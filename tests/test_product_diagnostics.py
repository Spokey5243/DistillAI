"""Diagnostics retain attribution without payloads, and cannot block product work."""
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from distillai.config import Config
from distillai.diagnostics import diagnostic_sink
from distillai.mcp import run_stdio
from distillai.runtime import Runtime
from distillai.storage import Store


def records(home):
    result = []
    for path in (Path(home) / "logs").glob("*"):
        data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        result.extend(json.loads(line) for line in data.decode("utf-8").splitlines())
    return result


class DiagnosticTests(unittest.TestCase):
    def test_task_failure_logs_identity_and_code_without_source_key_or_exception_body(self):
        def execute(task, control):
            raise ValueError("PRIVATE_EXCEPTION_BODY")
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            config = Config(store)
            config.update(1, {"llm": {"api_key": "PRIVATE_MODEL_KEY"}})
            runtime = Runtime(store, config, execute, lambda task, result: None)
            try:
                with diagnostic_sink(temporary, "backend"):
                    task = runtime.register("query", {"text": "PRIVATE_SOURCE_BODY"}, "synthetic")
                    runtime.dispatch()
                    self.assertEqual(runtime.wait(task["id"], timeout=3)["status"], "failed")
                saved = records(temporary)
                self.assertTrue(any(item["record"]["extra"].get("task_id") == task["id"]
                    and item["record"]["extra"].get("error_code") == "ValueError" for item in saved))
                self.assertNotIn("PRIVATE_", json.dumps(saved))
                self.assertTrue(all(item["record"]["exception"] is None for item in saved))
            finally:
                runtime.close()

    def test_two_capture_processes_own_separate_flushed_logs(self):
        code = ("import os,sys;from distillai.capture import diagnostic;"
                "diagnostic(sys.argv[1],'Stop','synthetic','queue',OSError('PRIVATE_EXCEPTION_BODY'));print(os.getpid())")
        with tempfile.TemporaryDirectory() as temporary:
            children = [subprocess.Popen([sys.executable, "-c", code, temporary], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE) for _ in range(2)]
            try:
                owners_expected = set()
                for child in children:
                    output, error = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 0, error)
                    self.assertTrue(output.strip().isdigit(), output)
                    owners_expected.add(int(output))  # Windows venv launchers have a different PID.
                seen = set()
                for path in (Path(temporary) / "logs").glob("*"):
                    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
                    self.assertNotIn(b"PRIVATE_", data)
                    owners = {json.loads(line)["record"]["process"]["id"] for line in data.splitlines()}
                    self.assertEqual(len(owners), 1)
                    seen.update(owners)
                self.assertEqual(len(owners_expected), 2)
                self.assertEqual(seen, owners_expected)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=5)

    def test_log_setup_failure_does_not_prevent_stdio_transport_from_running(self):
        server = Mock()
        with tempfile.TemporaryDirectory() as temporary, patch("distillai.diagnostics.logger.add",
                side_effect=OSError("PRIVATE_LOG_PATH")), patch("distillai.mcp.create_server", return_value=server):
            run_stdio(temporary)
        server.run.assert_called_once_with(transport="stdio", show_banner=False)


if __name__ == "__main__":
    unittest.main()
