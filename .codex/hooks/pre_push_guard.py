from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


SUPPORTED_PUSH_COMMAND = re.compile(
    r"^git\s+push(?:\s+(?:-u|--set-upstream)\s+origin\s+HEAD)?\s*$",
    re.IGNORECASE,
)


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _sha(repo_root: Path, ref: str) -> str:
    return _git(repo_root, "rev-parse", ref).stdout.strip()


def _config(repo_root: Path, key: str, *, as_bool: bool = False) -> str | None:
    args = ("config", "--bool", "--get", key) if as_bool else ("config", "--get", key)
    result = _git(repo_root, *args, check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise RuntimeError(f"无法读取 Git 配置 {key}: {result.stderr.strip()}")
    return result.stdout.strip()


def _marker_path(repo_root: Path) -> Path:
    raw = _git(repo_root, "rev-parse", "--git-path", "codex/push-allow.json").stdout.strip()
    path = Path(raw)
    return path if path.is_absolute() else repo_root / path


def _default_branch(repo_root: Path) -> str:
    result = _git(repo_root, "ls-remote", "--symref", "origin", "HEAD", check=False)
    if result.returncode != 0:
        raise RuntimeError("无法获取远端默认分支；请检查 origin 和网络")
    match = re.search(r"^ref: refs/heads/([^\s]+)\s+HEAD$", result.stdout, re.MULTILINE)
    if match is None:
        raise RuntimeError("无法确定远端默认分支；空仓库首次初始化须由用户确认")
    branch = match.group(1)
    _git(repo_root, "check-ref-format", f"refs/heads/{branch}")
    return branch


def evaluate(payload: dict, repo_root: Path) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return {"allow": False, "reason": "无效的 Hook 输入，无法检查 Push"}
    command = payload["tool_input"].get("command")
    if not isinstance(command, str):
        return {"allow": False, "reason": "Hook command 必须是文本"}
    if SUPPORTED_PUSH_COMMAND.fullmatch(command.strip()) is None:
        if not (
            re.search(r"\bgit\b", command, re.IGNORECASE)
            and re.search(r"\bpush\b", command, re.IGNORECASE)
        ):
            return {"allow": True}
        return {
            "allow": False,
            "reason": (
                "无法确认 Push 的目标仓库和分支；仅支持 git push 或 "
                "git push -u origin HEAD。"
            ),
        }

    try:
        branch = _git(repo_root, "branch", "--show-current").stdout.strip()
        if not branch:
            return {"allow": False, "reason": "detached HEAD 不允许 Push。"}
        fetch_urls = _git(repo_root, "remote", "get-url", "--all", "origin").stdout.splitlines()
        push_urls = _git(
            repo_root, "remote", "get-url", "--push", "--all", "origin"
        ).stdout.splitlines()
        if len(fetch_urls) != 1 or push_urls != fetch_urls:
            return {
                "allow": False,
                "reason": "无法确认 Push 的目标仓库；origin 的获取/推送地址不唯一或不一致。",
            }
        base_branch = _default_branch(repo_root)
        if branch == base_branch:
            return {"allow": False, "reason": f"仓库规则禁止直接 Push 默认分支 {base_branch}。"}
        if re.fullmatch(r"git\s+push", command.strip(), re.IGNORECASE):
            if (
                _config(repo_root, f"branch.{branch}.remote") != "origin"
                or _config(repo_root, f"branch.{branch}.merge") != f"refs/heads/{branch}"
                or _config(repo_root, "push.default") not in (None, "simple")
                or _config(repo_root, "remote.pushDefault") is not None
                or _config(repo_root, f"branch.{branch}.pushRemote") is not None
                or _config(repo_root, "remote.origin.push") is not None
                or _config(repo_root, "remote.origin.mirror", as_bool=True) == "true"
            ):
                return {
                    "allow": False,
                    "reason": "无法确认 Push 的目标仓库和分支；请检查 upstream 与 Git Push 配置。",
                }

        base_ref = f"refs/remotes/origin/{base_branch}"
        fetch = _git(repo_root, "fetch", "origin", f"+refs/heads/{base_branch}:{base_ref}", check=False)
        if fetch.returncode != 0:
            return {
                "allow": False,
                "reason": f"无法获取 origin/{base_branch}，已取消本次 Push；请检查远端和网络。",
            }

        head_sha = _sha(repo_root, "HEAD")
        base_sha = _sha(repo_root, base_ref)
        ancestor = _git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            base_ref,
            "HEAD",
            check=False,
        )
        if ancestor.returncode == 0:
            return {"allow": True}
        if ancestor.returncode != 1:
            return {
                "allow": False,
                "reason": f"无法判断当前分支是否包含 origin/{base_branch}，已取消本次 Push。",
            }

        marker = _marker_path(repo_root)
        if marker.exists():
            try:
                saved = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                saved = {}
            marker.unlink(missing_ok=True)
            if saved == {"head_sha": head_sha, "base_branch": base_branch, "base_sha": base_sha, "origin_url": fetch_urls[0]}:
                return {"allow": True}
        return {"allow": False, "reason": f"远端 {base_branch} 已更新，当前分支尚未包含最新提交；请询问用户是否仍继续 Push。"}
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {
            "allow": False,
            "reason": f"Push 前检查失败，已取消本次 Push：{exc}",
        }


def authorize(repo_root: Path) -> Path:
    branch = _git(repo_root, "branch", "--show-current").stdout.strip()
    base_branch = _default_branch(repo_root)
    if not branch or branch == base_branch:
        raise RuntimeError("只能为非默认分支创建一次性 Push 放行标记")
    base_ref = f"refs/remotes/origin/{base_branch}"
    _git(repo_root, "fetch", "origin", f"+refs/heads/{base_branch}:{base_ref}")
    marker = _marker_path(repo_root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "head_sha": _sha(repo_root, "HEAD"),
                "base_branch": base_branch,
                "base_sha": _sha(repo_root, base_ref),
                "origin_url": _git(repo_root, "remote", "get-url", "origin").stdout.strip(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return marker


def _repository_root() -> Path:
    return Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        repo_root = _repository_root()
        if args == ["authorize"]:
            print(authorize(repo_root))
            return 0
        payload = json.load(sys.stdin)
        decision = evaluate(payload, repo_root)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
        decision = {"allow": False, "reason": f"Push 前检查失败：{exc}"}

    if decision["allow"]:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": decision["reason"],
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
