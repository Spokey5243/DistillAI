"""Normalized lifecycle contracts; synthetic events do not validate Desktop Hooks."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from distillai import episode, lifecycle
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json


class LifecycleTests(unittest.TestCase):
    def test_invalid_saved_event_cannot_advance_or_close_the_session(self):
        original = self.observe("request_started", 0)
        path = self.home / "events/lifecycle/synthetic.json"
        original.pop("version")
        for changed in ({"sequence": True}, {"line_end": False}, {"session_key": "other-session"},
                        {"kind": "guessed_end"}, {"unknown": "ignored"}):
            with self.subTest(changed=changed):
                atomic_json(path, {**original, **changed})
                saved = path.read_bytes()
                with self.assertRaises(ValueError):
                    lifecycle.observe(self.runtime, "synthetic", "response_stopped", observed_at=self.at(1))
                with self.assertRaises(ValueError):
                    lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(31))
                self.assertEqual(path.read_bytes(), saved)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.store = Store(self.home)
        self.runtime = Runtime(self.store, Config(self.store), lambda *_: None, lambda *_: None)
        self.addCleanup(self.runtime.close)
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.queue = self.home / "codex/queue/synthetic.jsonl"
        self.queue.parent.mkdir(parents=True)
        self.queue.write_text('{"role":"user","text":"synthetic request"}\n', encoding="utf-8")

    def at(self, minutes):
        return (self.start + timedelta(minutes=minutes)).isoformat()

    def observe(self, kind, minutes):
        return lifecycle.observe(self.runtime, "synthetic", kind, observed_at=self.at(minutes))

    def test_restart_uses_original_deadline_and_new_request_pauses_then_restarts(self):
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(100)))
        self.observe("request_started", 0)
        stopped = self.observe("response_stopped", 1)
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(30)))
        restarted = Runtime(Store(self.home), Config(Store(self.home)), lambda *_: None, lambda *_: None)
        self.addCleanup(restarted.close)
        signal = lifecycle.closing_signal(restarted, "synthetic", at=self.at(31))
        self.assertEqual(signal["event_version"], stopped["version"])
        self.assertEqual(signal["line_end"], 1)
        self.observe("request_started", 31)
        self.assertIsNone(lifecycle.closing_signal(restarted, "synthetic", at=self.at(100)))
        stopped_again = self.observe("response_stopped", 32)
        self.assertIsNone(lifecycle.closing_signal(restarted, "synthetic", at=self.at(61)))
        self.assertEqual(lifecycle.closing_signal(restarted, "synthetic", at=self.at(62))["event_version"], stopped_again["version"])
        self.assertEqual(json.loads(self.store.read_version(stopped_again["version"]))["previous_version"],
                         lifecycle.read(restarted, "synthetic")["previous_version"])

    def test_missing_start_interruption_clock_regression_and_late_material_never_guess_end(self):
        self.observe("response_stopped", 1)
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(100)))
        self.observe("request_started", 101)
        self.observe("interrupted", 102)
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(200)))
        self.observe("request_started", 201)
        self.observe("response_stopped", 200)
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(300)))
        self.observe("request_started", 301)
        self.observe("response_stopped", 302)
        with self.queue.open("a", encoding="utf-8") as stream:
            stream.write('{"role":"assistant","text":"late body"}\n')
        self.assertIsNone(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(400)))
        self.observe("session_ended", 401)
        self.assertEqual(lifecycle.closing_signal(self.runtime, "synthetic", at=self.at(401))["line_end"], 2)
        with self.assertRaises(ValueError):
            self.observe("PreCompact", 402)
        with self.assertRaises(ValueError):
            lifecycle.observe(self.runtime, "../other", "request_started", observed_at=self.at(402))

    def test_closure_waits_for_known_material_and_new_start_cancels_fixed_input(self):
        self.observe("request_started", 0)
        self.observe("response_stopped", 1)
        path = self.home / "buffers/synthetic.json"
        path.parent.mkdir()
        current = {"connector": "codex", "session_key": "synthetic", "active_episode_id": "1" * 32,
                   "buffer": [], "processed_line": 0, "material_updates": 1}
        atomic_json(path, current)
        self.assertIsNone(episode.register_close(self.runtime, "synthetic", at=self.at(31)))
        atomic_json(path, {**current, "processed_line": 1})
        task = episode.register_close(self.runtime, "synthetic", at=self.at(31))
        self.assertEqual(episode.register_close(self.runtime, "synthetic", at=self.at(32))["id"], task["id"])
        self.observe("request_started", 32)
        self.runtime.dispatch()
        completed = self.runtime.wait(task["id"])
        self.assertEqual(completed["status"], "cancelled", completed["error"])
        self.assertEqual(completed["model_calls"], 0)

    def close_buffer(self, independent, *, new_start=False, late_material=False, buffered=True):
        key, identifier = "synthetic", "1" * 32
        def ref(start, end):
            return {"connector": "codex", "session_key": key, "line_start": start, "line_end": end}
        rows = [{"role": role, "text": text} for role, text in
                [("user", "old goal"), ("assistant", "old answer"), ("user", "new request"), ("assistant", "new answer")]]
        self.queue.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        record = {"id": identifier, "connector": "codex", "session_key": key, "topic": "old topic", "goal": "old goal",
                  "state": "open", "source_refs": [ref(1, 2)],
                  "boundary_basis": {"reason": "initial exchange", "source_refs": [ref(1, 1)], "evaluation_versions": []}}
        (self.home / "episodes").mkdir()
        atomic_json(self.home / "episodes" / (identifier + ".json"), record)
        args = {"episode_ref": {"id": identifier, "version": self.store.put_version((self.home / "episodes" / (identifier + ".json")).read_bytes())},
                "episode_keywords": ["old"], "episode_source_refs": [ref(1, 1)],
                "episode_basis": [{"source_ref": ref(1, 1), "quote": "old goal"}],
                "candidates": [{"source_refs": [ref(3, 4)], "keywords": ["new"], "C": 2,
                                "basis": [{"source_ref": ref(3, 3), "quote": "new request"}], "reason": "not settled yet", "group": "new exchange"}]}
        scored = episode.score_boundary({"session_key": key, "active_episode_ref": args["episode_ref"], "active_source_refs": [ref(1, 2)],
            "sources": [{"ref": ref(1, 4), "rows": rows}], "turns": episode.turns(self.home, key, 4)[1:]}, args)
        version = self.store.put_version(json.dumps(scored).encode())
        pending = {name: scored["evaluations"][0][name] for name in ("source_refs", "keywords", "C", "reason", "group")}
        (self.home / "buffers").mkdir()
        atomic_json(episode.state_path(self.home, key), {"connector": "codex", "session_key": key, "active_episode_id": identifier,
            "buffer": [{**pending, "evaluation_version": version}] if buffered else [], "processed_line": 4 if buffered else 2, "material_updates": 2})
        if not buffered:
            self.queue.write_text("".join(json.dumps(row) + "\n" for row in rows[:2]), encoding="utf-8")
        self.observe("request_started", 0)
        self.observe("response_stopped", 1)

        def execute(task, runtime):
            inputs = episode.execution_task(runtime, task)["inputs"]
            self.assertEqual(inputs["closing"]["kind"], "response_stopped")
            scored_now = episode.evaluate(runtime, task["id"], args) if inputs["turns"] else None
            old = {**inputs["active_episode"], "state": "closed", "summary": "old exchange closed", "close_reason": "idle end"}
            old["source_refs"] = [ref(1, 2)] if independent else [ref(1, inputs["line_end"])]
            old["boundary_basis"] = {"reason": "insufficient evidence retained conservatively", "source_refs": old["source_refs"],
                                     "evaluation_versions": [scored_now["evaluation_version"]] if scored_now else []}
            root = Path(task["workspace"])
            atomic_json(root / "episodes" / (identifier + ".json"), old)
            changed = [{"id": identifier}]
            if independent:
                new_id = inputs["new_episode_ids"][0]
                new = {**old, "id": new_id, "topic": "new topic", "goal": "new goal", "source_refs": [ref(3, 4)],
                       "summary": "independent short exchange", "boundary_basis": {"reason": "distinct request in original material",
                       "source_refs": [ref(3, 4)], "evaluation_versions": [scored_now["evaluation_version"]]}}
                atomic_json(root / "episodes" / (new_id + ".json"), new)
                changed.append({"id": new_id})
            atomic_json(episode.state_path(root, key), {**inputs["state"], "buffer": [], "active_episode_id": None})
            if new_start:
                self.observe("request_started", 40)
            if late_material:
                with self.queue.open("a", encoding="utf-8") as stream:
                    stream.write('{"role":"assistant","text":"late completion"}\n')
            return {"episode_refs": changed, "closed_episode_refs": changed, "revised_episode_refs": [],
                    "buffered_source_refs": [], "reason": "close the fixed completed range"}

        runtime = self.runtime
        runtime.execute = execute
        runtime.validate = lambda task, result: episode.validate_task(runtime, task, result)
        runtime.prepare_result = lambda task, result: episode.prepare_result(runtime, task, result)
        runtime.after_commit = lambda task: episode.after_commit(runtime, task)
        task = episode.register_close(runtime, key, at=self.at(31))
        runtime.dispatch()
        completed = runtime.wait(task["id"])
        if new_start or late_material:
            self.assertEqual(completed["status"], "cancelled", completed["error"])
            self.assertEqual(episode.state(self.home, key)["active_episode_id"], identifier)
            self.assertEqual(len(episode.state(self.home, key)["buffer"]), 1)
            self.assertFalse(any(task["kind"] == "knowledge" for task in runtime.tasks()))
            return
        self.assertEqual(completed["status"], "succeeded", completed["error"])
        current = episode.state(self.home, key)
        self.assertEqual((current["processed_line"], current["material_updates"], current["buffer"], current["active_episode_id"]), (4 if buffered else 2, 2, [], None))
        downstream = [task for task in runtime.tasks() if task["kind"] == "knowledge"]
        self.assertEqual(len(downstream), 1)
        self.assertEqual(len(downstream[0]["inputs"]["episode_refs"]), 2 if independent else 1)

    def test_short_closing_buffer_can_remain_with_old_episode(self):
        self.close_buffer(False)

    def test_short_independent_exchange_closes_separately_without_full_window(self):
        self.close_buffer(True)

    def test_new_request_during_closing_prevents_old_result_publication(self):
        self.close_buffer(False, new_start=True)

    def test_late_material_during_closing_stays_unclassified_and_blocks_publication(self):
        self.close_buffer(False, late_material=True)

    def test_closing_without_pending_buffer_keeps_material_count_and_needs_no_new_score(self):
        self.close_buffer(False, buffered=False)


if __name__ == "__main__":
    unittest.main()
