"""Knowledge maintenance cannot invent sources or overwrite user-model fields."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from distillai.knowledge import validate_collection
from distillai.storage import Store
from distillai.storage import atomic_json
from distillai.storage import ConflictError
from distillai.config import Config
from distillai.runtime import Runtime
from distillai import knowledge


A, B, R = (str(i) * 32 for i in range(1, 4))


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic explanation"}\n', encoding="utf-8")
        self.ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        self.records = {A: {"id": A, "name": "Reference", "content": {"summary": "synthetic", "source_refs": [self.ref]},
                            "observations": [], "cognition": {"understanding": "unknown"}, "provenance": {"cognition_updated_at": "synthetic"}},
                        B: {"id": B, "name": "Target", "aliases": ["Reference"], "content": {"summary": "target", "source_refs": [self.ref]}}}
        self.relations = {R: {"id": R, "name": "Synthetic relationship", "source_knowledge_id": A, "target_knowledge_id": B,
                              "kind": "user_association", "relation_type": "not a fixed enum", "direction_semantics": "reference to target",
                              "content": {"statement": "unverified user analogy", "source_refs": [self.ref]}, "assessment": {"status": "unverified"}}}

    def test_same_batch_endpoints_aliases_and_unverified_associations_are_valid(self):
        validate_collection(self.store, self.records, self.relations)
        self.records[A]["relations"] = [R]
        validate_collection(self.store, self.records, self.relations)

    def test_bad_ids_names_endpoints_and_sources_are_rejected(self):
        for mutate in (lambda k, r: k[A].update(id=B), lambda k, r: k[B].update(name=" reference "),
                       lambda k, r: r[R].update(target_knowledge_id="f" * 32), lambda k, r: r[R].update(relation_type=""),
                       lambda k, r: k[A]["content"].update(source_refs=[{**self.ref, "line_end": 2}]),
                       lambda k, r: k[A].update(relations=["f" * 32])):
            records, relations = deepcopy(self.records), deepcopy(self.relations)
            mutate(records, relations)
            with self.assertRaises(ValueError):
                validate_collection(self.store, records, relations)

    def test_content_changes_preserve_user_model_and_its_provenance(self):
        baseline = {"knowledge": deepcopy(self.records), "relations": deepcopy(self.relations)}
        self.records[A]["content"]["summary"] = "refined content"
        validate_collection(self.store, self.records, self.relations, baseline=baseline)
        for field, value in (("observations", [{"performance": "invented"}]), ("cognition", {"understanding": "mastered"}),
                             ("hypotheses", [{"claim": "invented"}]), ("provenance", {"cognition_updated_at": "changed"})):
            records = deepcopy(self.records)
            records[A][field] = value
            with self.assertRaises(ValueError):
                validate_collection(self.store, records, self.relations, baseline=baseline)

    def edit_runtime(self, execute):
        for directory, records in (("knowledge", self.records), ("relations", self.relations)):
            folder = self.store.home / directory
            folder.mkdir(exist_ok=True)
            for identifier, record in records.items():
                atomic_json(folder / (identifier + ".json"), record)
        runtime = Runtime(self.store, Config(self.store), execute,
            lambda task, result: knowledge.validate_task(runtime, task, result),
            prepare_result=lambda task, result: knowledge.prepare_result(runtime, task, result),
            after_commit=lambda task: knowledge.after_commit(runtime, task))
        self.addCleanup(runtime.close)
        version = self.store.put_version((self.store.home / "knowledge" / (A + ".json")).read_bytes())
        return runtime, version

    def test_user_edit_keeps_unspecified_fields_and_submission_history_without_inventing_user_ability(self):
        def execute(task, control):
            inputs = knowledge.execution_task(control, task)["inputs"]
            self.assertEqual(inputs["user_edit"]["changes"], {"content": {"summary": "explicit user correction"}})
            old = deepcopy(self.records[A])
            old["content"]["summary"] = "explicit user correction"
            atomic_json(Path(task["workspace"]) / "knowledge" / (A + ".json"), old)
            return {"knowledge_refs": [{"id": A}], "relation_refs": [], "reason": "applied specified field"}
        runtime, version = self.edit_runtime(execute)
        request = {"record_kind": "knowledge", "record_id": A, "expected_version": version,
                   "changes": {"content": {"summary": "explicit user correction"}}, "reason": "correct this statement"}
        first = knowledge.register_user_edit(runtime, request)
        self.assertEqual(knowledge.register_user_edit(runtime, request)["id"], first["id"])
        runtime.dispatch()
        done = runtime.wait(first["id"])
        self.assertEqual(done["status"], "succeeded", done["error"])
        detail = runtime.knowledge_index.detail("knowledge", A)["record"]
        self.assertEqual(detail["cognition"], self.records[A]["cognition"])
        self.assertEqual(detail["name"], self.records[A]["name"])
        self.assertEqual(detail["content"]["source_refs"][0], self.ref)
        self.assertEqual(detail["content"]["source_refs"][-1]["source_kind"], "user_submission")
        self.assertEqual(detail["changes"][-1]["reason"], request["reason"])
        self.assertEqual(json.loads(self.store.read_version(version))["content"]["summary"], "synthetic")
        self.assertFalse(any(task["kind"] == "cognition" for task in runtime.tasks()))

    def test_failed_index_rebuild_keeps_committed_details_and_retry_does_not_rerun_model(self):
        executions = []
        def execute(task, control):
            executions.append(task["id"])
            knowledge.execution_task(control, task)
            record = deepcopy(self.records[A])
            record["content"]["summary"] = "committed despite index failure"
            atomic_json(Path(task["workspace"]) / "knowledge" / (A + ".json"), record)
            return {"knowledge_refs": [{"id": A}], "relation_refs": [], "reason": "explicit content edit"}
        runtime, version = self.edit_runtime(execute)
        task = knowledge.register_user_edit(runtime, {"record_kind": "knowledge", "record_id": A,
            "expected_version": version, "changes": {"content": {"summary": "committed despite index failure"}}, "reason": "synthetic correction"})
        with patch.object(knowledge.KnowledgeIndex, "rebuild", side_effect=ValueError("synthetic index failure")):
            runtime.dispatch()
            pending = runtime.wait(task["id"])
        self.assertEqual(pending["status"], "validating")
        self.assertEqual(runtime.store.read_commit(pending["commit_id"])["status"], "committed")
        saved = runtime.knowledge_index.detail("knowledge", A)
        self.assertEqual(saved["record"]["content"]["summary"], "committed despite index failure")
        runtime.finish_post_commits()
        self.assertEqual(runtime.task(task["id"])["status"], "succeeded")
        self.assertEqual(runtime.knowledge_index.detail("knowledge", A)["version"], saved["version"])
        self.assertEqual(executions, [task["id"]])
        self.assertEqual(len(runtime.tasks()), 1)

    def test_stale_user_edit_and_readonly_fields_are_rejected_before_publication(self):
        called = []
        runtime, version = self.edit_runtime(lambda task, control: called.append(task))
        request = {"record_kind": "knowledge", "record_id": A, "expected_version": version,
                   "changes": {"name": "New name"}, "reason": "synthetic edit"}
        for change in ({"id": "f" * 32}, {"cognition": {}}, {"content": {"source_refs": []}}):
            with self.assertRaises(ValueError):
                knowledge.register_user_edit(runtime, {**request, "changes": change})
        queued = knowledge.register_user_edit(runtime, request)
        atomic_json(self.store.home / "knowledge" / (A + ".json"), {**self.records[A], "name": "Other edit"})
        with self.assertRaises(ConflictError):
            knowledge.register_user_edit(runtime, {**request, "reason": "another request"})
        runtime.dispatch()
        self.assertEqual(runtime.task(queued["id"])["status"], "cancelled")
        self.assertEqual(called, [])

    def test_edit_of_already_equal_fields_can_finish_without_creating_a_business_revision(self):
        def execute(task, control):
            knowledge.execution_task(control, task)
            return {"knowledge_refs": [], "relation_refs": [], "reason": "requested value already present"}
        runtime, version = self.edit_runtime(execute)
        task = knowledge.register_user_edit(runtime, {"record_kind": "knowledge", "record_id": A,
            "expected_version": version, "changes": {"name": self.records[A]["name"]}, "reason": "confirm this name"})
        runtime.dispatch()
        done = runtime.wait(task["id"])
        self.assertEqual(done["status"], "succeeded", done["error"])
        self.assertEqual(runtime.knowledge_index.detail("knowledge", A)["version"], version)

    def test_episode_analysis_can_commit_empty_results_and_still_register_cognition(self):
        directory = self.store.home / "episodes"
        directory.mkdir()
        identifier = "e" * 32
        path = directory / (identifier + ".json")
        atomic_json(path, {"id": identifier, "connector": "codex", "session_key": "synthetic", "state": "closed", "source_refs": [self.ref]})
        ref = {"id": identifier, "version": self.store.put_version(path.read_bytes())}

        def execute(task, control):
            prepared = knowledge.execution_task(control, task)
            self.assertEqual(prepared["inputs"]["episode_refs"], [ref])
            self.assertEqual(prepared["inputs"]["sources"][0]["rows"][0]["role"], "user")
            return {"knowledge_refs": [], "relation_refs": [], "reason": "no durable content"}

        runtime = Runtime(self.store, Config(self.store), execute,
            lambda task, result: knowledge.validate_task(runtime, task, result),
            prepare_result=lambda task, result: knowledge.prepare_result(runtime, task, result),
            after_commit=lambda task: knowledge.after_commit(runtime, task))
        self.addCleanup(runtime.close)
        task = knowledge.register_episode_analysis(runtime, [ref], "closed episode", "synthetic-commit")
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        dependents = [t for t in runtime.tasks() if t["kind"] == "cognition"]
        self.assertEqual(len(dependents), 1)
        self.assertEqual(dependents[0]["inputs"]["episode_refs"], [ref])
        self.assertEqual(dependents[0]["inputs"]["knowledge_result"]["knowledge_refs"], [])
        knowledge.after_commit(runtime, completed)
        self.assertEqual(len([t for t in runtime.tasks() if t["kind"] == "cognition"]), 1)

    def test_allocated_records_publish_together_and_index_failure_retries_without_model(self):
        directory = self.store.home / "episodes"
        directory.mkdir()
        episode_id = "e" * 32
        path = directory / (episode_id + ".json")
        atomic_json(path, {"id": episode_id, "connector": "codex", "session_key": "synthetic", "state": "closed", "source_refs": [self.ref]})
        ref = {"id": episode_id, "version": self.store.put_version(path.read_bytes())}
        calls = []

        def execute(task, control):
            knowledge.execution_task(control, task)
            calls.append(task["id"])
            first = knowledge.allocate_id(control, task["id"], "knowledge")["id"]
            second = knowledge.allocate_id(control, task["id"], "knowledge")["id"]
            link = knowledge.allocate_id(control, task["id"], "relation")["id"]
            root = Path(task["workspace"])
            (root / "knowledge").mkdir(exist_ok=True)
            (root / "relations").mkdir(exist_ok=True)
            atomic_json(root / "knowledge" / (first + ".json"), {"id": first, "name": "Reference", "content": {"summary": "source concept", "source_refs": [self.ref]}, "relations": [link]})
            atomic_json(root / "knowledge" / (second + ".json"), {"id": second, "name": "Target", "content": {"summary": "target concept", "source_refs": [self.ref]}})
            atomic_json(root / "relations" / (link + ".json"), {"id": link, "name": "Unverified analogy", "source_knowledge_id": first, "target_knowledge_id": second,
                "kind": "user_association", "relation_type": "analogy", "direction_semantics": "reference to target", "symmetric": True,
                "content": {"statement": "a user-proposed connection", "source_refs": [self.ref]}, "assessment": {"status": "unverified"}})
            return {"knowledge_refs": [{"id": first}, {"id": second}], "relation_refs": [{"id": link}], "reason": "synthetic records"}

        failed = [True]

        def after(task):
            if failed[0]:
                raise OSError("synthetic index build failure")
            knowledge.after_commit(runtime, task)

        runtime = Runtime(self.store, Config(self.store), execute,
            lambda task, result: knowledge.validate_task(runtime, task, result),
            prepare_result=lambda task, result: knowledge.prepare_result(runtime, task, result), after_commit=after)
        self.addCleanup(runtime.close)
        task = knowledge.register_episode_analysis(runtime, [ref], "closed episode", "synthetic-commit")
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "validating")
        self.assertEqual(self.store.read_commit(completed["commit_id"])["status"], "committed")
        identifier = next(iter(completed["allocated_record_ids"]))
        self.assertEqual(knowledge.KnowledgeIndex(self.store).detail("knowledge", identifier)["record"]["name"], "Reference")
        runtime.recover_tasks()
        self.assertEqual(runtime.task(task["id"])["status"], "validating")
        failed[0] = False
        runtime.finish_post_commits()
        self.assertEqual(runtime.task(task["id"])["status"], "succeeded")
        self.assertEqual(calls, [task["id"]])
        self.assertEqual(len(runtime.knowledge_index.neighbors(identifier)["relations"]), 1)


if __name__ == "__main__":
    unittest.main()
