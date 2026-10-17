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





if __name__ == "__main__":
    unittest.main()
