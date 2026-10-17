"""Capture keeps conversational text and never advances past unsaved queue bytes."""
import json
import gzip
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import socket
import threading
import time
import unittest
from unittest.mock import patch

from distillai.capture import capture, notify, parse_rollout, session_key, summarize_tool
from distillai.sources import read_source
from distillai.windows import FileHandle


FIXTURES = Path(__file__).parent / "fixtures"


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.payload = {"hook_event_name": "Stop", "session_id": "synthetic/session",
                        "transcript_path": str(FIXTURES / "codex-rollout.jsonl")}

    def queue(self):
        return self.home / "codex/queue/synthetic_session.jsonl"

    def cursor(self):
        return self.home / "codex/cursors/synthetic_session.json"

    def test_filter_preserves_intermediate_text_and_only_drops_known_user_prefixes(self):
        rows = parse_rollout(FIXTURES / "codex-rollout.jsonl")
        self.assertEqual([r["text"] for r in rows], ["question\nsecond text", "working", "answer",
                         "<unknown>keep", "prefix <environment_context>keep", "<environment_context>assistant"])
        self.assertEqual(rows[0]["at"], "2026-10-14T01:00:00Z")
        self.assertNotIn("at", rows[1])
        self.assertEqual(session_key("完整/a-b_c.9"), "___a-b_c_9")

    def test_tool_summaries_match_fixed_rules_without_response(self):
        for case in json.loads((FIXTURES / "codex-tools.json").read_text(encoding="utf-8")):
            with self.subTest(case=case):
                self.assertEqual(summarize_tool(case.get("tool_name"), case.get("tool_input")), case["expected"])

    def test_capture_is_incremental_and_tools_do_not_count_as_body(self):
        self.assertEqual(capture(self.home, self.payload), "saved")
        initial = self.queue().read_bytes()
        self.assertNotIn(b"\xef\xbb\xbf", initial)
        self.assertEqual(initial.count(b"\n"), 6)
        self.assertEqual(capture(self.home, self.payload), "unchanged")
        self.assertEqual(self.queue().read_bytes(), initial)
        tool = {"hook_event_name": "PostToolUse", "session_id": "synthetic/session",
                "tool_name": "Bash", "tool_input": {"command": "python build.py"}, "tool_response": "PRIVATE"}
        self.assertEqual(capture(self.home, tool), "saved")
        self.assertEqual(json.loads(self.cursor().read_text())["count"], 6)
        source = read_source(self.home, {"connector": "codex", "session_key": "synthetic_session", "line_start": 7, "line_end": 7})
        self.assertEqual(source["rows"][0]["text"], "ran: python build.py")
        self.assertNotIn(b"PRIVATE", self.queue().read_bytes())

    def test_cursor_failures_and_out_of_range_restart_without_destroying_old_sources(self):
        with patch("distillai.capture.atomic_json", side_effect=OSError("synthetic")):
            self.assertEqual(capture(self.home, self.payload), "error")
        first = self.queue().read_bytes()
        self.assertFalse(self.cursor().exists())
        self.assertEqual(capture(self.home, self.payload), "saved")
        self.assertEqual(self.queue().read_bytes(), first + first)
        for cursor in ({"count": 99, "at": "2026-10-14T00:00:00Z"}, {"count": True}, {"count": 2, "at": "bad"}):
            self.cursor().write_text(json.dumps(cursor))
            before = self.queue().read_bytes()
            capture(self.home, self.payload)
            self.assertEqual(self.queue().read_bytes(), before + first)

    def test_queue_sync_failure_does_not_advance_cursor_and_diagnostics_have_no_body(self):
        with patch("distillai.capture.FileHandle.write", side_effect=OSError("SECRET BODY")):
            self.assertEqual(capture(self.home, self.payload), "error")
        self.assertFalse(self.cursor().exists())
        log = "".join(gzip.decompress(path.read_bytes()).decode("utf-8") for path in (self.home / "logs").glob("capture-*.jsonl.gz"))
        self.assertTrue(log)
        self.assertNotIn("SECRET", log)
        self.assertNotIn("question", log)
        self.assertEqual(capture(self.home, self.payload), "saved")

    def test_competing_process_returns_busy_and_does_not_touch_cursor(self):
        capture(self.home, self.payload)
        before = self.queue().read_bytes()
        code = "import sys;from distillai.capture import capture;print(capture(sys.argv[1], {'hook_event_name':'PostToolUse','session_id':'synthetic/session','tool_name':'build'}))"
        with FileHandle(self.queue(), writable=True):
            result = subprocess.run([sys.executable, "-c", code, str(self.home)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "busy")
        self.assertEqual(self.queue().read_bytes(), before)

    def test_missing_transcript_session_or_filtered_tool_does_not_advance(self):
        for payload in ({"hook_event_name": "Stop"}, {"hook_event_name": "PreCompact", "session_id": "x"},
                        {"hook_event_name": "Stop", "session_id": "x", "transcript_path": str(self.home / "missing")},
                        {"hook_event_name": "PostToolUse", "session_id": "x", "tool_name": "Bash", "tool_input": {"command": "rg x"}}):
            capture(self.home, payload)
        self.assertEqual(list(self.home.glob("codex/cursors/*.json")), [])

    def test_unfinished_utf8_rollout_tail_waits_and_codex_patch_command_is_adapted(self):
        transcript = self.home / "rollout.jsonl"
        complete = {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "kept"}}
        transcript.write_bytes(json.dumps(complete).encode() + b'\n{"unfinished":"' + bytes([0xe4, 0xb8]))
        self.assertEqual(parse_rollout(transcript), [{"role": "user", "text": "kept"}])
        payload = {"hook_event_name": "PostToolUse", "session_id": "synthetic/session", "tool_name": "apply_patch",
                   "tool_input": {"command": "*** Update File: synthetic.py"}}
        capture(self.home, payload)
        self.assertEqual(json.loads(self.queue().read_text())["text"], "edited: synthetic.py")

    def test_dispatcher_always_returns_empty_object_with_zero_status(self):
        script = Path(__file__).parents[1] / "plugins/distillai/hooks/dispatch.py"
        for payload in ("not json", json.dumps(self.payload), json.dumps({"hook_event_name": "Stop"})):
            result = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, text=True,
                                    env={**os.environ, "DISTILLAI_HOME": str(self.home)}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "{}")

    def test_dispatcher_accepts_utf8_pipes_with_windows_legacy_encoding(self):
        transcript = self.home / "合成会话.jsonl"
        transcript.write_text(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": "中文"}}, ensure_ascii=False), encoding="utf-8")
        payload = {**self.payload, "session_id": "合成", "transcript_path": str(transcript)}
        result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "plugins/distillai/hooks/dispatch.py")],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=5,
            env={**os.environ, "DISTILLAI_HOME": str(self.home), "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp936"})
        self.assertEqual((result.returncode, result.stdout.strip()), (0, b"{}"))
        self.assertEqual(json.loads((self.home / "codex/queue/__.jsonl").read_text(encoding="utf-8"))["text"], "中文")

    def test_notification_does_not_wait_for_response_or_send_body(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.addCleanup(listener.close)
        received, finished = [], threading.Event()

        def accept():
            with listener.accept()[0] as client:
                client.settimeout(2)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += client.recv(8192)
                headers, body = request.split(b"\r\n\r\n", 1)
                length = int(next(line.split(b":")[1] for line in headers.split(b"\r\n") if line.startswith(b"Content-Length:")))
                while len(body) < length:
                    body += client.recv(8192)
                received.append(json.loads(body))
                finished.wait(2)

        thread = threading.Thread(target=accept)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(finished.set)
        (self.home / "instance.json").write_text(json.dumps({"url": f"http://127.0.0.1:{listener.getsockname()[1]}", "token": "synthetic"}))
        started = time.monotonic()
        capture(self.home, self.payload)
        self.assertLess(time.monotonic() - started, .5)
        finished.set()
        thread.join(2)
        self.assertEqual(received, [{"connector": "codex", "session_key": "synthetic_session"}])
        listener.close()
        started = time.monotonic()
        notify(self.home, "synthetic_session")
        self.assertLess(time.monotonic() - started, .5)


if __name__ == "__main__":
    unittest.main()
