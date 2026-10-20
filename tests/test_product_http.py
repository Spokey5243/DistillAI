"""Authenticated loopback business API contracts."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from distillai.config import Config
from distillai.runtime import Runtime
from distillai.server import create_app, get_runtime
from distillai.storage import Store


@contextmanager
def serving(server):
    if hasattr(server, "app"):
        with TestClient(server.app, base_url=server.url, follow_redirects=False) as client:
            server.client = client
            try:
                yield server
            finally:
                server.app.dependency_overrides.clear()
        return


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "data")
        self.config = Config(self.store)

    def request(self, server, path, *, method="GET", data=None, headers=None):
        response = server.client.request(method, path, json=data,
            headers={"Authorization": "Bearer " + server.token,
                     "Content-Type": "application/json", **(headers or {})})
        return response.status_code, response.json()

    def backend(self, execute=None):
        runtime = Runtime(self.store, self.config, execute or (lambda task, control: {}),
                          lambda task, result: None)
        self.addCleanup(runtime.close)
        app = create_app(runtime)
        app.dependency_overrides[get_runtime] = lambda: runtime
        server = app.state.control
        server.app = app
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
            query_path = "/v1/queries/" + "c" * 32
            code, queried = self.request(server, query_path, method="POST",
                data={"session_key": "synthetic", "query": identifier})
            self.assertEqual(code, 200)
            self.assertEqual(queried["status"], "completed")
            self.assertEqual(queried["result"]["items"][0]["record_ref"]["id"], identifier)
            self.assertEqual(self.request(server, query_path)[1], queried)
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
            for version in (True, "2", 2.0):
                with self.subTest(version=version):
                    self.assertEqual(self.request(server, "/v1/config", method="PUT",
                        data={"expected_version": version, "values": {}}), (409, {"error": {"code": "conflict"}}))
            code, invalid = self.request(server, "/v1/config", method="PUT", data={"expected_version": 2, "values": None})
            self.assertEqual(code, 422)
            self.assertEqual(invalid["error"], {"code": "invalid_config", "fields": {"values": "Expected an object"}})
            self.assertEqual(self.config.read()["version"], 2)

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

    def test_invalid_payloads_keep_errors_private_and_do_not_register_tasks(self):
        server, runtime = self.backend()
        identifier = "a" * 32
        with serving(server):
            cases = [
                ("POST", "/v1/tasks", {"kind": "query", "inputs": {}, "trigger": "synthetic", "private": "synthetic-secret"}, "invalid_task_request"),
                ("POST", "/v1/tasks", {"kind": True, "inputs": {}, "trigger": "synthetic"}, "invalid_request"),
                ("POST", "/v1/tasks", {"kind": "query", "inputs": {}, "trigger": "synthetic", "dependencies": "synthetic-secret"}, "invalid_request"),
                ("PUT", "/v1/config", {"values": {}}, "invalid_config_request"),
                ("POST", "/v1/queries/" + identifier, {"session_key": "synthetic", "query": 1}, "invalid_request"),
                ("POST", "/v1/queries/" + identifier, {"session_key": "synthetic", "query": "synthetic", "knowledge_refs": [{"id": identifier, "version": True}]}, "invalid_request"),
                ("POST", "/v1/tasks/" + identifier + "/cancel", {"reason": False}, "invalid_cancel_request"),
                ("POST", "/v1/tasks/" + identifier + "/retry", {"private": "synthetic-secret"}, "invalid_retry_request"),
                ("POST", "/v1/material-notifications", {"connector": "codex", "session_key": "../private"}, "invalid_material_notification"),
                ("POST", "/internal/stop", {"private": "synthetic-secret"}, "invalid_stop_request"),
            ]
            for method, path, payload, expected in cases:
                with self.subTest(path=path, payload=payload):
                    self.assertEqual(self.request(server, path, method=method, data=payload), (422, {"error": {"code": expected}}))
            self.assertEqual(self.request(server, "/v1/tasks", method="POST", data={"kind": True},
                headers={"Authorization": "Bearer wrong"}), (401, {"error": {"code": "unauthorized"}}))
            self.assertEqual(runtime.tasks(), [])
            self.assertTrue(runtime._accepting)
            self.assertEqual(self.config.read()["version"], 1)

    def test_quarantined_health_and_stop_do_not_wait_for_a_failing_publication_lock(self):
        server, runtime = self.backend()
        self.store.state.failed = True
        answered = threading.Event()
        responses = []
        with serving(server):
            def health():
                try:
                    responses.append(self.request(server, "/v1/health"))
                    responses.append(self.request(server, "/internal/stop", method="POST", data={}))
                finally:
                    answered.set()
            thread = threading.Thread(target=health)
            try:
                with self.store.locked():
                    thread.start()
                    self.assertTrue(answered.wait(2), "Health or stop waited for the failing writer's data lock")
            finally:
                thread.join(3)
            self.assertEqual(responses[0][0], 200)
            self.assertFalse(responses[0][1]["ready"])
            self.assertEqual(responses[1], (202, {"stopping": True}))
            self.assertFalse(runtime._accepting)
            self.assertTrue(server.stopping.is_set())

    def test_oversized_control_body_is_rejected(self):
        server, _ = self.backend()
        with serving(server):
            code, _ = self.request(server, "/v1/tasks", method="POST", data={"padding": "x" * (1024 * 1024)})
            self.assertEqual(code, 413)





if __name__ == "__main__":
    unittest.main()
