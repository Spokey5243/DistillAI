"""Context queries return read versions and keep cancellation ownership per call."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from distillai import context
from distillai.config import Config
from distillai.knowledge import KnowledgeIndex
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json


A = "a" * 32


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic source"}\n', encoding="utf-8")
        self.ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        folder = self.store.home / "knowledge"
        folder.mkdir()
        self.record = {"id": A, "name": "Synthetic concept", "content": {"summary": "authoritative content", "source_refs": [self.ref]}}
        atomic_json(folder / (A + ".json"), self.record)

    def runtime(self, execute=None):
        runtime = Runtime(self.store, Config(self.store), execute or (lambda task, control: {}),
            lambda task, result: context.validate_task(runtime, task, result),
            prepare_result=lambda task, result: context.prepare_result(runtime, task, result),
            after_commit=lambda task: context.after_commit(runtime, task))
        runtime.knowledge_index = KnowledgeIndex(self.store)
        runtime.knowledge_index.rebuild()
        self.addCleanup(runtime.close)
        return runtime

    def test_explicit_id_or_known_name_returns_actual_content_without_a_model_task(self):
        runtime = self.runtime()
        for query in (A, " synthetic CONCEPT "):
            result = context.start_query(runtime, "synthetic", query, uuid.uuid4().hex)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["items"][0]["record"], self.record)
        result = context.start_query(runtime, "synthetic", "f" * 32, uuid.uuid4().hex)
        self.assertEqual(result["result"]["status"], "not_found")
        self.assertEqual(runtime.tasks(), [])

    def test_query_must_read_returned_record_and_preserve_its_frozen_version(self):
        def execute(task, control):
            prepared = context.execution_task(control, task)
            record = prepared["inputs"]["records"][0]
            context.audit_reads(control, task["id"], [{name: record[name] for name in ("id", "version", "record_kind")}])
            atomic_json(self.store.home / "knowledge" / (A + ".json"), {**self.record, "content": {"summary": "later content", "source_refs": [self.ref]}})
            return {"status": "ok", "items": [{"record_kind": "knowledge", "record_ref": {"id": A, "version": record["version"]}}], "source_refs": [self.ref], "reason": "read actual record"}

        runtime = self.runtime(execute)
        started = context.start_query(runtime, "synthetic", "Explain this topic in context", uuid.uuid4().hex)
        runtime.dispatch()
        completed = runtime.wait(started["task_id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        result = json.loads(self.store.read_version(completed["result_version"]))
        self.assertEqual(result["items"][0]["record"]["content"]["summary"], "authoritative content")
        self.assertIsNone(completed["scope"])
        self.assertIsNone(completed["commit_id"])

    def test_unread_record_cannot_be_returned(self):
        def execute(task, control):
            record = context.execution_task(control, task)["inputs"]["records"][0]
            return {"status": "ok", "items": [{"record_kind": "knowledge", "record_ref": {"id": A, "version": record["version"]}}], "source_refs": [self.ref], "reason": "not actually read"}

        runtime = self.runtime(execute)
        started = context.start_query(runtime, "synthetic", "Explain this topic", uuid.uuid4().hex)
        runtime.dispatch()
        self.assertEqual(runtime.wait(started["task_id"])["status"], "failed")

    def test_identical_queries_have_independent_call_ownership_and_early_cancel_is_sticky(self):
        runtime = self.runtime()
        first_id, second_id = uuid.uuid4().hex, uuid.uuid4().hex
        first = context.start_query(runtime, "synthetic", "Explain this topic", first_id)
        same = context.start_query(runtime, "synthetic", "Explain this topic", first_id)
        second = context.start_query(runtime, "synthetic", "Explain this topic", second_id)
        self.assertEqual(first, same)
        self.assertNotEqual(first["task_id"], second["task_id"])
        context.cancel_query(runtime, first_id, "client cancelled")
        self.assertEqual(runtime.task(first["task_id"])["status"], "cancelled")
        self.assertEqual(runtime.task(second["task_id"])["status"], "queued")
        early = uuid.uuid4().hex
        context.cancel_query(runtime, early, "cancelled before registration response")
        result = context.start_query(runtime, "synthetic", "Explain this topic", early)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(runtime.tasks()), 2)

    def test_context_refresh_coalesces_queued_inputs_but_never_changes_running_inputs(self):
        runtime = self.runtime()
        folder = self.store.home / "episodes"
        folder.mkdir()
        ep = {"id": "e" * 32, "state": "open", "session_key": "synthetic", "source_refs": [self.ref]}
        atomic_json(folder / (ep["id"] + ".json"), ep)
        version = self.store.put_version((folder / (ep["id"] + ".json")).read_bytes())
        ref = {"id": ep["id"], "version": version}
        first = context.register_prepare(runtime, "synthetic", ref, 1, "first save")
        second = context.register_prepare(runtime, "synthetic", ref, 2, "new material")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(runtime.task(first["id"])["inputs"]["material_updates"], 2)
        frozen = runtime.task(first["id"])
        frozen.update(status="running", started=True)
        runtime._save(frozen)
        next_task = context.register_prepare(runtime, "synthetic", ref, 3, "material while preparing")
        self.assertNotEqual(next_task["id"], first["id"])
        self.assertEqual(runtime.task(first["id"])["inputs"]["material_updates"], 2)

    def test_selection_filters_changed_duplicate_and_unknown_items_and_compact_restores_saved_text(self):
        runtime = self.runtime()
        version = self.store.put_version((self.store.home / "knowledge" / (A + ".json")).read_bytes())
        record_ref = {"id": A, "version": version}
        candidate = {"id": "c" * 32, "revision": 1, "record_refs": [record_ref], "text": "Use this synthetic connection",
                     "conditions": "when useful", "rationale": "helps this question"}
        folder = self.store.home / "contexts"
        folder.mkdir()
        atomic_json(folder / "synthetic.json", {"id": "d" * 32, "session_key": "synthetic", "injection_candidates": [candidate]})
        started = context.start_selection(runtime, "synthetic", "synthetic question")
        task = runtime.task(started["task_id"])
        selected = context.prepare_result(runtime, task, {"selected_ids": [candidate["id"], "f" * 32], "reason": "useful one"})
        self.assertEqual(selected["selected_ids"], [candidate["id"]])
        duplicate = context.prepare_result(runtime, task, {"selected_ids": [candidate["id"], candidate["id"]], "reason": "invalid duplicate"})
        self.assertEqual(duplicate["selected_ids"], [])
        # Finish the actual no-tool screening through its normal lifecycle.
        runtime.execute = lambda task, control: {"selected_ids": [candidate["id"]], "reason": "useful"}
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        first = context.selection_status(runtime, started["round_key"])
        self.assertEqual(first["selected"][0]["text"], candidate["text"])
        def broken_writer(value):
            raise OSError("synthetic output failure")
        self.assertFalse(context.write_selection(runtime, started["round_key"], broken_writer))
        self.assertNotIn("output_phase", context.selection_status(runtime, started["round_key"]))
        output = []
        self.assertFalse(context.write_selection(runtime, started["round_key"], output.append, compact=True))
        self.assertTrue(context.write_selection(runtime, started["round_key"], output.append))
        written = context.selection_status(runtime, started["round_key"])
        self.assertEqual(written["output_phase"], "additional_context_written")
        self.assertNotIn("platform_received", written)
        first_payload = json.loads(output[-1].split("\n\n", 1)[1])
        self.assertEqual(first_payload["items"], first["selected"])
        atomic_json(self.store.home / "knowledge" / (A + ".json"), {**self.record, "content": {"summary": "changed", "source_refs": [self.ref]}})
        self.assertFalse(context.write_selection(runtime, started["round_key"], output.append))
        for _ in range(2):
            self.assertTrue(context.write_selection(runtime, started["round_key"], output.append, compact=True))
            restored = json.loads(output[-1].split("\n\n", 1)[1])
            self.assertEqual(restored["delivery_type"], "compact_restore")
            self.assertEqual(restored["items"], first_payload["items"])
            self.assertEqual(restored["selection_prompt_version"], first_payload["selection_prompt_version"])
            self.assertEqual(restored["request_version"], first_payload["request_version"])
        self.assertEqual(context.restore_selection(runtime, "synthetic")["selected"], first["selected"])
        self.assertEqual(context.restore_selection(runtime, "synthetic")["selected"], first["selected"])
        self.assertEqual(len(runtime.tasks()), 1)
        self.assertEqual(context.prepare_result(runtime, task, {"selected_ids": [candidate["id"]], "reason": "now stale"})["selected_ids"], [])
        context.start_selection(runtime, "synthetic", "next prompt without candidates")
        self.assertFalse(context.write_selection(runtime, started["round_key"], output.append, compact=True))

    def test_prepare_publishes_stable_candidate_revisions_and_waits_for_three_new_updates(self):
        text = ["Use the existing synthetic connection"]
        def execute(task, control):
            inputs = context.execution_task(control, task)["inputs"]
            previous = inputs["previous_context"]
            candidate_id = previous["injection_candidates"][0]["id"] if previous else context.allocate_candidate(control, task["id"])["id"]
            revision = previous["injection_candidates"][0]["revision"] if previous else 0
            known = next(item for item in inputs["records"] if item["id"] == A)
            ref = {"id": A, "version": known["version"]}
            record = {**inputs["context_template"], "record_refs": [ref],
                "subgraph": {"knowledge_refs": [next(item for item in inputs["name_graph"] if item["id"] == A)], "relations": []},
                "injection_candidates": [{"id": candidate_id, "revision": revision, "record_refs": [ref],
                    "text": text[0], "conditions": "when useful", "rationale": "connects the task"}]}
            atomic_json(Path(task["workspace"]) / "contexts/synthetic.json", record)
            return {"context_ref": {"id": record["id"]}, "reason": "prepared actual records"}

        runtime = self.runtime(execute)
        folder = self.store.home / "episodes"
        folder.mkdir()
        ep = {"id": "e" * 32, "state": "open", "session_key": "synthetic", "source_refs": [self.ref]}
        atomic_json(folder / (ep["id"] + ".json"), ep)
        version = self.store.put_version((folder / (ep["id"] + ".json")).read_bytes())
        ref = {"id": ep["id"], "version": version}
        task = context.register_prepare(runtime, "synthetic", ref, 1, "first")
        runtime.dispatch()
        done = runtime.wait(task["id"])
        self.assertEqual(done["status"], "succeeded", done["error"])
        path = self.store.home / "contexts/synthetic.json"
        first = json.loads(path.read_text(encoding="utf-8"))["injection_candidates"][0]
        self.assertEqual(first["revision"], 1)
        self.assertIsNone(context.register_prepare(runtime, "synthetic", ref, 2, "second"))
        self.assertIsNone(context.register_prepare(runtime, "synthetic", ref, 3, "third"))
        text[0] = "Use the revised synthetic connection"
        task = context.register_prepare(runtime, "synthetic", ref, 4, "fourth")
        runtime.dispatch()
        done = runtime.wait(task["id"])
        self.assertEqual(done["status"], "succeeded", done["error"])
        second = json.loads(path.read_text(encoding="utf-8"))["injection_candidates"][0]
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["revision"], 2)

    def test_reanalysis_requires_fresh_preparation_and_preserves_selected_compact_snapshot(self):
        from distillai.cognition import REANALYSIS
        def execute(task, control):
            if task["kind"] == "screening":
                return {"selected_ids": [task["inputs"]["candidates"][0]["id"]], "reason": "useful existing material"}
            inputs = context.execution_task(control, task)["inputs"]
            previous = inputs["previous_context"]
            old = previous["injection_candidates"][0] if previous else None
            item = next(item for item in inputs["records"] if item["id"] == A)
            ref = {"id": A, "version": item["version"]}
            candidate = {"id": old["id"] if old else context.allocate_candidate(control, task["id"])["id"],
                "revision": old["revision"] if old else 0, "record_refs": [ref], "text": "synthetic prepared material", "conditions": "when useful", "rationale": "direct evidence"}
            record = {**inputs["context_template"], "record_refs": [ref], "injection_candidates": [candidate]}
            atomic_json(Path(task["workspace"]) / "contexts/synthetic.json", record)
            return {"context_ref": {"id": record["id"]}, "reason": "prepare current dependencies"}
        runtime = self.runtime(execute)
        (self.store.home / "episodes").mkdir()
        ep = {"id": "e" * 32, "state": "open", "session_key": "synthetic", "source_refs": [self.ref]}
        path = self.store.home / "episodes" / (ep["id"] + ".json")
        atomic_json(path, ep)
        ep_ref = {"id": ep["id"], "version": self.store.put_version(path.read_bytes())}
        def complete(task):
            runtime.dispatch()
            done = runtime.wait(task["id"])
            self.assertEqual(done["status"], "succeeded", done["error"])
        complete(context.register_prepare(runtime, "synthetic", ep_ref, 1, "initial"))
        selection = context.start_selection(runtime, "synthetic", "initial question")
        complete(runtime.task(selection["task_id"]))
        original = context.selection_status(runtime, selection["round_key"])["selected"]
        waiting = {"entries": [{"record_ref": original[0]["record_refs"][0], "episode_ref": ep_ref, "status": "waiting"}]}
        (self.store.home / "cognition").mkdir()
        atomic_json(self.store.home / REANALYSIS, waiting)
        self.assertEqual(context.restore_selection(runtime, "synthetic")["selected"], original)
        self.assertNotIn("task_id", context.start_selection(runtime, "synthetic", "waiting question"))
        waiting["entries"][0]["status"] = "ready"
        atomic_json(self.store.home / REANALYSIS, waiting)
        self.assertNotIn("task_id", context.start_selection(runtime, "synthetic", "ready but not prepared"))
        complete(context.register_prepare(runtime, "synthetic", ep_ref, 1, "analysis complete", force=True))
        selected = context.start_selection(runtime, "synthetic", "freshly prepared question")
        complete(runtime.task(selected["task_id"]))
        self.assertEqual(context.selection_status(runtime, selected["round_key"])["selected"][0]["revision"], 2)

    def test_candidate_revision_changed_during_selection_drops_only_that_item(self):
        version = self.store.put_version((self.store.home / "knowledge" / (A + ".json")).read_bytes())
        candidates = [{"id": letter * 32, "revision": 1, "record_refs": [{"id": A, "version": version}],
            "text": "existing material " + letter, "conditions": "when useful", "rationale": "direct relevance"} for letter in ("c", "d")]
        (self.store.home / "contexts").mkdir()
        path = self.store.home / "contexts/synthetic.json"
        record = {"id": "e" * 32, "session_key": "synthetic", "injection_candidates": candidates}
        atomic_json(path, record)
        def execute(task, control):
            updated = [{**candidates[0], "revision": 2, "text": "new candidate text"}, candidates[1]]
            atomic_json(path, {**record, "injection_candidates": updated})
            return {"selected_ids": [item["id"] for item in candidates], "reason": "both appeared relevant in the fixed input"}
        runtime = self.runtime(execute)
        started = context.start_selection(runtime, "synthetic", "synthetic question")
        runtime.dispatch()
        completed = runtime.wait(started["task_id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        selected = context.selection_status(runtime, started["round_key"])["selected"]
        self.assertEqual(selected, [candidates[1]])
        atomic_json(path, {**record, "injection_candidates": []})
        self.assertEqual(context.restore_selection(runtime, "synthetic")["selected"], selected)
        self.assertEqual(context.restore_selection(runtime, "synthetic")["selected"], selected)


if __name__ == "__main__":
    unittest.main()
