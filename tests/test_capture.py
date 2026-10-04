"""Run: python tests/test_capture.py (Windows, no dependencies)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/distill-capture/hooks/capture.py"


def main():
    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, "DISTILLAI_HOME": directory}

        def invoke(payload, platform=None):
            raw = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
            args = [sys.executable, str(SCRIPT)]
            if platform:
                args += ["--platform", platform]
            result = subprocess.run(
                args, input=raw.encode("utf-8"),
                capture_output=True, env=env, timeout=15,
            )
            assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
            assert json.loads(result.stdout) == {}, result.stdout

        prompt = {
            "session_id": "test-session", "turn_id": "turn-1",
            "hook_event_name": "UserPromptSubmit", "prompt": "中文🙂\n第二行",
            "cwd": "E:/示例", "model": "test-model", "transcript_path": None,
            "future_field": {"keep": True},
        }
        invoke(prompt)
        invoke({**prompt, "hook_event_name": "Stop", "last_assistant_message": "收到"})
        path = Path(directory) / "data/sessions/test-session.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 2
        assert rows[0]["payload"] == prompt
        assert rows[0]["role"] == "user" and rows[1]["role"] == "assistant"
        assert rows[1]["payload"]["last_assistant_message"] == "收到"
        assert rows[0]["platform"] == "codex" and rows[0]["schema_version"] == 1
        assert rows[0]["captured_at"].endswith("+00:00")
        invoke({**prompt, "session_id": "other-session"})
        assert (path.parent / "other-session.jsonl").exists()
        # zcode shape: no turn_id; source platform comes from --platform.
        zcode_prompt = {k: v for k, v in prompt.items() if k not in ("turn_id", "session_id")}
        invoke({**zcode_prompt, "session_id": "zcode-session"}, platform="zcode")
        invoke({**zcode_prompt, "session_id": "zcode-session", "hook_event_name": "Stop",
                "last_assistant_message": "ok"}, platform="zcode")
        zpath = path.parent / "zcode-session.jsonl"
        zrows = [json.loads(line) for line in zpath.read_text(encoding="utf-8").splitlines()]
        assert [r["platform"] for r in zrows] == ["zcode", "zcode"]
        assert all(r["turn_id"] is None for r in zrows)
        # Stop without a message field still records the payload (assistant role).
        invoke({**zcode_prompt, "session_id": "zcode-session", "hook_event_name": "Stop"},
               platform="zcode")
        # Invalid platform value falls back to the codex default.
        invoke({**zcode_prompt, "session_id": "zcode-session", "prompt": "p2"},
               platform="BAD/PLATFORM")
        zrows = [json.loads(line) for line in zpath.read_text(encoding="utf-8").splitlines()]
        assert zrows[2]["role"] == "assistant" and zrows[2]["payload"].get("last_assistant_message") is None
        assert zrows[3]["platform"] == "codex"
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(invoke, [{**prompt, "prompt": f"并发-{i}"} for i in range(20)]))
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 22 and len({row["event_id"] for row in rows}) == 22
        assert {r["payload"].get("prompt") for r in rows[2:]} == {f"并发-{i}" for i in range(20)}
        for invalid in ["{broken", [], {**prompt, "session_id": "../escape"},
                        {**prompt, "session_id": "CON"}, {**prompt, "prompt": 42}]:
            invoke(invalid if isinstance(invalid, (dict, str)) else json.dumps(invalid))
        assert len(path.read_text(encoding="utf-8").splitlines()) == 22
        assert len((Path(directory) / "logs/capture-errors.log").read_text().splitlines()) == 5
        assert not (Path(directory) / "data/escape.jsonl").exists()
    print("PASS: UTF-8, payload, append, session isolation, concurrency, invalid input, fail-open, platform override")


if __name__ == "__main__":
    main()
