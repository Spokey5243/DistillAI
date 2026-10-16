"""Ownership revisions preserve history and invalidate only direct user evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from distillai import episode, cognition, knowledge, context
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json, ConflictError


E, F, K, U, O = (char * 32 for char in "ef12a")


def ref(start, end=None):
    return {"connector": "codex", "session_key": "synthetic", "line_start": start, "line_end": end or start}


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(temporary.name)
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text(''.join(json.dumps({"role": role, "text": text}) + '\n' for role, text in
            [("user", "first"), ("assistant", "reply"), ("user", "second"), ("assistant", "reply")]), encoding="utf-8")
        for directory in ("episodes", "buffers", "knowledge"):
            (self.store.home / directory).mkdir()
        self.episodes = {}
        for identifier, sources in ((E, [ref(1, 2)]), (F, [ref(3, 4)])):
            record = {"id": identifier, "connector": "codex", "session_key": "synthetic", "topic": identifier,
                "goal": "fixed goal", "state": "closed", "source_refs": sources,
                "boundary_basis": {"reason": "synthetic grouping", "source_refs": sources, "evaluation_versions": []},
                "summary": "synthetic summary", "close_reason": "synthetic close"}
            atomic_json(self.store.home / "episodes" / (identifier + ".json"), record)
            self.episodes[identifier] = record
        atomic_json(episode.state_path(self.store.home, "synthetic"), {"connector": "codex", "session_key": "synthetic",
            "active_episode_id": None, "buffer": [], "processed_line": 4, "material_updates": 2})
        observed = {"id": K, "name": "Affected", "content": {"summary": "saved content", "source_refs": [ref(1)]},
            "observations": [{"id": O, "observed_at": None, "source": {"episode_id": E, "source_refs": [ref(1)]},
                "task": "explain", "help": "unknown", "performance": "first"}],
            "cognition": {"assessed_at": "2026-10-15T00:00:00Z", "observation_ids": [O], "summary": "provisional"}}
        unrelated = {"id": U, "name": "Content only", "content": {"summary": "same source, no user judgment", "source_refs": [ref(1)]}}
        for record in (observed, unrelated):
            atomic_json(self.store.home / "knowledge" / (record["id"] + ".json"), record)
        self.original = (self.store.home / "knowledge" / (K + ".json")).read_bytes()
        self.request = {"session_key": "synthetic", "episode_refs": [{"id": identifier, "version": self.store.put_version(
            (self.store.home / "episodes" / (identifier + ".json")).read_bytes())} for identifier in (E, F)],
            "assignments": [{"episode_id": E, "source_refs": [ref(3, 4)]}, {"episode_id": F, "source_refs": [ref(1, 2)]}],
            "reason": "the two original turns were assigned in reverse"}
        self.fail_cognition = False
        def business(task):
            return {"episode": episode, "correction": episode, "knowledge": knowledge, "cognition": cognition, "context": context}[task["kind"]]
        self.runtime = Runtime(self.store, Config(self.store), self.execute,
            lambda task, result: business(task).validate_task(self.runtime, task, result),
            prepare_result=lambda task, result: business(task).prepare_result(self.runtime, task, result),
            after_commit=lambda task: business(task).after_commit(self.runtime, task))
        self.addCleanup(self.runtime.close)

    def execute(self, task, control):
        if task["kind"] == "correction":
            inputs = episode.execution_task(control, task)["inputs"]
            for assignment in inputs["assignments"]:
                identifier = assignment["episode_id"]
                record = deepcopy(self.episodes[identifier])
                record["source_refs"] = assignment["source_refs"]
                record["boundary_basis"] = {"reason": inputs["reason"], "source_refs": assignment["source_refs"], "evaluation_versions": []}
                atomic_json(Path(task["workspace"]) / "episodes" / (identifier + ".json"), record)
            return {"episode_refs": [{"id": E}, {"id": F}], "closed_episode_refs": [],
                "revised_episode_refs": [{"id": E}, {"id": F}], "buffered_source_refs": [], "reason": inputs["reason"]}
        if task["kind"] == "knowledge":
            knowledge.execution_task(control, task)
            return {"knowledge_refs": [], "relation_refs": [], "reason": "no content changes"}
        if task["kind"] == "cognition":
            cognition.execution_task(control, task)
            if self.fail_cognition:
                raise RuntimeError("synthetic analysis failure")
            return {"knowledge_refs": [], "relation_refs": [], "hypothesis_refs": [], "reason": "grouping changed; old evidence remains valid"}
        raise AssertionError("Unexpected task")

    def run_task(self, task):
        self.runtime.dispatch()
        result = self.runtime.wait(task["id"])
        self.assertEqual(result["status"], "succeeded", result["error"])
        return result

    def test_revision_marks_direct_judgment_in_same_commit_and_only_latest_analysis_clears(self):
        record_ref = {"id": K, "version": self.store.put_version(self.original)}
        candidate = {"id": "b" * 32, "record_refs": [record_ref]}
        self.assertTrue(context._candidate_current(self.runtime, candidate))
        invocation = "c" * 32
        before_query = context.start_query(self.runtime, "synthetic", "knowledge:" + K, invocation)
        self.assertEqual(before_query["result"]["items"][0]["reanalysis"], [])
        task = episode.register_correction(self.runtime, self.request)
        self.assertEqual(episode.register_correction(self.runtime, self.request)["id"], task["id"])
        submission = task["inputs"]["submission_ref"]
        self.assertEqual(submission["source_kind"], "user_submission")
        completed = self.run_task(task)
        waiting = cognition.reanalysis(self.store, K)
        self.assertTrue(waiting)
        self.assertTrue(all(item["status"] == "waiting" for item in waiting))
        self.assertFalse(context._candidate_current(self.runtime, candidate))
        self.assertEqual(cognition.reanalysis(self.store, U), [])
        self.assertEqual((self.store.home / "knowledge" / (K + ".json")).read_bytes(), self.original)
        paths = {item["path"] for item in self.store.read_commit(completed["commit_id"])["items"]}
        self.assertIn("cognition/reanalysis.json", paths)
        self.assertIn("episodes/" + E + ".json", paths)
        result = context._direct(self.runtime, "knowledge:" + K)
        self.assertEqual(result["items"][0]["reanalysis"], waiting)
        self.assertEqual(context.query_status(self.runtime, invocation)["result"]["items"][0]["reanalysis"], waiting)
        old_ref = self.request["episode_refs"][0]
        self.assertEqual(json.loads(self.store.read_version(old_ref["version"])), self.episodes[E])
        content = next(item for item in self.runtime.tasks() if item["kind"] == "knowledge")
        self.run_task(content)
        analysis = next(item for item in self.runtime.tasks() if item["kind"] == "cognition")
        self.fail_cognition = True
        self.runtime.dispatch()
        self.assertEqual(self.runtime.wait(analysis["id"])["status"], "failed")
        self.assertTrue(any(item["status"] == "waiting" for item in cognition.reanalysis(self.store, K)))
        self.fail_cognition = False
        # A separate open session uses this judgment; resolving waiting must refresh it without material updates.
        active_id = "d" * 32
        active_ref = {"connector": "codex", "session_key": "active", "line_start": 1, "line_end": 1}
        (self.store.home / "codex/queue/active.jsonl").write_text('{"role":"user","text":"synthetic active context"}\n', encoding="utf-8")
        active_path = self.store.home / "episodes" / (active_id + ".json")
        atomic_json(active_path, {"id": active_id, "connector": "codex", "session_key": "active", "state": "open", "source_refs": [active_ref]})
        active_version = self.store.put_version(active_path.read_bytes())
        atomic_json(episode.state_path(self.store.home, "active"), {"connector": "codex", "session_key": "active", "active_episode_id": active_id,
            "buffer": [], "processed_line": 1, "material_updates": 2})
        (self.store.home / "contexts").mkdir()
        atomic_json(self.store.home / "contexts/active.json", {"id": "c" * 32, "session_key": "active",
            "episode_ref": {"id": active_id, "version": active_version}, "record_refs": [record_ref], "material_updates": 2})
        self.runtime.retry(analysis["id"])
        self.run_task(self.runtime.task(analysis["id"]))
        self.assertTrue(all(item["status"] == "ready" for item in cognition.reanalysis(self.store, K)))
        self.assertFalse(context._candidate_current(self.runtime, candidate), "Clearing waiting does not revive an old candidate")
        candidate["reanalysis_versions"] = cognition.reanalysis_versions(self.store, candidate["record_refs"])
        self.assertTrue(context._candidate_current(self.runtime, candidate))
        refresh = [item for item in self.runtime.tasks() if item["kind"] == "context"]
        self.assertEqual(len(refresh), 1)
        self.assertEqual(refresh[0]["inputs"]["material_updates"], 2)
        self.assertEqual(refresh[0]["dependencies"], [analysis["id"]])

    def test_old_knowledge_and_cognition_inputs_cannot_publish_or_clear_waiting(self):
        self.run_task(episode.register_correction(self.runtime, self.request))
        current = self.store.home / "episodes" / (E + ".json")
        current_bytes = current.read_bytes()
        for kind in ("knowledge", "cognition"):
            with self.subTest(kind=kind):
                old = self.request["episode_refs"]
                if kind == "knowledge":
                    task = knowledge.register_episode_analysis(self.runtime, old, "superseded", "old knowledge")
                else:
                    task = cognition.register_analysis(self.runtime, old, {}, "superseded", "old cognition")
                # Keep unrelated queued work from consuming the ordinary slot in this isolated check.
                for queued in self.runtime.tasks():
                    if queued["id"] != task["id"] and queued["status"] == "queued":
                        self.runtime.cancel(queued["id"], "test executes the selected stale dependency")
                self.runtime.dispatch()
                self.assertEqual(self.runtime.task(task["id"])["status"], "cancelled")
                latest = [{"id": E, "version": self.store.put_version(current.read_bytes())}]
                if kind == "knowledge":
                    task = knowledge.register_episode_analysis(self.runtime, latest, "running old input", "running knowledge")
                else:
                    task = cognition.register_analysis(self.runtime, latest, {}, "running old input", "running cognition")
                def stale_during_execution(task, control):
                    module = knowledge if task["kind"] == "knowledge" else cognition
                    module.execution_task(control, task)
                    control.reserve_generation(task["id"])
                    record = json.loads(current.read_text(encoding="utf-8"))
                    atomic_json(current, {**record, "summary": "another revision"})
                    return {"knowledge_refs": [], "relation_refs": [], **({"hypothesis_refs": []} if task["kind"] == "cognition" else {}), "reason": "stale"}
                self.runtime.execute = stale_during_execution
                self.runtime.dispatch()
                completed = self.runtime.wait(task["id"])
                self.assertEqual(completed["status"], "cancelled", completed["error"])
                self.assertEqual(completed["model_calls"], 1)
                self.assertTrue(any(item["status"] == "waiting" for item in cognition.reanalysis(self.store, K)))
                current.write_bytes(current_bytes)

    def test_conflicts_and_invalid_ownership_are_rejected_before_registering(self):
        for mutate in (lambda request: request["assignments"][0].update(source_refs=[ref(1, 4)]),
                       lambda request: request["assignments"][0].update(source_refs=[ref(3)]),
                       lambda request: request.update(session_key="another"),
                       lambda request: request["episode_refs"][0].update(version="0" * 64)):
            request = deepcopy(self.request)
            mutate(request)
            with self.subTest(request=request), self.assertRaises((ValueError, ConflictError)):
                episode.register_correction(self.runtime, request)
        self.assertEqual(self.runtime.tasks(), [])

    def test_changed_input_cancels_queued_correction_without_overwriting(self):
        task = episode.register_correction(self.runtime, self.request)
        path = self.store.home / "episodes" / (E + ".json")
        updated = {**self.episodes[E], "summary": "newer saved summary"}
        atomic_json(path, updated)
        self.runtime.dispatch()
        self.assertEqual(self.runtime.task(task["id"])["status"], "cancelled")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), updated)

    def test_agent_cannot_publish_its_own_reanalysis_marker(self):
        original = self.execute
        def tamper(task, control):
            result = original(task, control)
            path = Path(task["workspace"]) / "cognition/reanalysis.json"
            path.parent.mkdir(exist_ok=True)
            atomic_json(path, {"entries": []})
            return result
        self.runtime.execute = tamper
        task = episode.register_correction(self.runtime, self.request)
        self.runtime.dispatch()
        completed = self.runtime.wait(task["id"])
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["error"]["code"], "ValueError")
        self.assertFalse((self.store.home / "cognition/reanalysis.json").exists())
        for ref in self.request["episode_refs"]:
            self.assertEqual((self.store.home / "episodes" / (ref["id"] + ".json")).read_bytes(), self.store.read_version(ref["version"]))

    def test_shared_hypothesis_dependents_wait_but_graph_neighbors_do_not(self):
        hypothesis_id, relation_id = "b" * 32, "c" * 32
        other = self.store.home / "knowledge" / (U + ".json")
        record = json.loads(other.read_text(encoding="utf-8"))
        atomic_json(other, {**record, "hypothesis_refs": [hypothesis_id]})
        (self.store.home / "hypotheses").mkdir()
        atomic_json(self.store.home / "hypotheses" / (hypothesis_id + ".json"), {"id": hypothesis_id,
            "claim": "synthetic shared hypothesis", "status": "open", "needed_evidence": "independent use",
            "knowledge_refs": [{"id": identifier, "version": self.store.put_version((self.store.home / "knowledge" / (identifier + ".json")).read_bytes())} for identifier in (K, U)],
            "relation_refs": [], "supporting_observations": [{"record_id": K, "observation_id": O}], "counter_observations": []})
        (self.store.home / "relations").mkdir()
        atomic_json(self.store.home / "relations" / (relation_id + ".json"), {"id": relation_id, "name": "graph neighbor only",
            "source_knowledge_id": K, "target_knowledge_id": U, "content": {"statement": "synthetic connection", "source_refs": [ref(1)]}})
        self.run_task(episode.register_correction(self.runtime, self.request))
        self.assertTrue(cognition.reanalysis(self.store, hypothesis_id))
        self.assertTrue(cognition.reanalysis(self.store, U))
        self.assertEqual(cognition.reanalysis(self.store, relation_id), [])

    def test_web_cognition_correction_is_an_independent_source_without_a_forged_episode(self):
        request = {"record_kind": "knowledge", "record_id": K, "expected_version": self.store.put_version(self.original),
            "performance": "My earlier response repeated the supplied explanation; I have not used it independently.",
            "help": "A full worked example was visible", "reason": "correct the conditions of the recorded performance"}
        task = cognition.register_correction(self.runtime, request)
        self.assertEqual(cognition.register_correction(self.runtime, request)["id"], task["id"])
        def correct(task, control):
            inputs = cognition.execution_task(control, task)["inputs"]
            source = inputs["submission_ref"]
            identifier = cognition.allocate_id(control, task["id"], "observation", [source])["id"]
            record = deepcopy(next(item["record"] for item in inputs["records"] if item["id"] == K))
            record["observations"].append({"id": identifier, "observed_at": inputs["assessment_at"], "source": {"source_refs": [source]},
                "task": "correct prior evidence conditions", "help": request["help"], "performance": request["performance"]})
            record["cognition"] = {"assessed_at": inputs["assessment_at"], "observation_ids": [identifier], "summary": "independent use remains unverified"}
            atomic_json(Path(task["workspace"]) / "knowledge" / (K + ".json"), record)
            return {"knowledge_refs": [{"id": K}], "relation_refs": [], "hypothesis_refs": [], "reason": request["reason"]}
        self.runtime.execute = correct
        self.run_task(task)
        saved = json.loads((self.store.home / "knowledge" / (K + ".json")).read_text(encoding="utf-8"))
        self.assertNotIn("episode_id", saved["observations"][-1]["source"])
        self.assertEqual(saved["content"], json.loads(self.original)["content"])
        self.assertEqual(saved["observations"][0], json.loads(self.original)["observations"][0])
        source = saved["observations"][-1]["source"]["source_refs"][0]
        from distillai.sources import read_source
        self.assertEqual(read_source(self.store.home, source)["record"]["payload"], request)

    def test_explicit_reanalysis_uses_current_snapshot_without_resetting_failed_task(self):
        self.run_task(episode.register_correction(self.runtime, self.request))
        content = next(task for task in self.runtime.tasks() if task["kind"] == "knowledge")
        self.run_task(content)
        failed = next(task for task in self.runtime.tasks() if task["kind"] == "cognition")
        self.fail_cognition = True
        self.runtime.dispatch()
        self.assertEqual(self.runtime.wait(failed["id"])["status"], "failed")
        target = self.store.home / "knowledge" / (K + ".json")
        current = json.loads(target.read_text(encoding="utf-8"))
        atomic_json(target, {**current, "cognition": {**current["cognition"], "summary": "later explicit correction"}})
        request = {"client_request_id": "synthetic-reanalysis", "record_id": K, "reason": "analyse the latest current evidence"}
        fresh = cognition.request_reanalysis(self.runtime, request)
        self.assertNotEqual(fresh["id"], failed["id"])
        self.assertEqual(cognition.request_reanalysis(self.runtime, request)["id"], fresh["id"])
        self.assertEqual(self.runtime.task(failed["id"])["status"], "failed")
        self.fail_cognition = False
        self.run_task(fresh)
        analysis = next(task for task in self.runtime.tasks() if task["kind"] == "cognition" and task["status"] == "queued")
        self.run_task(analysis)
        self.assertTrue(all(item["status"] == "ready" for item in cognition.reanalysis(self.store, K)))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["cognition"]["summary"], "later explicit correction")
        self.assertEqual(cognition.request_reanalysis(self.runtime, request)["id"], fresh["id"])

    def test_mcp_feedback_reuses_actual_sources_and_can_commit_program_waiting_state(self):
        self.run_task(episode.register_correction(self.runtime, self.request))
        for task in self.runtime.tasks():
            if task["status"] == "queued":
                self.runtime.cancel(task["id"], "exercise explicit feedback analysis")
        observed_ids = []
        def maintain(task, control):
            inputs = cognition.execution_task(control, task)["inputs"]
            source = inputs["feedback"]["source_refs"]
            identifier = cognition.allocate_id(control, task["id"], "observation", source)["id"]
            observed_ids.append(identifier)
            record = deepcopy(next(item["record"] for item in inputs["records"] if item["id"] == K))
            observation = {"id": identifier, "observed_at": None, "source": {"episode_id": E, "source_refs": source},
                "task": "synthetic current user performance", "help": inputs["feedback"]["help"], "performance": "second"}
            record["observations"] = [item for item in record["observations"] if item["id"] != identifier] + [observation]
            record["cognition"] = {"assessed_at": inputs["assessment_at"], "observation_ids": [identifier], "summary": "evidence conditions reviewed; no mastery claim"}
            atomic_json(Path(task["workspace"]) / "knowledge" / (K + ".json"), record)
            return {"knowledge_refs": [{"id": K}], "relation_refs": [], "hypothesis_refs": [], "reason": "current grouped evidence"}
        self.runtime.execute = maintain
        for request_id in ("feedback-first", "feedback-supplement"):
            feedback = context.submit_feedback(self.runtime, {"client_request_id": request_id, "session_key": "synthetic",
                "performance": "second", "task": "synthetic task", "help": "none" if request_id == "feedback-first" else "earlier example was visible",
                "knowledge_refs": [], "relation_refs": [], "source_refs": [ref(3)]})
            self.run_task(self.runtime.task(feedback["task_id"]))
        self.assertEqual(observed_ids[0], observed_ids[1])
        saved = json.loads((self.store.home / "knowledge" / (K + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["observations"]), 2)
        self.assertEqual(saved["observations"][-1]["help"], "earlier example was visible")
        self.assertTrue(all(item["status"] == "ready" for item in cognition.reanalysis(self.store, K)))

    def test_new_material_revision_requires_actual_new_quotes_and_commits_direct_waiting(self):
        active_id = "9" * 32
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        with queue.open("a", encoding="utf-8") as stream:
            for role, text in [("user", "current goal"), ("assistant", "current answer"), ("user", "the earlier first and second turns were assigned in reverse")]:
                stream.write(json.dumps({"role": role, "text": text}) + "\n")
        active = {**self.episodes[E], "id": active_id, "state": "open", "source_refs": [ref(5, 6)],
            "boundary_basis": {"reason": "current exchange", "source_refs": [ref(5)], "evaluation_versions": []}}
        atomic_json(self.store.home / "episodes" / (active_id + ".json"), active)
        atomic_json(episode.state_path(self.store.home, "synthetic"), {"connector": "codex", "session_key": "synthetic",
            "active_episode_id": active_id, "buffer": [], "processed_line": 6, "material_updates": 2})
        def maintain(task, control):
            inputs = episode.execution_task(control, task)["inputs"]
            old = episode.read_episode_source(control, task["id"], {"ref": ref(1, 2)})
            self.assertEqual(old["rows"][0]["text"], "first")
            with self.assertRaises(ValueError):
                episode.read_episode_source(control, task["id"], {"ref": ref(8)})
            proposed = {**self.request, "basis": [{"source_ref": ref(7), "quote": "assigned in reverse"}]}
            with self.assertRaises(ValueError):
                episode.evaluate_revision(control, task["id"], {**proposed, "episode_refs": [None]})
            for invalid in ([{"source_ref": ref(1), "quote": "first"}], [{"source_ref": ref(7), "quote": "invented quote"}]):
                with self.assertRaises(ValueError):
                    episode.evaluate_revision(control, task["id"], {**proposed, "basis": invalid})
            approved = episode.evaluate_revision(control, task["id"], proposed)
            self.assertIn("revision_version", approved)
            evaluation = episode.evaluate(control, task["id"], {"episode_ref": inputs["active_episode_ref"], "episode_keywords": [],
                "episode_source_refs": [ref(5)], "episode_basis": [{"source_ref": ref(5), "quote": "current goal"}],
                "candidates": [{"source_refs": [ref(7)], "keywords": [], "C": 4, "basis": proposed["basis"], "reason": "correction within current exchange", "group": "current"}]})
            for item in self.request["assignments"]:
                original = inputs["episode_records"][item["episode_id"]]["record"]
                record = {**original, "source_refs": item["source_refs"], "boundary_basis": {
                    "reason": self.request["reason"], "source_refs": item["source_refs"], "evaluation_versions": []}}
                atomic_json(Path(task["workspace"]) / "episodes" / (item["episode_id"] + ".json"), record)
            atomic_json(Path(task["workspace"]) / "episodes" / (active_id + ".json"), {**active, "source_refs": [ref(5, 7)]})
            return {"episode_refs": [{"id": item} for item in (E, F, active_id)], "closed_episode_refs": [],
                "revised_episode_refs": [{"id": E}, {"id": F}], "buffered_source_refs": [], "reason": "new raw evidence corrects only the old grouping"}
        self.runtime.execute = maintain
        task = episode.register_material(self.runtime, ref(7))
        self.run_task(task)
        entries = cognition.reanalysis(self.store, K)
        self.assertTrue(entries)
        self.assertTrue(all(item["revision_source_refs"] == [ref(7)] for item in entries))
        self.assertTrue(all("submission_ref" not in item for item in entries))
        self.assertEqual(episode.state(self.store.home, "synthetic")["processed_line"], 7)


if __name__ == "__main__":
    unittest.main()
