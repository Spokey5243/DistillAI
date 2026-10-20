"""User evidence retains role, help and identity while content stays unchanged."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from distillai import cognition
from distillai.storage import Store, atomic_json
from distillai.config import Config
from distillai.runtime import Runtime


A, B, E, O, H = (character * 32 for character in ("1", "2", "e", "c", "d"))


class CognitionTests(unittest.TestCase):
    def test_invalid_reanalysis_dependencies_are_not_adopted_or_rewritten(self):
        entry = {"record_kind": "knowledge", "record_ref": {"id": A, "version": "a" * 64},
            "previous_episode_ref": {"id": E, "version": "b" * 64},
            "episode_ref": {"id": E, "version": "c" * 64}, "status": "waiting", "reason": "synthetic revision",
            "revision_source_refs": [self.ref]}
        path = self.store.home / "cognition/reanalysis.json"
        path.parent.mkdir(exist_ok=True)
        for changed in ({"status": "unknown"}, {"status": "ready"}, {"resolved_by": True},
                        {"extra": "ignored"}, {"record_ref": {"id": A, "version": "not-a-version"}}):
            atomic_json(path, {"entries": [{**entry, **changed}]})
            before = path.read_bytes()
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                cognition.reanalysis(self.store, A)
            self.assertEqual(path.read_bytes(), before)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_bytes(b"".join((json.dumps({"role": role, "text": text, "at": "2026-10-15T00:00:00Z"}) + "\n").encode()
                                   for role, text in [("user", "synthetic explanation"), ("assistant", "synthetic help"), ("user", "synthetic explanation")]))
        (self.store.home / "episodes").mkdir()
        atomic_json(self.store.home / "episodes" / (E + ".json"), {"id": E, "source_refs": [{**self.ref, "line_end": 3}], "state": "closed"})
        self.records = {A: {"id": A, "name": "Concept", "content": {"summary": "content", "source_refs": [self.ref]}, "provenance": {"created_from_episode_id": E}}}
        self.baseline = {"knowledge": deepcopy(self.records), "relations": {}, "hypotheses": {}}

    def observation(self, *, source=None, identifier=O):
        return {"id": identifier, "observed_at": "2026-10-15T00:00:00Z", "source": {"episode_id": E, "source_refs": [source or self.ref]},
                "task": "explain a mechanism", "help": {"previously_shown_explanation": True},
                "performance": "user offered an explanation", "scope": "assisted expression only"}

    def judge(self):
        self.records[A]["observations"] = [self.observation()]
        self.records[A]["hypotheses"] = [{"id": H, "claim": "an explanation is available with prior help", "status": "provisional",
            "supporting_observation_ids": [O], "counter_observation_ids": [], "needed_evidence": "independent use in another task"}]
        self.records[A]["cognition"] = {"assessed_at": "2026-10-15T00:01:00Z", "understanding": {"explain": "observed with help"},
                                        "observation_ids": [O], "hypothesis_ids": [H]}

    def test_user_sources_keep_help_and_qualitative_judgments(self):
        self.judge()
        cognition.validate_collection(self.store, self.records, {}, {}, baseline=self.baseline)
        self.assertTrue(self.records[A]["observations"][0]["help"]["previously_shown_explanation"])

    def test_assistant_only_missing_source_or_missing_help_cannot_be_user_evidence(self):
        for mutate in (lambda observation: observation["source"].update(source_refs=[{**self.ref, "line_start": 2, "line_end": 2}]),
                       lambda observation: observation["source"].update(source_refs=[{**self.ref, "line_start": 4, "line_end": 4}]),
                       lambda observation: observation.pop("help"), lambda observation: observation["source"].update(episode_id="f" * 32)):
            record = deepcopy(self.records)
            record[A]["observations"] = [self.observation()]
            mutate(record[A]["observations"][0])
            with self.assertRaises(ValueError):
                cognition.validate_collection(self.store, record, {}, {}, baseline=self.baseline)

    def test_source_identity_uses_physical_user_positions_and_not_text_or_assistant_context(self):
        first = cognition.source_identity(self.store, [self.ref])
        supplemented = cognition.source_identity(self.store, [{**self.ref, "line_end": 2}])
        repeated_text = cognition.source_identity(self.store, [{**self.ref, "line_start": 3, "line_end": 3}])
        self.assertEqual(first, supplemented)
        self.assertNotEqual(first, repeated_text)
        self.records[A]["observations"] = [self.observation(), self.observation(identifier="b" * 32)]
        with self.assertRaises(ValueError):
            cognition.validate_collection(self.store, self.records, {}, {}, baseline=self.baseline)

    def test_cognition_cannot_change_content_or_reference_nonexistent_observations(self):
        self.judge()
        for mutate in (lambda record: record["content"].update(summary="rewritten content"),
                       lambda record: record["provenance"].update(created_from_episode_id="f" * 32),
                       lambda record: record["cognition"].update(observation_ids=["f" * 32]),
                       lambda record: record["hypotheses"][0].update(supporting_observation_ids=["f" * 32]),
                       lambda record: record["cognition"]["understanding"].update(score=.9)):
            records = deepcopy(self.records)
            mutate(records[A])
            with self.assertRaises(ValueError):
                cognition.validate_collection(self.store, records, {}, {}, baseline=self.baseline)

    def test_cross_object_hypothesis_uses_record_and_observation_locators(self):
        self.judge()
        self.records[B] = {"id": B, "name": "Other", "content": {"summary": "other", "source_refs": [self.ref]}}
        self.baseline["knowledge"][B] = deepcopy(self.records[B])
        self.records[B]["observations"] = [self.observation(source={**self.ref, "line_start": 3, "line_end": 3}, identifier="b" * 32)]
        refs = []
        for identifier, record in self.baseline["knowledge"].items():
            data = json.dumps(record).encode()
            refs.append({"id": identifier, "version": self.store.put_version(data)})
        external_id = "f" * 32
        hypotheses = {external_id: {"id": external_id, "claim": "possible common explanation", "status": "open alternative",
            "knowledge_refs": refs, "relation_refs": [], "supporting_observations": [{"record_id": A, "observation_id": O}, {"record_id": B, "observation_id": "b" * 32}],
            "counter_observations": [], "needed_evidence": "another independent context"}}
        self.records[A]["hypothesis_refs"] = [external_id]
        cognition.validate_collection(self.store, self.records, {}, hypotheses, baseline=self.baseline)
        duplicates = deepcopy(hypotheses)
        duplicates[H] = {**deepcopy(hypotheses[external_id]), "id": H}
        with self.assertRaises(ValueError):
            cognition.validate_collection(self.store, self.records, {}, duplicates, baseline=self.baseline)
        hypotheses[external_id]["supporting_observations"][0]["observation_id"] = "0" * 32
        with self.assertRaises(ValueError):
            cognition.validate_collection(self.store, self.records, {}, hypotheses, baseline=self.baseline)

    def test_episode_runtime_reuses_source_bound_observation_ids_and_preserves_content(self):
        folder = self.store.home / "knowledge"
        folder.mkdir()
        atomic_json(folder / (A + ".json"), self.records[A])
        path = self.store.home / "episodes" / (E + ".json")
        episode_ref = {"id": E, "version": self.store.put_version(path.read_bytes())}
        observations = []

        def execute(task, control):
            inputs = cognition.execution_task(control, task)["inputs"]
            identifier = cognition.allocate_id(control, task["id"], "observation", [self.ref])["id"]
            same = cognition.allocate_id(control, task["id"], "observation", [{**self.ref, "line_end": 2}])["id"]
            self.assertEqual(identifier, same)
            other = cognition.allocate_id(control, task["id"], "observation", [{**self.ref, "line_start": 3, "line_end": 3}])["id"]
            self.assertNotEqual(identifier, other)
            observations.append(identifier)
            record = deepcopy(next(item["record"] for item in inputs["records"] if item["id"] == A))
            old_claims = record.get("hypotheses", [])
            hypothesis_id = old_claims[0]["id"] if old_claims else cognition.allocate_id(control, task["id"], "hypothesis")["id"]
            observation = self.observation(identifier=identifier)
            observation["help"]["supplemented"] = len(observations) > 1
            record["observations"] = [observation]
            record["hypotheses"] = [{"id": hypothesis_id, "claim": "assisted expression observed", "status": "provisional",
                                    "supporting_observation_ids": [identifier], "counter_observation_ids": [], "needed_evidence": "independent use"}]
            record["cognition"] = {"assessed_at": inputs["assessment_at"], "understanding": {"explain": "observed with help"},
                                    "observation_ids": [identifier], "hypothesis_ids": [hypothesis_id]}
            atomic_json(Path(task["workspace"]) / "knowledge" / (A + ".json"), record)
            return {"knowledge_refs": [{"id": A}], "relation_refs": [], "hypothesis_refs": [], "reason": "source-bound evidence"}

        runtime = Runtime(self.store, Config(self.store), execute,
            lambda task, result: cognition.validate_task(runtime, task, result),
            prepare_result=lambda task, result: cognition.prepare_result(runtime, task, result),
            after_commit=lambda task: cognition.after_commit(runtime, task))
        self.addCleanup(runtime.close)
        for commit in ("first", "supplement"):
            task = cognition.register_analysis(runtime, [episode_ref], {"knowledge_refs": [], "relation_refs": [], "reason": "empty M04"}, "episode evidence", commit)
            runtime.dispatch()
            completed = runtime.wait(task["id"], timeout=30)
            self.assertEqual(completed["status"], "succeeded", completed["error"])
        record = json.loads((folder / (A + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(len(record["observations"]), 1)
        self.assertEqual(record["content"], self.records[A]["content"])
        self.assertTrue(record["observations"][0]["help"]["supplemented"])


if __name__ == "__main__":
    unittest.main()
