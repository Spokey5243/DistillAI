"""Durable tasks must obey fixed inputs, budget, scheduling and commit ordering."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from distillai.config import Config
from distillai.runtime import CancelledError, Runtime
from distillai.storage import ConflictError, Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.config = Config(self.store)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.config.update(1, {"workspace": {"paths": [str(self.workspace)]}})
        self.runtimes = []
        self.addCleanup(self.close_runtimes)

    def close_runtimes(self):
        for runtime in self.runtimes:
            runtime.close()

    def runtime(self, execute, *, after_commit=None):
        runtime = Runtime(self.store, self.config, execute, lambda task, result: None,
                          after_commit=after_commit)
        self.runtimes.append(runtime)
        return runtime

    def submit(self, runtime, kind="knowledge", inputs=None, scope=None, trigger="synthetic"):
        return runtime.register(kind, inputs or {}, trigger, scope=scope)

    def test_same_registration_is_reused_and_new_input_is_distinct(self):
        runtime = self.runtime(lambda task, control: {})
        first = self.submit(runtime, inputs={"version": "one"})
        self.assertEqual(self.submit(runtime, inputs={"version": "one"})["id"], first["id"])
        self.assertNotEqual(self.submit(runtime, inputs={"version": "two"})["id"], first["id"])
        runtime.dispatch()
        self.assertEqual(runtime.wait(first["id"])["status"], "succeeded")

    def test_sixteenth_call_can_complete_and_restart_does_not_reset_budget(self):
        sent = []

        def execute(task, control):
            for _ in range(task["inputs"].get("calls", 16)):
                control.reserve_generation(task["id"])
                sent.append("sent")
            return {"answer": "complete"}

        runtime = self.runtime(execute)
        task = self.submit(runtime)
        runtime.dispatch()
        result = runtime.wait(task["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["model_calls"], 16)
        self.assertEqual(len(sent), 16)
        restarted = self.runtime(execute)
        with self.assertRaises(ConflictError):
            restarted.retry(task["id"])
        self.assertEqual(len(sent), 16)
        self.assertEqual(restarted.task(task["id"])["model_calls"], 16)

    def test_seventeenth_call_is_rejected_before_send(self):
        sent = []

        def execute(task, control):
            for _ in range(17):
                control.reserve_generation(task["id"])
                sent.append(1)
            self.fail("Seventeenth generation was allowed")

        runtime = self.runtime(execute)
        task = self.submit(runtime)
        runtime.dispatch()
        result = runtime.wait(task["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "BudgetError")
        self.assertEqual(len(sent), 16)
        restarted = self.runtime(execute)
        restarted.retry(task["id"])
        restarted.dispatch()
        self.assertEqual(restarted.wait(task["id"])["status"], "failed")
        self.assertEqual(len(sent), 16)

    def test_query_waits_for_ordinary_slot_while_screening_runs_independently(self):
        started = []
        busy = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def execute(task, control):
            started.append(task["kind"])
            if task["inputs"].get("hold"):
                busy.set()
                self.assertTrue(release.wait(5))
            return {}

        runtime = self.runtime(execute)
        first = self.submit(runtime, inputs={"hold": True})
        runtime.dispatch()
        self.assertTrue(busy.wait(5))
        normal = self.submit(runtime, trigger="next")
        query = self.submit(runtime, kind="query")
        screening = self.submit(runtime, kind="screening")
        runtime.dispatch()
        self.assertEqual(runtime.wait(screening["id"])["status"], "succeeded")
        self.assertEqual(runtime.task(query["id"])["status"], "queued")
        release.set()
        runtime.wait(first["id"])
        runtime.dispatch()
        runtime.wait(query["id"])
        self.assertEqual(started, ["knowledge", "screening", "query"])
        runtime.dispatch()
        self.assertEqual(runtime.wait(normal["id"])["status"], "succeeded")

    def test_cancel_queued_never_starts_executor(self):
        started = []
        runtime = self.runtime(lambda task, control: started.append(task["id"]))
        task = self.submit(runtime)
        runtime.cancel(task["id"], "user")
        runtime.dispatch()
        self.assertEqual(runtime.task(task["id"])["status"], "cancelled")
        self.assertEqual(started, [])

    def test_revoking_workspace_cancels_before_publication_and_keeps_slot_until_stop(self):
        began, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        (self.workspace / "a.txt").write_bytes(b"original")

        def execute(task, control):
            (Path(task["workspace"]) / "a.txt").write_bytes(b"agent")
            began.set()
            self.assertTrue(release.wait(5))
            return {}

        runtime = self.runtime(execute)
        task = self.submit(runtime, scope={"root": str(self.workspace)})
        runtime.dispatch()
        self.assertTrue(began.wait(5))
        runtime.update_config(self.config.read()["version"], {"workspace": {"paths": []}})
        self.assertEqual(runtime.task(task["id"])["status"], "recovering")
        next_task = self.submit(runtime, trigger="next")
        runtime.dispatch()
        self.assertEqual(runtime.task(next_task["id"])["status"], "queued")
        release.set()
        self.assertEqual(runtime.wait(task["id"])["status"], "cancelled")
        self.assertEqual((self.workspace / "a.txt").read_bytes(), b"original")
        runtime.cancel(next_task["id"], "cleanup")

    def test_committed_post_registration_is_recovered_without_rerunning_model(self):
        calls, registrations = [], []
        (self.workspace / "a.txt").write_bytes(b"original")

        def execute(task, control):
            calls.append(task["id"])
            (Path(task["workspace"]) / "a.txt").write_bytes(b"agent")
            return {"records": ["a"]}

        def register(task):
            self.assertEqual(self.store.read_commit(task["commit_id"])["status"], "committed")
            registrations.append(task["id"])
            if len(registrations) == 1:
                raise OSError("synthetic post-registration outage")

        runtime = self.runtime(execute, after_commit=register)
        task = self.submit(runtime, scope={"root": str(self.workspace)})
        runtime.dispatch()
        record = runtime.wait(task["id"])
        self.assertEqual(record["status"], "validating")
        self.assertFalse(record["post_registered"])
        restarted = self.runtime(execute, after_commit=register)
        restarted.recover_tasks()
        self.assertEqual(restarted.task(task["id"])["status"], "succeeded")
        self.assertTrue(restarted.task(task["id"])["post_registered"])
        self.assertEqual(calls, [task["id"]])
        self.assertEqual((self.workspace / "a.txt").read_bytes(), b"agent")

    def test_stale_episode_analysis_cannot_publish(self):
        episode_id = uuid.uuid4().hex
        folder = self.store.home / "episodes"
        folder.mkdir()
        episode = folder / f"{episode_id}.json"
        episode.write_bytes(b'{"revision":1}')
        version = self.store.put_version(episode.read_bytes())
        (self.workspace / "a.txt").write_bytes(b"original")

        def execute(task, control):
            (Path(task["workspace"]) / "a.txt").write_bytes(b"agent")
            episode.write_bytes(b'{"revision":2}')
            return {}

        for kind in ("knowledge", "cognition"):
            with self.subTest(kind=kind):
                episode.write_bytes(b'{"revision":1}')
                runtime = self.runtime(execute)
                task = self.submit(runtime, kind=kind, inputs={"episode_refs": [{"id": episode_id, "version": version}]},
                                   scope={"root": str(self.workspace)})
                runtime.dispatch()
                self.assertEqual(runtime.wait(task["id"])["status"], "cancelled")
                self.assertEqual((self.workspace / "a.txt").read_bytes(), b"original")

    def test_invalid_input_fails_without_blocking_other_queued_tasks(self):
        runtime = Runtime(self.store, self.config, lambda task, control: {},
                          lambda task, result: (_ for _ in ()).throw(ValueError("invalid input"))
                          if task["inputs"].get("invalid") else None)
        self.runtimes.append(runtime)
        bad = self.submit(runtime, inputs={"invalid": True})
        good = self.submit(runtime)
        runtime.dispatch()
        self.assertEqual(runtime.task(bad["id"])["status"], "failed")
        self.assertEqual(runtime.wait(good["id"])["status"], "succeeded")

    def test_completed_executor_cannot_reserve_another_generation(self):
        def execute(task, control):
            control.reserve_generation(task["id"])
            return {}

        runtime = self.runtime(execute)
        task = self.submit(runtime)
        runtime.dispatch()
        self.assertEqual(runtime.wait(task["id"])["model_calls"], 1)
        with self.assertRaises(CancelledError):
            runtime.reserve_generation(task["id"])

    def test_recovery_conflict_blocks_overlapping_writes_but_allows_read_only_query(self):
        started = []
        runtime = self.runtime(lambda task, control: started.append(task["id"]) or {})
        old = self.submit(runtime, scope={"root": str(self.workspace)}, trigger="old")
        old["status"] = "recovery_conflict"
        self.store.save_task(old)
        write = self.submit(runtime, scope={"root": str(self.workspace)}, trigger="new")
        query = self.submit(runtime, kind="query")
        runtime.dispatch()
        runtime.wait(query["id"])
        runtime.dispatch()
        self.assertEqual(runtime.task(write["id"])["status"], "queued")
        self.assertEqual(started, [query["id"]])

    def test_fixed_episode_file_is_protected_through_publication_window(self):
        episode_id = uuid.uuid4().hex
        folder = self.store.home / "episodes"
        folder.mkdir()
        episode = folder / (episode_id + ".json")
        episode.write_bytes(b'{"revision":1}')
        version = self.store.put_version(episode.read_bytes())
        (self.workspace / "a.txt").write_bytes(b"original")
        attempts = []
        original_publish = self.store.publish

        def publish(commit_id, validate):
            checks = 0

            def checked():
                nonlocal checks
                validate()
                checks += 1
                if checks == 2:
                    try:
                        episode.write_bytes(b'{"revision":2}')
                    except OSError:
                        attempts.append("blocked")
                    else:
                        attempts.append("changed")

            return original_publish(commit_id, checked)

        def execute(task, control):
            (Path(task["workspace"]) / "a.txt").write_bytes(b"agent")
            return {}

        runtime = self.runtime(execute)
        task = self.submit(runtime, inputs={"episode_refs": [{"id": episode_id, "version": version}]},
                           scope={"root": str(self.workspace)})
        from unittest.mock import patch
        with patch.object(self.store, "publish", side_effect=publish):
            runtime.dispatch()
            self.assertEqual(runtime.wait(task["id"])["status"], "succeeded")
        self.assertEqual(attempts, ["blocked"])

    def test_scope_dot_segments_cannot_escape_authorized_workspace(self):
        runtime = self.runtime(lambda task, control: {})
        with self.assertRaises((CancelledError, ValueError)):
            self.submit(runtime, scope={"root": str(self.workspace / ".." / "data")})

    def test_only_unstarted_contiguous_session_increment_can_merge(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def execute(task, control):
            entered.set()
            self.assertTrue(release.wait(5))
            return {}

        runtime = self.runtime(execute)
        source = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 2}
        first = runtime.register_increment(source)
        old_input = first["input_version"]
        merged = runtime.register_increment({**source, "line_start": 3, "line_end": 4})
        self.assertEqual(merged["id"], first["id"])
        self.assertEqual(merged["inputs"]["source_refs"][0]["line_end"], 4)
        self.assertEqual(json.loads(self.store.read_version(old_input))["source_refs"][0]["line_end"], 2)
        self.assertEqual(runtime.register("episode", {"source_refs": [source]}, "material")["id"], first["id"])
        runtime.dispatch()
        self.assertTrue(entered.wait(3))
        following = runtime.register_increment({**source, "line_start": 5, "line_end": 6})
        self.assertNotEqual(following["id"], first["id"])
        self.assertEqual(runtime.task(first["id"])["inputs"]["source_refs"][0]["line_end"], 4)
        gap = runtime.register_increment({**source, "line_start": 9, "line_end": 10})
        self.assertNotEqual(gap["id"], following["id"])
        other = runtime.register_increment({**source, "session_key": "different"})
        self.assertNotEqual(other["id"], first["id"])
        release.set()
        runtime.wait(first["id"])


if __name__ == "__main__":
    unittest.main()
