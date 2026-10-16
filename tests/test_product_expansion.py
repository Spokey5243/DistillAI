"""Exploration advances only on committed results with individually read sources."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from distillai import expansion
from distillai.config import Config
from distillai.runtime import Runtime, CancelledError
from distillai.sources import read_source
from distillai.storage import Store, atomic_json, ConflictError


A, B = "a" * 32, "b" * 32


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        dns = patch("distillai.expansion.socket.getaddrinfo", side_effect=lambda host, port: [(2, 1, 6, "", (
            "93.184.216.34" if host == "example.org" else "127.0.0.1", port))])
        dns.start()
        self.addCleanup(dns.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "data")
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic explanation"}\n', encoding="utf-8")
        self.source = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        (self.store.home / "knowledge").mkdir()
        for identifier in (A, B):
            atomic_json(self.store.home / "knowledge" / (identifier + ".json"),
                {"id": identifier, "name": identifier[:1], "content": {"summary": "synthetic", "source_refs": [self.source]}})
        self.runtime = Runtime(self.store, Config(self.store), self.execute,
            lambda task, result: expansion.validate_task(self.runtime, task, result),
            prepare_result=lambda task, result: expansion.prepare_result(self.runtime, task, result),
            after_commit=lambda task: expansion.after_commit(self.runtime, task))
        self.addCleanup(self.runtime.close)
        self.runtime.config.update(1, {"llm": {"base_url": "http://127.0.0.1:1/v1", "model": "synthetic"}})
        self.runtime.search_environment_key = ""
        self.runtime.expansion_ready = True
        self.action = None
        self.runtime.web_request = lambda endpoint, payload, key: (
            {"success": True, "data": {"web": [{"url": "https://example.org/source", "title": "Synthetic", "description": "search summary"}]}}
            if endpoint == "search" else [{"url": payload["urls"][0], "title": "Synthetic", "content": "Actual synthetic source excerpt"}])

    def execute(self, task, runtime):
        inputs = expansion.execution_task(runtime, task)["inputs"]
        if self.action:
            return self.action(task, inputs)
        return {"expansion_refs": [], "reason": "no worthwhile new result"}

    def run_task(self, task):
        self.runtime.dispatch()
        done = self.runtime.wait(task["id"])
        self.assertEqual(done["status"], "succeeded", done["error"])
        return done

    def test_period_batch_and_progress_survive_config_changes(self):
        self.assertIsNone(expansion.tick(self.runtime, now=0))
        self.assertIsNone(expansion.tick(self.runtime, now=3599))
        first = expansion.tick(self.runtime, now=3600)
        self.assertEqual([ref["id"] for ref in first["inputs"]["knowledge_refs"]], [A, B])
        self.assertEqual(expansion.tick(self.runtime, now=7200)["id"], first["id"])
        self.run_task(first)
        before = expansion.status(self.runtime)["completed"]
        self.runtime.config.update(2, {"expansion": {"interval_seconds": 10, "batch_size": 1}})
        self.assertIsNone(expansion.tick(self.runtime, now=7210))
        self.assertEqual(expansion.status(self.runtime)["completed"], before)
        record = json.loads((self.store.home / "knowledge" / (A + ".json")).read_text())
        record["content"]["summary"] = "new basis"
        atomic_json(self.store.home / "knowledge" / (A + ".json"), record)
        task = expansion.tick(self.runtime, now=7220)
        self.assertEqual([ref["id"] for ref in task["inputs"]["knowledge_refs"]], [A])
        self.assertEqual(expansion.status(self.runtime)["completed"], before)

    def test_unready_search_does_not_consume_period_or_coverage(self):
        self.runtime.expansion_ready = False
        self.assertIsNone(expansion.tick(self.runtime, now=9999))
        state = expansion.status(self.runtime)
        self.assertEqual(state["unavailable_reason"], "g3_validation_pending")
        self.assertIsNone(state["last_scheduled_at"])
        self.assertEqual(state["completed"], {})
        self.assertEqual(self.runtime.tasks(), [])

    def test_batch_limit_leaves_older_uncovered_objects_for_the_next_batch(self):
        for number in range(11):
            identifier = f"{number:032x}"
            atomic_json(self.store.home / "knowledge" / (identifier + ".json"),
                {"id": identifier, "name": "extra " + str(number), "content": {"summary": "synthetic", "source_refs": [self.source]}})
        expansion.tick(self.runtime, now=0)
        first = expansion.tick(self.runtime, now=3600)
        self.assertEqual(len(first["inputs"]["knowledge_refs"]), 10)
        first_ids = {ref["id"] for ref in first["inputs"]["knowledge_refs"]}
        self.run_task(first)
        second = expansion.tick(self.runtime, now=7200)
        self.assertEqual(len(second["inputs"]["knowledge_refs"]), 3)
        self.assertFalse(first_ids & {ref["id"] for ref in second["inputs"]["knowledge_refs"]})
        restored = Runtime(self.store, self.runtime.config, self.execute, lambda task, result: None)
        try:
            restored.expansion_ready = True
            self.assertEqual(expansion.tick(restored, now=10800)["id"], second["id"])
            self.assertEqual(len(expansion.status(restored)["completed"]), 10)
        finally:
            restored.close()

    def test_rate_limit_is_an_error_not_an_empty_search_and_credentials_use_task_version(self):
        self.runtime.config.update(2, {"search": {"api_key": "synthetic-frozen-key"}})
        expansion.tick(self.runtime, now=0)
        task = expansion.tick(self.runtime, now=3600)
        self.runtime.config.update(3, {"search": {"api_key": "synthetic-new-key"}})
        def action(task, inputs):
            def request(endpoint, payload, key):
                self.assertEqual(key, "synthetic-frozen-key")
                raise HTTPError("https://api.tavily.com/search", 429, "synthetic-frozen-key", {}, None)
            self.runtime.web_request = request
            result = expansion.web_tool(self.runtime, task["id"], "web_search", {"query": "synthetic public claim"})
            self.assertEqual(result["error"]["code"], "quota_or_rate_limit")
            self.assertNotIn("results", result)
            self.assertNotIn("synthetic-frozen-key", str(result))
            self.assertEqual(self.runtime.task(task["id"])["model_calls"], 0)
            return {"expansion_refs": [], "reason": "supplier unavailable is not a successful empty exploration"}
        self.action = action
        self.runtime.dispatch()
        done = self.runtime.wait(task["id"])
        self.assertEqual(done["status"], "failed")
        self.assertEqual(expansion.status(self.runtime)["completed"], {})
        self.assertNotIn("synthetic-frozen-key", str(done))

    def test_changed_seed_cancels_queued_exploration_before_execution(self):
        expansion.tick(self.runtime, now=0)
        task = expansion.tick(self.runtime, now=3600)
        record = json.loads((self.store.home / "knowledge" / (A + ".json")).read_text())
        record["content"]["summary"] = "updated while queued"
        atomic_json(self.store.home / "knowledge" / (A + ".json"), record)
        self.runtime.dispatch()
        done = self.runtime.wait(task["id"])
        self.assertEqual(done["status"], "cancelled")
        self.assertEqual(done["model_calls"], 0)
        self.assertEqual(expansion.status(self.runtime)["completed"], {})
        self.assertIsNone(expansion.tick(self.runtime, now=7200))
        fresh = expansion.tick(self.runtime, now=10800)
        self.assertNotEqual(fresh["id"], task["id"])
        self.assertNotEqual(fresh["inputs"]["knowledge_refs"], task["inputs"]["knowledge_refs"])

    def test_explicit_new_request_allows_reexploration_and_duplicate_request_reuses_task(self):
        expansion.tick(self.runtime, now=0)
        self.run_task(expansion.tick(self.runtime, now=3600))
        completed = expansion.status(self.runtime)["completed"]
        ref = {"id": A, "version": self.store.put_version((self.store.home / "knowledge" / (A + ".json")).read_bytes())}
        request = {"client_request_id": "synthetic-request", "knowledge_refs": [ref],
                   "question": "A different explicitly requested question", "reason": "user requested another exploration"}
        first = expansion.register_request(self.runtime, request)
        self.assertEqual(expansion.register_request(self.runtime, request)["id"], first["id"])
        with self.assertRaises(ConflictError):
            expansion.register_request(self.runtime, {**request, "question": "different payload for the same request ID"})
        self.run_task(first)
        self.assertEqual(expansion.status(self.runtime)["completed"], completed)
        self.assertEqual(first["inputs"]["user_request_ref"]["source_kind"], "user_submission")
        self.assertNotEqual(expansion.register_request(self.runtime, {**request, "client_request_id": "second-request"})["id"], first["id"])

    def test_repeated_changes_to_early_ids_do_not_starve_older_uncovered_objects(self):
        self.runtime.config.update(2, {"expansion": {"batch_size": 1}})
        expansion.tick(self.runtime, now=0)
        first = expansion.tick(self.runtime, now=3600)
        self.assertEqual(first["inputs"]["knowledge_refs"][0]["id"], A)
        self.run_task(first)
        record = json.loads((self.store.home / "knowledge" / (A + ".json")).read_text())
        record["content"]["summary"] = "frequently changing earlier ID"
        atomic_json(self.store.home / "knowledge" / (A + ".json"), record)
        self.assertEqual(expansion.tick(self.runtime, now=7200)["inputs"]["knowledge_refs"][0]["id"], B)

    def test_failed_task_keeps_position_and_is_not_repeated_automatically(self):
        expansion.tick(self.runtime, now=0)
        first = expansion.tick(self.runtime, now=3600)
        self.action = lambda task, inputs: {"wrong": "output"}
        self.runtime.dispatch()
        self.assertEqual(self.runtime.wait(first["id"])["status"], "failed")
        self.assertEqual(expansion.status(self.runtime)["completed"], {})
        self.assertEqual(expansion.tick(self.runtime, now=7200)["id"], first["id"])
        self.assertEqual(len(self.runtime.tasks()), 1)

    def test_fetch_preserves_actual_source_but_search_snippet_cannot_support_claim(self):
        def action(task, inputs):
            search = expansion.web_tool(self.runtime, task["id"], "web_search", {"query": "synthetic claim"})
            self.assertNotIn("source_ref", str(search))
            fetched = expansion.web_tool(self.runtime, task["id"], "fetch_page", {"url": "https://example.org/source"})
            source = fetched["source_ref"]
            self.assertEqual(read_source(self.store.home, source)["text"], "Actual synthetic source excerpt")
            record = {**inputs["expansion_template"], "question": "Does e connect a and b?", "reason": "potential transfer",
                "claims": [{"statement": "e-a", "status": "supported", "source_refs": [source], "verification": "excerpt supports only e-a"}],
                "proposed_connections": [{"source": {"candidate": "e"}, "target": inputs["knowledge_refs"][1],
                    "statement": "e-b", "status": "unverified", "source_refs": [], "verification": "no evidence read for b"}],
                "open_questions": [{"statement": "e-b remains open", "source_refs": []}]}
            atomic_json(Path(task["workspace"]) / "expansions" / (record["id"] + ".json"), record)
            return {"expansion_refs": [{"id": record["id"]}], "reason": "partial evidence retained"}
        self.action = action
        expansion.tick(self.runtime, now=0)
        done = self.run_task(expansion.tick(self.runtime, now=3600))
        result = json.loads(self.store.read_version(done["result_version"]))
        saved = json.loads(self.store.read_version(result["expansion_refs"][0]["version"]))
        self.assertEqual(saved["proposed_connections"][0]["status"], "unverified")
        following = [task for task in self.runtime.tasks() if task["kind"] == "knowledge"]
        self.assertEqual(len(following), 1)
        self.assertEqual(following[0]["inputs"]["expansion_refs"], result["expansion_refs"])
        self.assertFalse(any(task["kind"] == "cognition" for task in self.runtime.tasks()))

    def test_unread_source_or_claim_without_evidence_cannot_be_published(self):
        def action(task, inputs):
            record = {**inputs["expansion_template"], "claims": [{"statement": "invented", "status": "supported", "source_refs": [], "verification": "search title only"}]}
            atomic_json(Path(task["workspace"]) / "expansions" / (record["id"] + ".json"), record)
            return {"expansion_refs": [{"id": record["id"]}], "reason": "invalid"}
        self.action = action
        expansion.tick(self.runtime, now=0)
        task = expansion.tick(self.runtime, now=3600)
        self.runtime.dispatch()
        self.assertEqual(self.runtime.wait(task["id"])["status"], "failed")
        self.assertFalse(list((self.store.home / "expansions").glob("*.json")))
        self.assertEqual(expansion.status(self.runtime)["completed"], {})

    def test_web_tool_forbids_other_tasks_bad_urls_and_late_publication_after_cancel(self):
        other = self.runtime.register("query", {}, "synthetic")
        with self.assertRaises((ValueError, CancelledError)):
            expansion.web_tool(self.runtime, other["id"], "web_search", {"query": "x"})
        def action(task, inputs):
            for url in ("file:///secret", "http://localhost/admin", "http://127.0.0.1/", "https://user:pass@example.org"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    expansion.web_tool(self.runtime, task["id"], "fetch_page", {"url": url})
            def interrupted(endpoint, payload, key):
                self.runtime.cancel(task["id"], "synthetic cancelled network")
                return [{"url": payload["urls"][0], "title": "x", "content": "must not persist"}]
            self.runtime.web_request = interrupted
            with self.assertRaises(CancelledError):
                expansion.web_tool(self.runtime, task["id"], "fetch_page", {"url": "https://example.org/source"})
            self.assertFalse(list((self.store.home / "external-sources").glob("*.json")))
            return {"expansion_refs": [], "reason": "cancelled"}
        self.runtime.cancel(other["id"], "test setup")
        self.action = action
        expansion.tick(self.runtime, now=0)
        task = expansion.tick(self.runtime, now=3600)
        self.runtime.dispatch()
        self.assertEqual(self.runtime.wait(task["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
