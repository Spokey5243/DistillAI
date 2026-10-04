from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


HOOK_PATH = Path(__file__).with_name("pre_push_guard.py")


def load_guard():
    if not HOOK_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("pre_push_guard", HOOK_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class RepositoryFixture:
    def __init__(self, root: Path, base_branch: str = "main") -> None:
        self.base_branch = base_branch
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.updater = root / "updater"
        git(root, "init", "--bare", str(self.origin))
        git(root, "clone", str(self.origin), str(self.work))
        self._configure(self.work)
        (self.work / "seed.txt").write_text("seed\n", encoding="utf-8")
        git(self.work, "add", "seed.txt")
        git(self.work, "commit", "-m", "seed")
        git(self.work, "branch", "-M", base_branch)
        git(self.origin, "symbolic-ref", "HEAD", f"refs/heads/{base_branch}")
        git(self.work, "push", "-u", "origin", base_branch)
        git(self.work, "checkout", "-b", "feat/test")
        git(self.work, "push", "-u", "origin", "HEAD")

    @staticmethod
    def _configure(repo: Path) -> None:
        git(repo, "config", "user.name", "Codex Test")
        git(repo, "config", "user.email", "codex-test@example.invalid")

    def advance_main(self) -> None:
        git(self.origin.parent, "clone", str(self.origin), str(self.updater))
        self._configure(self.updater)
        (self.updater / "seed.txt").write_text("seed\nupdated\n", encoding="utf-8")
        git(self.updater, "add", "seed.txt")
        git(self.updater, "commit", "-m", "advance main")
        git(self.updater, "push", "origin", self.base_branch)


class PrePushGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = load_guard()
        self.assertIsNotNone(self.guard, "pre_push_guard.py has not been implemented")
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.fixture = RepositoryFixture(Path(self.tempdir.name))

    def payload(self, command: str) -> dict:
        return {"tool_input": {"command": command}}

    def test_non_push_command_is_allowed(self) -> None:
        for command in ("git status", "git -P status"):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertEqual({"allow": True}, decision)

    def test_supported_push_is_allowed_when_head_contains_origin_main(self) -> None:
        for command in (
            "git push",
            "git push -u origin HEAD",
            "git push --set-upstream origin HEAD",
        ):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertEqual({"allow": True}, decision)

    def test_unsupported_push_form_is_denied(self) -> None:
        other_repo = self.fixture.origin.parent / "other repo"
        for command in (
            f'git -C "{other_repo}" push origin HEAD',
            "git -P push",
            "git --no-pager push",
            "git --work-tree=. push",
            "git --config-env=http.extraHeader=HDR push",
            f'cd "{other_repo}"; git push origin HEAD',
            "git push other HEAD",
            "git push origin HEAD:main",
            "git push https://example.invalid/repo.git HEAD",
        ):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertFalse(decision["allow"])
                self.assertIn("目标仓库", decision["reason"])

    def test_multiline_or_control_flow_push_is_denied(self) -> None:
        for command in (
            "echo ok\ngit push origin HEAD:main",
            "if true; then git push origin HEAD:main; fi",
            "if true; then\n  git push origin HEAD:main\nfi",
        ):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertFalse(decision["allow"])
                self.assertIn("目标仓库", decision["reason"])

    def test_plain_push_rejects_nonstandard_target_config(self) -> None:
        settings = (
            ("branch.feat/test.remote", "other"),
            ("branch.feat/test.merge", "refs/heads/main"),
            ("remote.pushDefault", "other"),
            ("branch.feat/test.pushRemote", "other"),
            ("remote.origin.push", "HEAD:main"),
            ("remote.origin.mirror", "true"),
            ("remote.origin.mirror", "1"),
            ("remote.origin.mirror", "yes"),
            ("remote.origin.mirror", "on"),
            ("push.default", "matching"),
        )
        for key, value in settings:
            with self.subTest(key=key):
                try:
                    original = git(self.fixture.work, "config", "--get", key)
                except subprocess.CalledProcessError:
                    original = None
                git(self.fixture.work, "config", key, value)
                try:
                    decision = self.guard.evaluate(self.payload("git push"), self.fixture.work)
                    self.assertFalse(decision["allow"])
                    self.assertIn("目标仓库", decision["reason"])
                finally:
                    if original is not None:
                        git(self.fixture.work, "config", key, original)
                    else:
                        git(self.fixture.work, "config", "--unset", key)

    def test_push_rejects_different_origin_push_url(self) -> None:
        git(self.fixture.work, "remote", "set-url", "--push", "origin", "other-repository")
        for command in ("git push", "git push -u origin HEAD"):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertFalse(decision["allow"])
                self.assertIn("目标仓库", decision["reason"])

    def test_push_rejects_multiple_origin_push_urls(self) -> None:
        origin_url = git(self.fixture.work, "remote", "get-url", "origin")
        git(self.fixture.work, "remote", "set-url", "--add", "--push", "origin", origin_url)
        git(
            self.fixture.work,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            "other-repository",
        )
        for command in ("git push", "git push -u origin HEAD"):
            with self.subTest(command=command):
                decision = self.guard.evaluate(self.payload(command), self.fixture.work)
                self.assertFalse(decision["allow"])
                self.assertIn("目标仓库", decision["reason"])

    def test_stale_branch_is_denied_without_marker(self) -> None:
        self.fixture.advance_main()
        decision = self.guard.evaluate(
            self.payload("git push"), self.fixture.work
        )
        self.assertFalse(decision["allow"])
        self.assertIn("远端 main 已更新", decision["reason"])

    def test_matching_marker_allows_once(self) -> None:
        self.fixture.advance_main()
        first = self.guard.evaluate(
            self.payload("git push"), self.fixture.work
        )
        self.assertFalse(first["allow"])

        marker = self.guard.authorize(self.fixture.work)
        self.assertTrue(marker.exists())
        allowed = self.guard.evaluate(
            self.payload("git push"), self.fixture.work
        )
        self.assertEqual({"allow": True}, allowed)
        self.assertFalse(marker.exists())

        denied_again = self.guard.evaluate(
            self.payload("git push"), self.fixture.work
        )
        self.assertFalse(denied_again["allow"])

    def test_fetch_failure_is_denied(self) -> None:
        git(self.fixture.work, "remote", "set-url", "origin", "missing-origin")
        decision = self.guard.evaluate(
            self.payload("git push"), self.fixture.work
        )
        self.assertFalse(decision["allow"])
        self.assertIn("Push 前检查失败", decision["reason"])


    def test_actual_remote_default_branch_is_used(self) -> None:
        for branch in ("master", "trunk"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as folder:
                fixture = RepositoryFixture(Path(folder), base_branch=branch)
                allowed = self.guard.evaluate(self.payload("git push"), fixture.work)
                self.assertEqual({"allow": True}, allowed)
                fixture.advance_main()
                denied = self.guard.evaluate(self.payload("git push"), fixture.work)
                self.assertFalse(denied["allow"])
                self.assertIn(f"远端 {branch} 已更新", denied["reason"])

    def test_default_branch_and_detached_head_are_denied(self) -> None:
        for ref in ("main", "--detach"):
            with self.subTest(ref=ref):
                git(self.fixture.work, "checkout", ref)
                decision = self.guard.evaluate(self.payload("git push -u origin HEAD"), self.fixture.work)
                self.assertFalse(decision["allow"])
                git(self.fixture.work, "checkout", "feat/test")

    def test_missing_remote_default_branch_fails_closed(self) -> None:
        git(self.fixture.origin, "symbolic-ref", "HEAD", "refs/heads/missing")
        decision = self.guard.evaluate(self.payload("git push"), self.fixture.work)
        self.assertFalse(decision["allow"])
        self.assertIn("默认分支", decision["reason"])

    def test_marker_is_invalid_after_head_changes(self) -> None:
        self.fixture.advance_main()
        self.guard.evaluate(self.payload("git push"), self.fixture.work)
        self.guard.authorize(self.fixture.work)
        (self.fixture.work / "feature.txt").write_text("change", encoding="utf-8")
        git(self.fixture.work, "add", "feature.txt")
        git(self.fixture.work, "commit", "-m", "change head")
        decision = self.guard.evaluate(self.payload("git push"), self.fixture.work)
        self.assertFalse(decision["allow"])

    def test_marker_is_invalid_after_remote_changes(self) -> None:
        self.fixture.advance_main()
        self.guard.evaluate(self.payload("git push"), self.fixture.work)
        self.guard.authorize(self.fixture.work)
        (self.fixture.updater / "seed.txt").write_text("third", encoding="utf-8")
        git(self.fixture.updater, "add", "seed.txt")
        git(self.fixture.updater, "commit", "-m", "advance again")
        git(self.fixture.updater, "push", "origin", "main")
        decision = self.guard.evaluate(self.payload("git push"), self.fixture.work)
        self.assertFalse(decision["allow"])

    def test_malformed_payload_is_denied(self) -> None:
        for payload in ([], {"tool_input": []}, {"tool_input": {"command": 42}}):
            with self.subTest(payload=payload):
                self.assertFalse(self.guard.evaluate(payload, self.fixture.work)["allow"])


if __name__ == "__main__":
    unittest.main()
