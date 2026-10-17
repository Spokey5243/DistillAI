"""Episode boundaries preserve source ownership and use program-computed scores."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from distillai import episode
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json


KEY = "synthetic"
OLD = "1" * 32
NEW = "2" * 32


def ref(start, end=None):
    return {"connector": "codex", "session_key": KEY, "line_start": start, "line_end": end or start}


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        path = self.home / "codex/queue/synthetic.jsonl"
        path.parent.mkdir(parents=True)
        self.rows = [("user", "old goal"), ("assistant", "working"), ("tool", "used build"),
                     ("assistant", "old answer"), ("user", "new request"), ("assistant", "new answer"),
                     ("user", "new follow up"), ("assistant", "follow up answer"), ("user", "third request")]
        path.write_bytes(b"".join((json.dumps({"role": role, "text": text}) + "\n").encode() for role, text in self.rows))
        self.inputs = {"session_key": KEY, "active_episode_ref": {"id": OLD, "version": "a" * 64},
                       "active_source_refs": [ref(1, 2), ref(4)],
                       "turns": episode.turns(self.home, KEY, 9)[1:],
                       "sources": [{"ref": ref(i), "rows": [{"role": role, "text": text}]} for i, (role, text) in enumerate(self.rows, 1)]}
        self.args = {"episode_ref": self.inputs["active_episode_ref"], "episode_keywords": ["old"],
                     "episode_source_refs": [ref(1)], "episode_basis": [{"source_ref": ref(1), "quote": "old goal"}],
                     "candidates": [{"source_refs": [ref(5, 6)], "keywords": ["new"], "C": 0,
                                     "basis": [{"source_ref": ref(5), "quote": "new request"}], "reason": "independent request", "group": "new goal"}]}

    def test_damaged_or_cross_session_cursor_is_not_adopted(self):
        original = episode.state(self.home, KEY)
        path = episode.state_path(self.home, KEY)
        path.parent.mkdir(exist_ok=True)
        for changed in ({"session_key": "other-session"}, {"processed_line": True}, {"extra": "ignored"}):
            atomic_json(path, {**original, **changed})
            before = path.read_bytes()
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                episode.state(self.home, KEY)
            self.assertEqual(path.read_bytes(), before)

    def test_rounds_join_intermediate_and_final_assistant_without_counting_tools(self):
        rounds = episode.turns(self.home, KEY, 9)
        self.assertEqual([r["source_refs"] for r in rounds], [[ref(1, 2), ref(4)], [ref(5, 6)], [ref(7, 8)], [ref(9)]])
        self.assertEqual(rounds[0]["text"], "user: old goal\nassistant: working\nassistant: old answer")
        self.assertEqual(episode.turns(self.home, KEY, 4)[0], rounds[0])

    def test_scores_follow_approved_formula_and_normalize_keywords(self):
        for old, new, continuity, expected_k, expected_s in [(["old"], ["new"], 4, 0, .8),
                (["old"], ["old"], 0, 1, 3.2), (["a", "b"], ["a"], 2, .5, 2), ([], ["new"], 1, None, 3)]:
            args = deepcopy(self.args)
            args["episode_keywords"] = old
            args["candidates"][0].update(keywords=new, C=continuity)
            result = episode.score_boundary(self.inputs, args)["evaluations"][0]
            self.assertEqual(result["K"], expected_k)
            self.assertAlmostEqual(result["S"], expected_s)
        args = deepcopy(self.args)
        args["episode_keywords"] = [" Old ", "OLD", ""]
        self.assertEqual(episode.score_boundary(self.inputs, args)["episode_keywords"], ["old"])

    def test_scoring_rejects_invalid_continuity_missing_quotes_and_outside_snapshot(self):
        for change in ({"C": 5}, {"C": True}, {"C": 1.5}, {"basis": []}, {"reason": ""},
                       {"keywords": [str(i) for i in range(6)]}, {"source_refs": [ref(1)]},
                       {"basis": [{"source_ref": ref(5), "quote": "invented evidence"}]},
                       {"basis": [{"source_ref": ref(1), "quote": "old goal"}]}):
            args = deepcopy(self.args)
            args["candidates"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                episode.score_boundary(self.inputs, args)
        for change in ({"active_episode_ref": None}, {"active_episode_ref": {"id": NEW, "version": "a" * 64}}):
            with self.assertRaises(ValueError):
                episode.score_boundary({**self.inputs, **change}, self.args)

    def runtime(self, execute):
        store = Store(self.home)
        runtime = Runtime(store, Config(store), execute,
            lambda task, result: episode.validate_task(runtime, task, result),
            prepare_result=lambda task, result: episode.prepare_result(runtime, task, result),
            after_commit=lambda task: episode.after_commit(runtime, task))
        self.addCleanup(lambda: runtime.close() if store.home.exists() else None)
        return runtime

    def write_first(self, task, runtime, *, mutate=None):
        prepared = episode.execution_task(runtime, task)
        inputs = prepared["inputs"]
        identifier = inputs["new_episode_ids"][0]
        record = {"id": identifier, "connector": "codex", "session_key": KEY, "topic": "old topic", "goal": "old goal",
                  "state": "open", "source_refs": [ref(1, 2), ref(4)],
                  "boundary_basis": {"reason": "initial exchange", "source_refs": [ref(1)], "evaluation_versions": []}}
        current = {**inputs["state"], "active_episode_id": identifier}
        if mutate:
            mutate(record, current)
        workspace = Path(task["workspace"])
        (workspace / "episodes").mkdir(exist_ok=True)
        (workspace / "buffers").mkdir(exist_ok=True)
        atomic_json(workspace / "episodes" / (identifier + ".json"), record)
        atomic_json(workspace / "buffers" / (KEY + ".json"), current)
        return {"episode_refs": [{"id": identifier}], "closed_episode_refs": [], "revised_episode_refs": [],
                "buffered_source_refs": [], "reason": "initial exchange"}

    def test_initial_commit_advances_processing_only_after_publication_and_registers_prepare(self):
        runtime = self.runtime(self.write_first)
        task = episode.register_material(runtime, ref(1, 9))
        self.assertEqual(task["inputs"]["source_refs"], [ref(1, 4)])
        self.assertEqual(episode.register_material(runtime, ref(5, 9))["id"], task["id"])
        self.assertEqual(episode.state(self.home, KEY)["processed_line"], 0)
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        current = episode.state(self.home, KEY)
        self.assertEqual((current["processed_line"], current["material_updates"]), (4, 1))
        result = json.loads(runtime.store.read_version(completed["result_version"]))
        self.assertEqual(len(result["episode_refs"][0]["version"]), 64)
        self.assertEqual(len([t for t in runtime.tasks() if t["kind"] == "context"]), 1)
        episode.after_commit(runtime, completed)
        self.assertEqual(len([t for t in runtime.tasks() if t["kind"] == "context"]), 1)
        follow = episode.register_material(runtime, ref(5, 9))
        self.assertEqual(follow["inputs"]["source_refs"], [ref(5, 9)])

    def test_bad_ownership_or_agent_processing_edits_never_advance_live_state(self):
        changes = [lambda record, current: record.update(source_refs=[ref(1, 2)]),
                   lambda record, current: record.update(session_key="other"),
                   lambda record, current: current.update(processed_line=4),
                   lambda record, current: record.update(id=NEW),
                   lambda record, current: (record.update(state="closed", summary="x", close_reason="idle"), current.update(active_episode_id=None))]
        for index, change in enumerate(changes):
            with self.subTest(change=index), tempfile.TemporaryDirectory() as directory:
                previous = self.home
                self.home = Path(directory)
                queue = self.home / "codex/queue/synthetic.jsonl"
                queue.parent.mkdir(parents=True)
                queue.write_bytes((previous / "codex/queue/synthetic.jsonl").read_bytes())
                runtime = self.runtime(lambda task, control: self.write_first(task, control, mutate=change))
                task = episode.register_material(runtime, ref(1, 4))
                runtime.dispatch()
                completed = runtime.wait(task["id"])
                self.assertEqual(completed["status"], "failed")
                self.assertEqual(episode.state(self.home, KEY)["processed_line"], 0)
                self.assertEqual(list((self.home / "episodes").glob("*.json")), [])
                runtime.close()
                self.home = previous

    def test_switch_uses_recorded_window_and_keeps_original_goal(self):
        runtime = self.runtime(self.write_first)
        first = episode.register_material(runtime, ref(1, 9))
        runtime.dispatch()
        self.assertEqual(runtime.wait(first["id"])["status"], "succeeded")
        for task in runtime.tasks():
            if task["kind"] == "context":
                runtime.cancel(task["id"], "synthetic downstream not executed")

        def switch(task, control):
            prepared = episode.execution_task(control, task)
            inputs = prepared["inputs"]
            old = deepcopy(inputs["active_episode"])
            args = {"episode_ref": inputs["active_episode_ref"], "episode_keywords": ["old"],
                    "episode_source_refs": [ref(1)], "episode_basis": [{"source_ref": ref(1), "quote": "old goal"}],
                    "candidates": [{"source_refs": turn["source_refs"], "keywords": ["new"], "C": 0,
                                    "basis": [{"source_ref": turn["source_refs"][0], "quote": turn["text"].split(": ", 1)[1].split("\n")[0]}],
                                    "reason": "new exchange", "group": "new goal"} for turn in inputs["turns"]]}
            evaluation = episode.evaluate(control, task["id"], args)
            self.assertEqual(control.task(task["id"])["model_calls"], 0)
            old.update(state="closed", summary="old exchange", close_reason="topic switch")
            identifier = inputs["new_episode_ids"][0]
            record = {"id": identifier, "connector": "codex", "session_key": KEY, "topic": "new topic", "goal": "new goal",
                      "state": "open", "source_refs": [ref(5, 9)],
                      "boundary_basis": {"reason": "whole new window", "source_refs": [ref(5, 9)], "evaluation_versions": [evaluation["evaluation_version"]]}}
            root = Path(task["workspace"])
            atomic_json(root / "episodes" / (old["id"] + ".json"), old)
            atomic_json(root / "episodes" / (identifier + ".json"), record)
            atomic_json(root / "buffers" / (KEY + ".json"), {**inputs["state"], "active_episode_id": identifier})
            return {"episode_refs": [{"id": old["id"]}, {"id": identifier}], "closed_episode_refs": [{"id": old["id"]}],
                    "revised_episode_refs": [], "buffered_source_refs": [], "reason": "confirmed switch"}

        runtime.execute = switch
        task = episode.register_material(runtime, ref(5, 9))
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        self.assertEqual(episode.state(self.home, KEY)["processed_line"], 9)
        self.assertEqual(episode.state(self.home, KEY)["material_updates"], 1)
        self.assertEqual(len([t for t in runtime.tasks() if t["kind"] == "knowledge"]), 1)
        old_id = json.loads(runtime.store.read_version(runtime.task(first["id"])["result_version"]))["episode_refs"][0]["id"]
        self.assertEqual(json.loads((self.home / "episodes" / (old_id + ".json")).read_text())["goal"], "old goal")

    def test_new_user_turns_cannot_be_assigned_without_scoring(self):
        runtime = self.runtime(self.write_first)
        first = episode.register_material(runtime, ref(1, 9))
        runtime.dispatch()
        self.assertEqual(runtime.wait(first["id"])["status"], "succeeded")
        for task in runtime.tasks():
            if task["kind"] == "context":
                runtime.cancel(task["id"], "synthetic downstream not executed")

        def unscored(task, control):
            prepared = episode.execution_task(control, task)
            inputs = prepared["inputs"]
            record = {**inputs["active_episode"], "source_refs": [ref(1, 2), ref(4, 9)]}
            root = Path(task["workspace"])
            atomic_json(root / "episodes" / (record["id"] + ".json"), record)
            atomic_json(root / "buffers" / (KEY + ".json"), inputs["state"])
            return {"episode_refs": [{"id": record["id"]}], "closed_episode_refs": [], "revised_episode_refs": [],
                    "buffered_source_refs": [], "reason": "unsupported continuation"}

        runtime.execute = unscored
        task = episode.register_material(runtime, ref(5, 9))
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(episode.state(self.home, KEY)["processed_line"], 4)

    def test_buffered_exchanges_require_joint_review_when_a_later_turn_returns(self):
        runtime = self.runtime(self.write_first)
        first = episode.register_material(runtime, ref(1, 4))
        runtime.dispatch()
        self.assertEqual(runtime.wait(first["id"])["status"], "succeeded")
        for task in runtime.tasks():
            if task["kind"] == "context":
                runtime.cancel(task["id"], "synthetic downstream not executed")

        def maintain(task, control, *, clear_without_review=False):
            inputs = episode.execution_task(control, task)["inputs"]
            selected = inputs["turns"][-1:] if clear_without_review else inputs["turns"]
            candidates = [{"source_refs": turn["source_refs"], "keywords": [], "C": 4 if turn["source_refs"][0]["line_start"] == 9 else 2,
                           "basis": [{"source_ref": turn["source_refs"][0], "quote": turn["text"].split(": ", 1)[1].split("\n")[0]}],
                           "reason": "insufficient evidence" if turn["source_refs"][0]["line_start"] != 9 else "returns to old goal",
                           "group": "independent " + str(turn["source_refs"][0]["line_start"])} for turn in selected]
            evaluation = episode.evaluate(control, task["id"], {"episode_ref": inputs["active_episode_ref"],
                "episode_keywords": [], "episode_source_refs": [ref(1)], "episode_basis": [{"source_ref": ref(1), "quote": "old goal"}], "candidates": candidates})
            buffered = [{name: candidate[name] for name in ("source_refs", "keywords", "C", "reason", "group")}
                        | {"evaluation_version": evaluation["evaluation_version"]} for candidate in evaluation["evaluations"] if candidate["S"] >= 2]
            root = Path(task["workspace"])
            current = {**inputs["state"], "buffer": buffered}
            refs = []
            if inputs["line_end"] == 9:
                record = {**inputs["active_episode"], "source_refs": [ref(1, 2), ref(4, 9)] if clear_without_review else [ref(1, 2), ref(4), ref(9)]}
                atomic_json(root / "episodes" / (record["id"] + ".json"), record)
                refs = [{"id": record["id"]}]
            atomic_json(root / "buffers" / (KEY + ".json"), current)
            return {"episode_refs": refs, "closed_episode_refs": [], "revised_episode_refs": [],
                    "buffered_source_refs": [ref(5, 8)] if buffered else [], "reason": "joint review"}

        runtime.execute = maintain
        pending = episode.register_material(runtime, ref(5, 8))
        runtime.dispatch()
        self.assertEqual(runtime.wait(pending["id"])["status"], "succeeded")
        before = episode.state(self.home, KEY)
        self.assertEqual(before["material_updates"], 1)
        self.assertEqual(len(before["buffer"]), 2)
        self.assertNotEqual(before["buffer"][0]["group"], before["buffer"][1]["group"])
        runtime.execute = lambda task, control: maintain(task, control, clear_without_review=True)
        later = episode.register_material(runtime, ref(9))
        runtime.dispatch()
        self.assertEqual(runtime.wait(later["id"])["status"], "failed")
        self.assertEqual(episode.state(self.home, KEY), before)
        runtime.execute = maintain
        runtime.retry(later["id"])
        runtime.dispatch()
        completed = runtime.wait(later["id"])
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        self.assertEqual(episode.state(self.home, KEY)["processed_line"], 9)
        self.assertEqual(len(episode.state(self.home, KEY)["buffer"]), 2)
        self.assertEqual(episode.state(self.home, KEY)["material_updates"], 2)

    def test_buffered_turn_can_receive_assistant_fragments_in_a_later_capture(self):
        runtime = self.runtime(self.write_first)
        first = episode.register_material(runtime, ref(1, 4))
        runtime.dispatch()
        self.assertEqual(runtime.wait(first["id"])["status"], "succeeded")
        for task in runtime.tasks():
            if task["kind"] == "context":
                runtime.cancel(task["id"], "synthetic downstream not executed")

        def maintain(task, control):
            inputs = episode.execution_task(control, task)["inputs"]
            turn = inputs["turns"][0]
            evaluation = episode.evaluate(control, task["id"], {"episode_ref": inputs["active_episode_ref"],
                "episode_keywords": [], "episode_source_refs": [ref(1)], "episode_basis": [{"source_ref": ref(1), "quote": "old goal"}],
                "candidates": [{"source_refs": turn["source_refs"], "keywords": [], "C": 2 if inputs["line_end"] == 5 else 4,
                    "basis": [{"source_ref": ref(5), "quote": "new request"}], "reason": "jointly reviewed source fragments", "group": "current exchange"}]})
            candidate = evaluation["evaluations"][0]
            pending = candidate["S"] >= 2
            buffer = [{name: candidate[name] for name in ("source_refs", "keywords", "C", "reason", "group")}
                      | {"evaluation_version": evaluation["evaluation_version"]}] if pending else []
            current = {**inputs["state"], "buffer": buffer}
            refs = []
            root = Path(task["workspace"])
            if not pending:
                record = {**inputs["active_episode"], "source_refs": [ref(1, 2), ref(4, 6)]}
                atomic_json(root / "episodes" / (record["id"] + ".json"), record)
                refs = [{"id": record["id"]}]
            atomic_json(root / "buffers/synthetic.json", current)
            return {"episode_refs": refs, "closed_episode_refs": [], "revised_episode_refs": [],
                    "buffered_source_refs": [ref(5)] if pending else [], "reason": "fragments remain in one turn"}

        runtime.execute = maintain
        for source in (ref(5), ref(6)):
            task = episode.register_material(runtime, source)
            runtime.dispatch()
            completed = runtime.wait(task["id"])
            self.assertEqual(completed["status"], "succeeded", completed["error"])
        self.assertEqual(episode.state(self.home, KEY)["buffer"], [])
        self.assertEqual(episode.state(self.home, KEY)["processed_line"], 6)


if __name__ == "__main__":
    unittest.main()
