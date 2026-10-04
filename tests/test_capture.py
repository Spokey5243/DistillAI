"""Run: python tests/test_capture.py (Windows, no dependencies)."""
import json
import msvcrt
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

        def invoke(payload, platform=None, timeout=15):
            raw = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
            args = [sys.executable, str(SCRIPT)]
            if platform:
                args += ["--platform", platform]
            result = subprocess.run(
                args, input=raw.encode("utf-8"),
                capture_output=True, env=env, timeout=timeout,
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
                        {**prompt, "session_id": "CON"}, {**prompt, "prompt": 42},
                        {**prompt, "hook_event_name": "PRIVATE-EVENT-CONTENT"},
                        {**prompt, "hook_event_name": {"body": "PRIVATE-EVENT-CONTENT"}}]:
            invoke(invalid if isinstance(invalid, (dict, str)) else json.dumps(invalid))
        assert len(path.read_text(encoding="utf-8").splitlines()) == 22
        error_text = (Path(directory) / "logs/capture-errors.log").read_text()
        assert len(error_text.splitlines()) == 7
        assert "PRIVATE-EVENT-CONTENT" not in error_text
        assert all(json.loads(line)["event"] == "unknown" for line in error_text.splitlines()[-2:])
        assert not (Path(directory) / "data/escape.jsonl").exists()
        # A busy session must fail open and report the error before the 5s Hook deadline.
        busy_path = path.parent / "busy-session.jsonl"
        with busy_path.open("a+b") as stream:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                invoke({**prompt, "session_id": "busy-session"}, timeout=4)
                assert busy_path.stat().st_size == 0
                errors = (Path(directory) / "logs/capture-errors.log").read_text().splitlines()
                assert len(errors) == 8
                error = json.loads(errors[-1])
                assert error["event"] == prompt["hook_event_name"] and error["error"]
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    print("PASS: UTF-8, payload, append, session isolation, concurrency, invalid input, fail-open, platform override, busy-lock deadline")


if __name__ == "__main__":
    main()
