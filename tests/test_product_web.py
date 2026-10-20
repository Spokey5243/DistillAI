"""Browser sessions exchange one-use bootstrap credentials and require CSRF for writes."""
import json
from pathlib import Path
from urllib.parse import urlencode
import tempfile
import unittest

from distillai.config import Config
from distillai.runtime import Runtime
from distillai.server import create_app, get_runtime
from fastapi.testclient import TestClient
from distillai.storage import Store, atomic_json


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = Store(Path(self.temp.name))
        self.runtime = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
        self.addCleanup(self.runtime.close)
        app = create_app(self.runtime)
        app.dependency_overrides[get_runtime] = lambda: self.runtime
        self.server = app.state.control
        self.client = self.enterContext(TestClient(app, base_url=self.server.url, follow_redirects=False))
        self.addCleanup(app.dependency_overrides.clear)

    def request(self, path, *, method="GET", body=None, headers=None):
        self.client.cookies.clear()
        response = self.client.request(method, path, json=body,
            headers={"Content-Type": "application/json", **(headers or {})})
        content = response.headers.get("Content-Type", "")
        value = (response.json() if "application/json" in content else response.text) if response.content else None
        return response.status_code, response.headers, value

    def session(self):
        status, _, body = self.request("/internal/web/bootstrap", method="POST", body={},
            headers={"Authorization": "Bearer " + self.server.token})
        self.assertEqual(status, 200)
        self.assertNotIn(self.server.token, body["url"])
        path = body["url"].removeprefix(self.server.url)
        status, headers, _ = self.request(path)
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("samesite=strict", headers["Set-Cookie"].lower())
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.request(path)[0], 401)
        status, _, body = self.request("/v1/web/session", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        return cookie, body["csrf_token"]

    def test_bootstrap_requires_control_authorization_and_is_consumed_once(self):
        self.assertEqual(self.request("/internal/web/bootstrap", method="POST", body={})[0], 401)
        cookie, _ = self.session()
        self.assertNotIn(self.server.token, cookie)
        self.assertEqual(self.request("/v1/config")[0], 401)
        self.assertEqual(self.request("/v1/config", headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("/internal/web/bootstrap", method="POST", body={}, headers={"Cookie": cookie})[0], 401)

    def test_cookie_write_requires_exact_origin_and_csrf_and_does_not_expose_key(self):
        cookie, csrf = self.session()
        data = {"expected_version": 1, "values": {"llm": {"api_key": "synthetic-private-key"}}}
        base = {"Cookie": cookie}
        for extra in ({}, {"Origin": self.server.url}, {"X-DistillAI-CSRF": csrf},
                      {"Origin": "https://example.invalid", "X-DistillAI-CSRF": csrf}):
            self.assertEqual(self.request("/v1/config", method="PUT", body=data, headers={**base, **extra})[0], 403)
        self.assertEqual(self.runtime.config.read()["version"], 1)
        status, _, result = self.request("/v1/config", method="PUT", body=data,
            headers={**base, "Origin": self.server.url, "X-DistillAI-CSRF": csrf})
        self.assertEqual(status, 200)
        self.assertNotIn("synthetic-private-key", json.dumps(result))
        self.assertEqual(result["version"], 2)
        self.assertEqual(self.request("/v1/config", method="PUT", body=data,
            headers={**base, "Origin": self.server.url, "X-DistillAI-CSRF": csrf})[0], 409)

    def test_history_cursor_keeps_order_when_new_tasks_arrive_and_binds_filters(self):
        headers = {"Authorization": "Bearer " + self.server.token}
        tasks = [self.runtime.register("query", {"session_key": "synthetic", "n": n}, "synthetic history") for n in range(5)]
        status, _, first = self.request("/v1/history?kind=query&limit=2", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual([task["id"] for task in first["items"]], [task["id"] for task in reversed(tasks[-2:])])
        self.runtime.register("query", {"session_key": "synthetic", "n": 10}, "arrived during pagination")
        query = urlencode({"kind": "query", "limit": 2, "cursor": first["next_cursor"]})
        status, _, second = self.request("/v1/history?" + query, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual([task["id"] for task in second["items"]], [tasks[2]["id"], tasks[1]["id"]])
        changed = urlencode({"kind": "episode", "cursor": first["next_cursor"]})
        self.assertEqual(self.request("/v1/history?" + changed, headers=headers)[0], 422)
        self.assertEqual(self.request("/v1/history?limit=101", headers=headers)[0], 422)

    def test_queued_user_edits_are_visible_in_the_target_record_history(self):
        identifier = "a" * 32
        task = self.runtime.register("cognition", {"user_correction": {"record_id": identifier}}, "user_correction")
        status, _, result = self.request("/v1/history?record_id=" + identifier,
            headers={"Authorization": "Bearer " + self.server.token})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in result["items"]], [task["id"]])

    def test_related_views_keep_committed_context_versions_and_ignore_incidental_text(self):
        store = self.runtime.store
        identifier, context_id, expansion_id = "a" * 32, "b" * 32, "c" * 32
        for folder in ("knowledge", "contexts", "expansions"):
            (store.home / folder).mkdir()
        atomic_json(store.home / "knowledge" / (identifier + ".json"), {"id": identifier, "name": "Synthetic", "content": {"summary": "source"}})
        target = {"id": identifier, "version": store.put_version((store.home / "knowledge" / (identifier + ".json")).read_bytes())}
        previous = {"id": context_id, "session_key": "synthetic", "record_refs": [target], "subgraph": {"knowledge_refs": [target]},
            "mcp_context": [], "injection_candidates": []}
        version = store.put_version(json.dumps(previous).encode())
        task = self.runtime.register("context", {"episode_refs": []}, "synthetic committed context")
        task.update(status="succeeded", result_version=store.put_version(json.dumps({"context_ref": {"id": context_id, "version": version}}).encode()))
        self.runtime._save(task)
        atomic_json(store.home / "contexts/synthetic.json", {**previous, "record_refs": [], "subgraph": {}})
        atomic_json(store.home / "expansions" / (expansion_id + ".json"), {"id": expansion_id, "input_refs": [target], "question": "check source", "claims": []})
        atomic_json(store.home / "expansions" / ("d" * 32 + ".json"), {"id": "d" * 32, "input_refs": [], "question": identifier})
        headers = {"Authorization": "Bearer " + self.server.token}
        status, _, result = self.request("/v1/related?record_id=" + identifier, headers=headers)
        self.assertEqual(status, 200)
        rows = {(item["record_kind"], item["version"]): item for item in result["items"]}
        self.assertEqual(rows[("context", version)]["record"], previous)
        self.assertEqual([item["id"] for item in result["items"] if item["record_kind"] == "expansion"], [expansion_id])
        self.assertEqual(self.request("/v1/related?record_id=" + "f" * 32, headers=headers)[0], 404)
        self.assertEqual(self.request("/v1/related?record_id=../config", headers=headers)[0], 422)

    def test_record_lists_and_historical_details_do_not_accept_arbitrary_source_paths(self):
        headers = {"Authorization": "Bearer " + self.server.token}
        folder = self.runtime.store.home / "episodes"
        folder.mkdir()
        record = {"id": "e" * 32, "session_key": "synthetic", "state": "closed", "topic": "original synthetic topic", "source_refs": []}
        path = folder / (record["id"] + ".json")
        atomic_json(path, record)
        version = self.runtime.store.put_version(path.read_bytes())
        atomic_json(path, {**record, "topic": "later topic"})
        status, _, result = self.request("/v1/episodes", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(result["items"][0]["topic"], "later topic")
        status, _, result = self.request("/v1/episodes/" + record["id"] + "?version=" + version, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(result["record"]["topic"], "original synthetic topic")
        self.assertEqual(self.request("/v1/episodes/" + "f" * 32, headers=headers)[0], 404)
        self.assertEqual(self.request("/v1/sources?" + urlencode({"ref": json.dumps({"path": "C:/private.txt"})}), headers=headers)[0], 422)

    def test_static_assets_require_session_and_use_fixed_routes_with_no_inline_execution(self):
        self.assertEqual(self.request("/")[0], 401)
        cookie, _ = self.session()
        headers = {"Cookie": cookie}
        for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")):
            status, response_headers, text = self.request(path, headers=headers)
            self.assertEqual(status, 200)
            self.assertIn(content_type, response_headers["Content-Type"])
            self.assertIn("script-src 'self'", response_headers["Content-Security-Policy"])
            self.assertIn("frame-ancestors 'none'", response_headers["Content-Security-Policy"])
            self.assertNotIn(self.server.token, text)
        for path in ("/../config.json", "/%2e%2e/config.json", "/web/../../config.json", "/app.js?path=config.json"):
            self.assertNotEqual(self.request(path, headers=headers)[0], 200)
        self.assertNotEqual(self.request("/", method="POST", body={},
            headers={**headers, "Origin": self.server.url})[0], 200)

    def test_history_artifacts_are_bound_to_the_selected_task_and_keep_original_versions(self):
        headers = {"Authorization": "Bearer " + self.server.token}
        task = self.runtime.register("query", {"query": "original synthetic input"}, "synthetic", prompt="original prompt")
        self.runtime.config.update(1, {"llm": {"model": "new model", "api_key": "synthetic-private-credential"}})
        status, _, data = self.request("/v1/tasks/" + task["id"] + "/artifacts?field=input_version", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(data["version"], task["input_version"])
        self.assertEqual(json.loads(data["text"]), {"query": "original synthetic input"})
        for query, status in (("field=config", 422), ("field=result_version", 404), ("field=prompt_version&field=input_version", 422)):
            self.assertEqual(self.request("/v1/tasks/" + task["id"] + "/artifacts?" + query, headers=headers)[0], status)
        status, _, current = self.request("/v1/tasks/" + task["id"], headers=headers)
        self.assertEqual(current["config"]["version"], 1)
        self.assertNotIn("synthetic-private-credential", json.dumps(current))

    def test_failed_task_retry_requires_csrf_and_preserves_used_budget(self):
        def execute(task, runtime):
            runtime.reserve_generation(task["id"])
            raise ValueError("synthetic execution failed")
        self.runtime.execute = execute
        task = self.runtime.register("query", {}, "synthetic failure")
        self.runtime.dispatch()
        failed = self.runtime.wait(task["id"])
        self.assertEqual(failed["status"], "failed")
        cookie, csrf = self.session()
        path = "/v1/tasks/" + task["id"] + "/retry"
        self.assertEqual(self.request(path, method="POST", body={}, headers={"Cookie": cookie})[0], 403)
        status, _, result = self.request(path, method="POST", body={},
            headers={"Cookie": cookie, "Origin": self.server.url, "X-DistillAI-CSRF": csrf})
        self.assertEqual(status, 202)
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["model_calls"], failed["model_calls"])
        self.assertEqual(result["id"], failed["id"])

    def test_search_environment_credential_is_reported_without_its_value(self):
        self.runtime.search_environment_key = "synthetic-environment-key"
        headers = {"Authorization": "Bearer " + self.server.token}
        status, _, result = self.request("/v1/config", headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(result["search_environment_configured"])
        self.assertNotIn("synthetic-environment-key", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
