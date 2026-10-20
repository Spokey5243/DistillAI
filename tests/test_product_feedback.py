"""Feedback preserves request and original user-source identities."""
import json
from pathlib import Path
import tempfile
import unittest

from distillai import context
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.runtime = Runtime(self.store, Config(self.store), lambda task, runtime: {}, lambda task, result: None)
        self.addCleanup(self.runtime.close)
        self.queue = self.store.home / "codex/queue/synthetic.jsonl"
        self.queue.parent.mkdir(parents=True)
        self.request = {"client_request_id": "synthetic-feedback-1", "session_key": "synthetic",
                        "performance": "I used the synthetic rule", "task": "synthetic task", "help": "no assistant help",
                        "knowledge_refs": [], "relation_refs": [], "source_refs": []}

    def rows(self, roles):
        self.queue.write_text("".join(json.dumps({"role": role, "text": self.request["performance"]}) + "\n" for role in roles), encoding="utf-8")

    def episode(self, end):
        folder = self.store.home / "episodes"
        folder.mkdir(exist_ok=True)
        atomic_json(folder / ("e" * 32 + ".json"), {"id": "e" * 32, "connector": "codex", "session_key": "synthetic", "state": "open",
            "source_refs": [{"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": end}]})

    def test_invalid_boundary_is_not_extended_or_used_to_associate_feedback(self):
        context.record_request(self.runtime, "synthetic", self.request["performance"])
        first = context.submit_feedback(self.runtime, self.request)
        self.rows(["user"])
        self.episode(1)
        boundary_path = self.store.home / "events/requests/synthetic.json"
        original = json.loads(boundary_path.read_bytes())
        atomic_json(boundary_path, [{**original[0], "floor": True}])
        before = boundary_path.read_bytes()
        with self.assertRaises(ValueError):
            context.record_request(self.runtime, "synthetic", "next synthetic request")
        context.reconcile_feedback(self.runtime)
        self.assertEqual(boundary_path.read_bytes(), before)
        self.assertEqual(context.feedback_status(self.runtime, first["feedback_id"])["stage"], "awaiting_source")
        self.assertEqual(self.runtime.tasks(), [])

    def test_feedback_with_unknown_fields_is_not_registered_or_rewritten(self):
        context.record_request(self.runtime, "synthetic", self.request["performance"])
        first = context.submit_feedback(self.runtime, self.request)
        self.rows(["user"])
        self.episode(1)
        path = self.store.home / "events/feedback" / (first["feedback_id"] + ".json")
        original = json.loads(path.read_bytes())
        atomic_json(path, {**original, "extra": "ignored"})
        before = path.read_bytes()
        context.reconcile_feedback(self.runtime)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.runtime.tasks(), [])

    def test_feedback_cannot_report_another_requests_task(self):
        self.rows(["user"])
        self.episode(1)
        request = {**self.request, "source_refs": [{"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}]}
        first = context.submit_feedback(self.runtime, request)
        second = context.submit_feedback(self.runtime, {**request, "client_request_id": "another-feedback"})
        path = self.store.home / "events/feedback" / (first["feedback_id"] + ".json")
        original = json.loads(path.read_bytes())
        atomic_json(path, {**original, "task_id": second["task_id"]})
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            context.feedback_status(self.runtime, first["feedback_id"])
        context.reconcile_feedback(self.runtime)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.runtime.tasks()), 2)
        atomic_json(path, original)
        task = self.runtime.task(first["task_id"])
        task["inputs"]["feedback"] = None
        self.runtime._save(task)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            context.feedback_status(self.runtime, first["feedback_id"])
        context.reconcile_feedback(self.runtime)
        self.assertEqual(path.read_bytes(), before)

    def test_before_capture_is_pending_then_only_unique_new_user_source_is_associated(self):
        self.rows(["user"])
        context.record_request(self.runtime, "synthetic", self.request["performance"])
        first = context.submit_feedback(self.runtime, self.request)
        self.assertEqual(first["stage"], "awaiting_source")
        self.assertEqual(context.submit_feedback(self.runtime, self.request), first)
        self.rows(["user", "assistant", "user"])
        self.episode(3)
        context.reconcile_feedback(self.runtime)
        saved = context.feedback_status(self.runtime, first["feedback_id"])
        self.assertEqual(saved["stage"], "registered")
        task = self.runtime.task(saved["task_id"])
        self.assertEqual(task["inputs"]["feedback"]["source_refs"][0]["line_start"], 3)
        self.assertEqual(len(self.runtime.tasks()), 1)
        context.reconcile_feedback(self.runtime)
        self.assertEqual(len(self.runtime.tasks()), 1)

    def test_equal_text_at_two_positions_stays_pending_and_changed_retry_is_rejected(self):
        context.record_request(self.runtime, "synthetic", self.request["performance"])
        first = context.submit_feedback(self.runtime, self.request)
        self.rows(["user", "user"])
        self.episode(2)
        context.reconcile_feedback(self.runtime)
        self.assertEqual(context.feedback_status(self.runtime, first["feedback_id"])["stage"], "awaiting_source")
        self.assertEqual(self.runtime.tasks(), [])
        with self.assertRaises(ValueError):
            context.submit_feedback(self.runtime, {**self.request, "performance": "different request"})

    def test_explicit_assistant_source_is_not_a_user_performance(self):
        self.rows(["assistant"])
        ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        with self.assertRaises(ValueError):
            context.submit_feedback(self.runtime, {**self.request, "source_refs": [ref]})


if __name__ == "__main__":
    unittest.main()
