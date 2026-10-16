"""Loopback control API and fixed-target model forwarding contracts."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler, Request
from unittest.mock import patch

from distillai.config import Config
from distillai.runtime import BudgetError, Runtime
from distillai.server import BackendServer
from distillai.storage import Store


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "data")
        self.config = Config(self.store)
        self.opener = build_opener(ProxyHandler({}))

    def request(self, server, path, *, method="GET", data=None, headers=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(server.url + path, data=body, method=method,
                          headers={"Authorization": "Bearer " + server.token,
                                   "Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def backend(self, execute=None):
        runtime = Runtime(self.store, self.config, execute or (lambda task, control: {}),
                          lambda task, result: None)
        self.addCleanup(runtime.close)
        server = BackendServer(runtime)
        return server, runtime

    def test_health_auth_origin_host_and_unknown_route(self):
        server, _ = self.backend()
        with serving(server):
            code, result = self.request(server, "/v1/health")
            self.assertEqual(code, 200)
            self.assertEqual(result["instance_id"], server.instance_id)
            self.assertEqual(self.request(server, "/v1/health", headers={"Authorization": "Bearer wrong"})[0], 401)
            self.assertEqual(self.request(server, "/v1/health", headers={"Origin": "https://outside.test"})[0], 403)
            self.assertEqual(self.request(server, "/v1/health", headers={"Host": "outside.test"})[0], 403)
            self.assertEqual(self.request(server, "/v1/missing")[0], 404)

    def test_boundary_tool_is_task_scoped_records_scores_without_a_generation(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        candidate = {**ref, "line_start": 2, "line_end": 2}
        old = {"id": "a" * 32, "version": "b" * 64}
        context = {"session_key": "synthetic", "active_episode_ref": old, "active_source_refs": [ref],
                   "turns": [{"source_refs": [candidate]}],
                   "sources": [{"ref": ref, "rows": [{"role": "user", "text": "old goal"}]},
                               {"ref": candidate, "rows": [{"role": "user", "text": "new goal"}]}]}
        tokens = []

        def execute(task, control):
            with self.store.locked():
                saved = control.task(task["id"])
                saved["execution_input_version"] = self.store.put_version(json.dumps(context).encode())
                control._save(saved)
            tokens.append(control.issue_token(task["id"]))
            entered.set()
            release.wait(5)
            return {}

        server, runtime = self.backend(execute)
        task = runtime.register("episode", {}, "synthetic")
        with serving(server):
            runtime.dispatch()
            self.assertTrue(entered.wait(3))
            route = "/internal/tasks/" + task["id"] + "/tools/evaluate_episode_boundary"
            args = {"episode_ref": old, "episode_keywords": ["old"], "episode_source_refs": [ref],
                    "episode_basis": [{"source_ref": ref, "quote": "old goal"}],
                    "candidates": [{"source_refs": [candidate], "keywords": ["new"], "C": 0,
                                    "basis": [{"source_ref": candidate, "quote": "new goal"}], "reason": "new request", "group": "new goal"}]}
            self.assertEqual(self.request(server, route, method="POST", data=args)[0], 401)
            headers = {"Authorization": "Bearer " + tokens[0]}
            code, result = self.request(server, route, method="POST", data=args, headers=headers)
            self.assertEqual(code, 200)
            self.assertEqual(result["evaluations"][0]["S"], 4)
            self.assertIn(result["evaluation_version"], runtime.task(task["id"])["boundary_evaluations"])
            self.assertEqual(runtime.task(task["id"])["model_calls"], 0)
            allocation = "/internal/tasks/" + task["id"] + "/tools/new_record_id"
            self.assertEqual(self.request(server, allocation, method="POST", data={"record_kind": "knowledge"}, headers=headers)[0], 422)
            self.assertEqual(self.request(server, route, method="POST", data={}, headers=headers)[0], 422)
            self.assertEqual(self.request(server, route, method="POST", data=args, headers={**headers, "Origin": server.url})[0], 403)
            release.set()
            runtime.wait(task["id"])

    def test_knowledge_routes_keep_historical_versions_and_report_index_not_ready(self):
        from distillai.knowledge import KnowledgeIndex
        from distillai.storage import atomic_json
        identifier = "a" * 32
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic source"}\n', encoding="utf-8")
        record = {"id": identifier, "name": "Synthetic concept", "content": {"summary": "synthetic", "source_refs": [
            {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}]}}
        folder = self.store.home / "knowledge"
        folder.mkdir()
        atomic_json(folder / (identifier + ".json"), record)
        server, runtime = self.backend()
        runtime.knowledge_index = KnowledgeIndex(self.store)
        runtime.knowledge_index.rebuild()
        with serving(server):
            code, old = self.request(server, "/v1/records/knowledge/" + identifier)
            self.assertEqual(code, 200)
            self.assertEqual(self.request(server, "/v1/knowledge/lookup?name=%20SYNTHETIC%20CONCEPT%20")[1]["matches"][0]["id"], identifier)
            self.assertEqual(self.request(server, "/v1/knowledge/" + identifier + "/neighbors")[1], {"knowledge_refs": [], "relations": []})
            atomic_json(folder / (identifier + ".json"), {**record, "name": "Renamed concept"})
            runtime.knowledge_index.rebuild()
            self.assertEqual(self.request(server, "/v1/records/knowledge/" + identifier + "?version=" + old["version"])[1], old)
            self.assertEqual(self.request(server, "/v1/records/knowledge/" + "f" * 32)[0], 404)
            with patch.object(self.store, "_scan", side_effect=OSError("synthetic failure")), self.assertRaises(OSError):
                runtime.knowledge_index.rebuild()
            self.assertEqual(self.request(server, "/v1/knowledge/" + identifier + "/neighbors")[0], 503)
            self.assertEqual(self.request(server, "/v1/records/knowledge/" + identifier)[0], 200)

    def test_config_read_redacts_key_and_conflicting_update_is_409(self):
        self.config.update(1, {"llm": {"api_key": "synthetic-control-secret"}})
        server, _ = self.backend()
        with serving(server):
            _, result = self.request(server, "/v1/config")
            self.assertNotIn("synthetic-control-secret", str(result))
            self.assertEqual(self.request(server, "/v1/config", method="PUT",
                                          data={"expected_version": 1, "values": {}})[0], 409)
            self.assertEqual(self.request(server, "/v1/config", method="PUT",
                                          data={"expected_version": 2, "values": {"runtime": {"max_model_calls": 0}}})[0], 422)

    def test_task_dedup_lookup_notification_and_history(self):
        server, runtime = self.backend()
        with serving(server):
            payload = {"kind": "query", "inputs": {}, "trigger": "synthetic"}
            code, registered = self.request(server, "/v1/tasks", method="POST", data=payload)
            self.assertEqual(code, 202)
            task_id = registered["id"]
            self.assertEqual(self.request(server, "/v1/tasks", method="POST", data=payload)[1]["id"], task_id)
            self.assertEqual(self.request(server, "/v1/tasks/" + task_id)[0], 200)
            self.assertEqual(self.request(server, "/v1/tasks/" + "0" * 32)[0], 404)
            self.assertEqual(self.request(server, "/v1/material-notifications", method="POST",
                                          data={"connector": "codex", "session_key": "synthetic"})[0], 202)
            self.assertEqual(self.request(server, "/v1/history")[1]["items"][0]["id"], task_id)

    def test_slow_task_does_not_block_health_and_cancel_reports_202(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def execute(task, control):
            entered.set()
            self.assertTrue(release.wait(5))
            return {}

        server, runtime = self.backend(execute)
        with serving(server):
            task = runtime.register("query", {}, "synthetic")
            runtime.dispatch()
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.request(server, "/v1/health")[0], 200)
            self.assertEqual(self.request(server, "/v1/tasks/" + task["id"] + "/cancel", method="POST",
                                          data={"reason": "synthetic cancellation"})[0], 202)
            self.assertEqual(runtime.task(task["id"])["status"], "recovering")
            release.set()
            self.assertEqual(runtime.wait(task["id"])["status"], "cancelled")

    def test_oversized_control_body_is_rejected(self):
        server, _ = self.backend()
        with serving(server):
            code, _ = self.request(server, "/v1/tasks", method="POST", data={"padding": "x" * (1024 * 1024)})
            self.assertEqual(code, 413)

    def test_model_forwarder_counts_actual_attempts_and_stops_before_seventeenth(self):
        received = []

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), body))
                response = b'{"choices":[{"message":{"role":"assistant","content":"synthetic"}}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        with serving(provider):
            self.config.update(1, {"llm": {"base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                                           "model": "synthetic", "api_key": "synthetic-control-key"}})

            def execute(task, control):
                token = control.issue_token(task["id"])
                endpoint = server.model_base(task["id"]) + "/chat/completions"
                for _ in range(17):
                    request = Request(endpoint, data=json.dumps({"model": "synthetic", "messages": [
                        {"role": "user", "content": "synthetic"}]}).encode(),
                        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                    try:
                        with self.opener.open(request, timeout=3) as response:
                            response.read()
                    except HTTPError as response:
                        with response:
                            self.assertEqual(response.code, 400)
                            self.assertEqual(json.load(response)["error"]["code"], "budget_exhausted")
                        raise BudgetError("synthetic budget exhausted")

            server, runtime = self.backend(execute)
            with serving(server):
                task = runtime.register("query", {}, "synthetic")
                runtime.dispatch()
                self.assertEqual(runtime.wait(task["id"])["status"], "failed")
                self.assertEqual(runtime.task(task["id"])["model_calls"], 16)
        self.assertEqual(len(received), 16)
        self.assertTrue(all(path == "/v1/chat/completions" and auth == "Bearer synthetic-control-key"
                            for path, auth, _ in received))

    def test_known_unsent_request_releases_budget_but_uncertain_timeout_stays_counted(self):
        self.config.update(1, {"llm": {"base_url": "http://127.0.0.1:1/v1", "model": "synthetic"}})

        def execute(task, control):
            token = control.issue_token(task["id"])
            request = Request(server.model_base(task["id"]) + "/chat/completions",
                data=json.dumps({"model": "synthetic", "messages": [{"role": "user", "content": "synthetic"}]}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as error:
                self.opener.open(request, timeout=3)
            with error.exception:
                self.assertEqual(error.exception.code, 502)
            return {}

        server, runtime = self.backend(execute)
        with serving(server):
            for reason, expected in ((ConnectionRefusedError("not connected"), 0), (TimeoutError("unknown delivery"), 1)):
                with self.subTest(reason=type(reason).__name__), patch.object(server.opener, "open", side_effect=URLError(reason)):
                    task = runtime.register("query", {}, type(reason).__name__)
                    runtime.dispatch()
                    completed = runtime.wait(task["id"])
                    self.assertEqual(completed["status"], "succeeded")
                    self.assertEqual(completed["model_calls"], expected)

    def test_request_history_retains_actual_prompt_and_excludes_internal_reasoning(self):
        self.config.update(1, {"llm": {"base_url": "http://127.0.0.1:1/v1", "model": "synthetic"}})

        def execute(task, control):
            token = control.issue_token(task["id"])
            body = {"model": "synthetic", "messages": [
                {"role": "system", "content": "actual synthetic system prompt"},
                {"role": "assistant", "content": "visible text", "reasoning_content": "synthetic private reasoning"}]}
            request = Request(server.model_base(task["id"]) + "/chat/completions", data=json.dumps(body).encode(),
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as error:
                self.opener.open(request, timeout=3)
            error.exception.close()
            return {}

        server, runtime = self.backend(execute)
        with serving(server), patch.object(server.opener, "open", side_effect=URLError(TimeoutError())):
            task = runtime.register("query", {}, "history")
            runtime.dispatch()
            completed = runtime.wait(task["id"])
            snapshots = [self.store.read_version(attempt["request_version"]).decode("utf-8")
                         for attempt in completed["generation_attempts"].values()]
            self.assertEqual(len(snapshots), 1)
            self.assertIn("actual synthetic system prompt", snapshots[0])
            self.assertNotIn("synthetic private reasoning", snapshots[0])


if __name__ == "__main__":
    unittest.main()
