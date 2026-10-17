"""Read tools retain frozen source/version identity and reject missing lookup input."""
import json
import io
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from distillai.tools import register_read_tools


class Registry:
    def __init__(self):
        self.handlers = {}

    def register(self, **tool):
        self.handlers[tool["name"]] = tool["handler"]


class ToolTests(unittest.TestCase):
    def test_program_reply_rejects_extra_or_ambiguous_fields(self):
        import threading
        from distillai.hermes import HermesError, _program_tool
        for reply in ({"result": 42, "extra": "synthetic-private"},
                      {"result": 42, "error": {"code": "ValueError"}},
                      {"error": {"code": "ValueError", "extra": "synthetic-private"}}):
            frame = {"_channel_lock": threading.RLock(), "_channel": SimpleNamespace(
                send_bytes=lambda data: None, recv_bytes=lambda limit: json.dumps(reply).encode())}
            with self.subTest(reply=reply), self.assertRaisesRegex(HermesError, "Invalid program operation reply"):
                _program_tool(frame, "new_record_id", {"record_kind": "knowledge"})

    def test_invalid_pipe_bootstrap_does_not_open_a_connection(self):
        from distillai.hermes import HermesError, task_child
        valid = {"address": r"\\.\pipe\distillai-" + "a" * 32, "authkey": "00" * 32}
        for changed in ({"address": "arbitrary-pipe"}, {"authkey": "00"}, {"extra": "synthetic-private"}):
            payload = json.dumps({**valid, **changed}).encode()
            with self.subTest(changed=changed), patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(payload))), \
                    patch("multiprocessing.connection.Client", side_effect=OSError("synthetic connection refused")) as connect:
                with self.assertRaises((HermesError, ValueError, OSError)):
                    task_child()
                connect.assert_not_called()

    def test_failed_job_assignment_does_not_leave_a_suspended_child(self):
        from distillai.hermes import HermesExecutor
        from distillai.config import Config
        from distillai.runtime import Runtime
        from distillai.storage import Store
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run_agent.py").write_text("", encoding="utf-8")
            store = Store(root / "data")
            config = Config(store)
            config.update(1, {"llm": {"model": "synthetic", "base_url": "http://127.0.0.1/v1"}})
            executor = HermesExecutor(root, sys.executable,
                                      runtime_dir=root, base_python=sys._base_executable)
            runtime = Runtime(store, config, executor, lambda task, result: None)
            children = []
            popen = subprocess.Popen
            def remember(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append(child)
                return child
            try:
                with patch("distillai.hermes.subprocess.Popen", side_effect=remember), patch("distillai.windows.ProcessJob.assign", side_effect=[None, OSError("synthetic job failure")]):
                    task = runtime.register("query", {}, "synthetic launch")
                    runtime.dispatch()
                    done = runtime.wait(task["id"], 10)
                self.assertEqual(done["status"], "failed")
                self.assertTrue(children)
                self.assertIsNotNone(children[0].poll())
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait(5)
                runtime.close()

    def test_child_report_uses_utf8_pipe_and_keeps_stdout_clear(self):
        from distillai.hermes import HermesError, task_child
        class Agent:
            tools = []
            def __init__(self, **kwargs):
                pass
            def run_conversation(self, *args, **kwargs):
                return {"completed": True, "final_response": json.dumps({"reason": "⚠ 合成结果"}, ensure_ascii=False)}
            def close(self):
                pass
        loader = SimpleNamespace()
        registry = SimpleNamespace(registry=Registry())
        modules = {"hermes_cli": SimpleNamespace(env_loader=loader), "hermes_cli.env_loader": loader,
                   "run_agent": SimpleNamespace(AIAgent=Agent), "tools": SimpleNamespace(registry=registry), "tools.registry": registry,
                   "agent.ssl_verify": SimpleNamespace(resolve_httpx_verify=lambda **kwargs: True)}
        with tempfile.TemporaryDirectory() as temporary:
            frame = {"id": "a" * 32, "kind": "screening", "inputs": {}, "workspace": temporary,
                     "home": str(Path(temporary) / "hermes"), "llm": {"api": "chat_completions", "model": "synthetic", "base_url": "http://127.0.0.1/v1", "api_key": "", "parameters": {}},
                     "max_model_calls": 1, "prompt": "synthetic"}
            output = io.BytesIO()
            stdout = io.TextIOWrapper(output, encoding="gbk")
            messages = []
            from unittest.mock import Mock
            connection = SimpleNamespace(recv_bytes=Mock(side_effect=[json.dumps(frame).encode(), b'{"result":null}']),
                send_bytes=messages.append, close=Mock())
            bootstrap = {"address": r"\\.\pipe\distillai-" + "a" * 32, "authkey": "00" * 32}
            with patch.dict(sys.modules, modules), patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(bootstrap).encode()))), patch("multiprocessing.connection.Client", return_value=connection), patch("sys.stdout", stdout), patch("distillai.hermes.os.chdir"):
                task_child()
            self.assertEqual(json.loads(messages[0].decode("utf-8"))["arguments"]["result"]["reason"], "⚠ 合成结果")
            self.assertEqual(output.getvalue(), b"")
            stdout.detach()
            invalid_home = Path(temporary) / "invalid-home"
            invalid = {**frame, "home": str(invalid_home), "max_model_calls": True}
            connection.recv_bytes.side_effect = [json.dumps(invalid).encode(), b'{"result":null}']
            connection.close.reset_mock()
            with patch.dict(sys.modules, modules), patch("sys.stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(bootstrap).encode()))), \
                    patch("multiprocessing.connection.Client", return_value=connection), patch("distillai.hermes.os.chdir"):
                with self.assertRaises(HermesError):
                    task_child()
            self.assertFalse(invalid_home.exists())
            connection.close.assert_called_once()

    def test_record_lookup_preserves_version_and_alias(self):
        registry = Registry()
        record = {"id": "synthetic", "version": "frozen-version", "record": {"name": "Concept", "aliases": ["Alias"]}}
        register_read_tools(registry, {"records": [record]})
        result = json.loads(registry.handlers["query_records"]({"name": "alias"}))
        self.assertEqual(result["records"], [record])
        self.assertEqual(json.loads(registry.handlers["query_records"]({"id": "unknown"}))["records"], [])
        self.assertEqual(json.loads(registry.handlers["query_records"]({}))["error"]["code"], "invalid_query")
        for args in ({"name": 1}, {"name": "alias", "include_private": True}, {"version": "frozen-version"}):
            with self.subTest(args=args):
                self.assertEqual(json.loads(registry.handlers["query_records"](args))["error"]["code"], "invalid_query")

    def test_source_lookup_uses_exact_frozen_reference_and_reports_unavailable(self):
        registry = Registry()
        source = {"ref": {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 2}, "text": "synthetic source"}
        register_read_tools(registry, {"sources": [source]})
        self.assertEqual(json.loads(registry.handlers["read_source"]({"ref": source["ref"]}))["sources"], [source])
        self.assertEqual(json.loads(registry.handlers["read_source"]({"ref": {"line_start": 9}}))["error"]["code"], "source_not_in_task_snapshot")
        for ref in ({**source["ref"], "line_start": True}, {**source["ref"], "line_end": 2.0},
                    {**source["ref"], "path": "private.jsonl"}):
            with self.subTest(ref=ref):
                self.assertEqual(json.loads(registry.handlers["read_source"]({"ref": ref}))["error"]["code"], "source_not_in_task_snapshot")


if __name__ == "__main__":
    unittest.main()
