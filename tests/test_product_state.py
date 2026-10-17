"""Transactional control state preserves identities, budgets and failure atomicity."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import json
import multiprocessing
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from distillai.config import Config
from distillai.runtime import BudgetError, Runtime
from distillai.storage import Store
from distillai.server import create_app


def hold_store_lock(home, ready):
    with Store(home).locked():
        ready.send_bytes(b"locked")
        ready.close()
        time.sleep(15)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.home = Path(self.temp) / "data"
        self.store = Store(self.home)
        self.config = Config(self.store)
        self.runtime = Runtime(self.store, self.config, lambda task, control: {}, lambda task, result: None)
        self.addCleanup(self.runtime.close)

    def test_invalid_task_write_preserves_the_previous_record_and_budget(self):
        task = self.runtime.register("query", {}, "strict-task-write")
        for changed in ({"model_calls": True}, {"started": "false"}, {"extra": "ignored"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.store.save_task({**task, **changed})
            self.assertEqual(self.runtime.task(task["id"]), task)

    def test_damaged_task_and_attempt_records_are_not_adopted(self):
        task = self.runtime.register("query", {}, "strict-task-read")
        with self.store.state.transaction() as connection:
            original = connection.execute("SELECT record FROM tasks WHERE id=?", (task["id"],)).fetchone()[0]
        for changed in ({"authorized": 1}, {"post_registered": "false"}, {"extra": "ignored"}, [], None):
            damaged = json.dumps({**json.loads(original), **changed} if isinstance(changed, dict) else changed)
            try:
                with self.store.state.transaction() as connection:
                    connection.execute("UPDATE tasks SET record=? WHERE id=?", (damaged, task["id"]))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    self.runtime.task(task["id"])
                with self.store.state.transaction(write=False) as connection:
                    self.assertEqual(connection.execute("SELECT record FROM tasks WHERE id=?", (task["id"],)).fetchone()[0], damaged)
            finally:
                with self.store.state.transaction() as connection:
                    connection.execute("UPDATE tasks SET record=? WHERE id=?", (original, task["id"]))
        with self.store.state.transaction() as connection:
            connection.execute("INSERT INTO attempts VALUES(?,?,?)", (task["id"], "a" * 32, '{"state":"unknown","request_version":null}'))
        try:
            with self.assertRaises(ValueError):
                self.runtime.tasks()
        finally:
            with self.store.state.transaction() as connection:
                connection.execute("DELETE FROM attempts WHERE task_id=?", (task["id"],))
        self.assertEqual(self.runtime.task(task["id"]), task)

    def test_registration_and_dependencies_are_atomic_and_deduplicated(self):
        def register(_):
            store = Store(self.home)
            runtime = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
            return runtime.register("query", {}, "same-input")["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(register, range(2)))
        self.assertEqual(len(set(identifiers)), 1)
        original = self.runtime.task(identifiers[0])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.state.transaction() as connection:
                self.store.state.save_task({**original, "id": "e" * 32}, connection=connection)
        self.assertEqual([task["id"] for task in self.runtime.tasks()], [original["id"]])

    def test_concurrent_first_start_never_exposes_an_incomplete_database(self):
        first_home = Path(self.temp) / "first-start"
        with ThreadPoolExecutor(max_workers=2) as pool:
            versions = list(pool.map(lambda _: Config(Store(first_home)).read()["version"], range(2)))
        self.assertEqual(versions, [1, 1])

    def test_first_start_accepts_existing_capture_and_launch_configuration(self):
        home = Path(self.temp) / "captured-before-first-start"
        (home / "config").mkdir(parents=True)
        (home / "config/launch.json").write_text('{}', encoding="utf-8")
        queue = home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic first capture"}\n', encoding="utf-8")
        self.assertEqual(Config(Store(home)).read()["version"], 1)
        self.assertIn("synthetic first capture", queue.read_text(encoding="utf-8"))

    def test_repeated_dependency_is_one_edge_without_quarantining_the_database(self):
        parent = self.runtime.register("query", {}, "dependency-parent")
        child = self.runtime.register("query", {}, "dependency-child", dependencies=[parent["id"], parent["id"]])
        self.assertEqual(child["dependencies"], [parent["id"]])
        self.assertEqual(self.runtime.task(child["id"])["dependencies"], [parent["id"]])
        self.assertEqual(self.runtime.register("query", {}, "dependency-child", dependencies=[parent["id"]])["id"], child["id"])
        self.assertFalse(self.store.state.failed)

    def test_nested_lock_excludes_other_threads_and_releases_after_an_exception(self):
        waiting, acquired = threading.Event(), threading.Event()
        errors = []
        def contender():
            waiting.set()
            try:
                with self.store.locked():
                    acquired.set()
            except Exception as error:
                errors.append(type(error).__name__)
        thread = threading.Thread(target=contender)
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic abort"), self.store.locked():
                with self.store.locked():
                    thread.start()
                    self.assertTrue(waiting.wait(2))
                    self.assertFalse(acquired.wait(.1))
                    raise RuntimeError("synthetic abort")
            self.assertTrue(acquired.wait(2))
        finally:
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_process_death_releases_the_store_file_lock(self):
        import portalocker
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        child = context.Process(target=hold_store_lock, args=(self.home, sender))
        try:
            child.start()
            sender.close()
            self.assertTrue(receiver.poll(5))
            self.assertEqual(receiver.recv_bytes(32), b"locked")
            with self.assertRaises(portalocker.LockException):
                with portalocker.Lock(self.home / ".lock", mode="a+b", timeout=0):
                    self.fail("Lock held by another process was acquired")
            child.terminate()
            child.join(3)
            self.assertFalse(child.is_alive())
            with self.store.locked():
                self.assertEqual(self.config.read()["version"], 1)
        finally:
            if child.is_alive():
                child.terminate()
                child.join(3)
            receiver.close()
            sender.close()
            child.close()

    def test_last_generation_is_reserved_once_across_connections(self):
        self.config.update(1, {"runtime": {"max_model_calls": 1}})
        task = self.runtime.register("query", {}, "budget")
        task["status"] = "running"
        self.runtime._save(task)
        def reserve(index):
            store = Store(self.home)
            runtime = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
            try:
                runtime.reserve_generation(task["id"], attempt_id=str(index + 1) * 32)
                return True
            except BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reserve, range(2))), [False, True])
        saved = Store(self.home).read_task(task["id"])
        self.assertEqual(saved["model_calls"], 1)
        self.assertEqual(len(saved["generation_attempts"]), 1)

    def test_duplicate_attempt_and_transaction_rollback_do_not_change_budget(self):
        task = self.runtime.register("query", {}, "rollback")
        task["status"] = "running"
        self.runtime._save(task)
        self.runtime.reserve_generation(task["id"], attempt_id="a" * 32)
        with self.assertRaises(ValueError):
            self.runtime.reserve_generation(task["id"], attempt_id="a" * 32)
        with self.assertRaises(RuntimeError):
            with self.store.state.transaction() as connection:
                self.store.state.save_task({**self.runtime.task(task["id"]), "model_calls": 9}, connection=connection)
                raise RuntimeError("abort before commit")
        self.assertEqual(self.runtime.task(task["id"])["model_calls"], 1)

    def test_unknown_newer_database_is_rejected_without_modification(self):
        with closing(sqlite3.connect(self.home / "state.sqlite3")) as connection:
            connection.execute("PRAGMA user_version=999")
        with self.assertRaises(ValueError):
            Store(self.home)
        with closing(sqlite3.connect(self.home / "state.sqlite3")) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 999)

    def test_old_control_files_require_explicit_migration(self):
        old = Path(self.temp) / "legacy"
        (old / "tasks").mkdir(parents=True)
        (old / "tasks" / ("b" * 32 + ".json")).write_text('{}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "migrat"):
            Store(old)
        self.assertFalse((old / "state.sqlite3").exists())

    def test_connection_failure_quarantines_the_live_root_until_restart(self):
        task = self.runtime.register("query", {}, "connection-failure")
        database = self.home / "state.sqlite3"
        unavailable = self.home / "state.sqlite3.offline"
        database.rename(unavailable)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.config.read()
            self.assertTrue(self.store.state.failed)
            self.assertFalse(database.exists(), "A failed read must not create an empty replacement database")
            with self.assertRaisesRegex(ValueError, "database.*missing"):
                Store(self.home)
            self.assertFalse(database.exists())
        finally:
            if database.exists():
                database.unlink()  # Only a replacement produced by the failing implementation in this temporary fixture.
            unavailable.rename(database)
        self.runtime.dispatch()
        self.assertEqual(self.runtime.task(task["id"])["status"], "queued")
        app = create_app(self.runtime)
        with TestClient(app, base_url=app.state.control.url) as client:
            headers = {"Authorization": "Bearer " + app.state.control.token}
            self.assertEqual(client.get("/v1/config", headers=headers).status_code, 503)
            self.assertFalse(client.get("/v1/health", headers=headers).json()["ready"])
        restarted = Store(self.home)
        self.assertFalse(restarted.state.failed)
        self.assertEqual(Config(restarted).read()["version"], 1)

    def test_failed_config_pointer_write_keeps_the_old_version_and_does_not_reuse_orphan_bytes(self):
        with closing(sqlite3.connect(self.store.state.path, isolation_level=None)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            with self.assertRaises(sqlite3.OperationalError):
                self.config.update(1, {"llm": {"model": "synthetic orphan"}})
            self.assertTrue(self.store.state.failed)
            self.assertEqual(self.config.read()["version"], 1)
            blocker.execute("ROLLBACK")
        orphan = self.home / "config/2.json"
        original_bytes = orphan.read_bytes()
        restarted = Config(Store(self.home))
        self.assertEqual(restarted.read()["version"], 1)
        self.assertEqual(restarted.read()["values"]["llm"]["model"], "")
        updated = restarted.update(1, {"llm": {"model": "synthetic current"}})
        self.assertGreater(updated["version"], 2)
        self.assertEqual(orphan.read_bytes(), original_bytes)

    def test_busy_database_refuses_generation_and_still_stops_its_tree(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        sent = []
        class Job:
            def close(self):
                stopped.set()
        def execute(task, runtime):
            runtime.attach_job(task["id"], Job())
            entered.set()
            release.wait(2)
            runtime.reserve_generation(task["id"])
            sent.append(True)
            return {}
        self.runtime.execute = execute
        task = self.runtime.register("query", {}, "database-busy")
        self.runtime.dispatch()
        self.assertTrue(entered.wait(2))
        with closing(sqlite3.connect(self.home / "state.sqlite3", isolation_level=None)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            release.set()
            self.assertTrue(stopped.wait(7))
            self.runtime.close()
            self.assertFalse(self.runtime._active)
            self.assertEqual(sent, [])
            app = create_app(self.runtime)
            with TestClient(app, base_url=app.state.control.url) as client:
                headers = {"Authorization": "Bearer " + app.state.control.token}
                self.assertEqual(client.get("/v1/config", headers=headers).status_code, 503)
                self.assertEqual(client.get("/v1/health", headers=headers).status_code, 200)
            blocker.execute("ROLLBACK")
        restarted = Runtime(Store(self.home), Config(Store(self.home)), lambda task, control: {}, lambda task, result: None)
        restarted.recover_tasks()
        self.assertEqual(restarted.task(task["id"])["model_calls"], 0)
        self.assertEqual(restarted.task(task["id"])["status"], "failed")

    def test_live_database_write_failure_recovers_partial_and_all_written_files_without_reexecution(self):
        for written_count in (1, 2):
            with self.subTest(written_files=written_count):
                root = Path(self.temp) / ("publication-" + str(written_count))
                source = root / "source"
                source.mkdir(parents=True)
                for name in ("a", "b"):
                    (source / (name + ".txt")).write_bytes(("old-" + name).encode())
                store = Store(root / "data")
                config = Config(store)
                config.update(1, {"workspace": {"paths": [str(source)]}})
                locked, unavailable, stopped = threading.Event(), threading.Event(), threading.Event()
                calls, snapshots, successors = [], [], []
                class Job:
                    def close(self):
                        stopped.set()
                def execute(task, control):
                    control.attach_job(task["id"], Job())
                    control.reserve_generation(task["id"])
                    calls.append(task["id"])
                    for name in ("a", "b"):
                        (Path(task["workspace"]) / (name + ".txt")).write_bytes(("new-" + name).encode())
                    return {"result": "synthetic publication"}
                runtime = Runtime(store, config, execute, lambda task, result: None,
                    after_commit=lambda task: successors.append(task["id"]))
                task = runtime.register("knowledge", {}, "live-sql-failure", scope={"root": str(source)})
                original = store._save_commit
                with closing(sqlite3.connect(store.state.path, isolation_level=None, check_same_thread=False)) as blocker:
                    def save(record):
                        try:
                            original(record)
                        except sqlite3.Error:
                            unavailable.set()
                            raise
                        if record["status"] == "prepared" and not locked.is_set() and sum(
                                item["kind"] == "file" and item["state"] == "applied" for item in record["items"]) == written_count:
                            blocker.execute("BEGIN IMMEDIATE")
                            snapshots.append([(source / (name + ".txt")).read_bytes() for name in ("a", "b")])
                            locked.set()
                    try:
                        with patch.object(store, "_save_commit", side_effect=save):
                            runtime.dispatch()
                            self.assertTrue(locked.wait(3))
                            self.assertEqual(snapshots, [[b"new-a", b"new-b" if written_count == 2 else b"old-b"]])
                            self.assertTrue(unavailable.wait(7), "The real SQLite writer did not time out")
                            self.assertTrue(store.state.failed)
                            app = create_app(runtime)
                            with TestClient(app, base_url=app.state.control.url) as client:
                                headers = {"Authorization": "Bearer " + app.state.control.token}
                                for path in ("/v1/config", "/v1/history", "/v1/knowledge"):
                                    self.assertEqual(client.get(path, headers=headers).status_code, 503)
                                health = client.get("/v1/health", headers=headers)
                                self.assertEqual(health.status_code, 200)
                                self.assertFalse(health.json()["ready"])
                            runtime.close()
                            self.assertTrue(stopped.is_set())
                            self.assertTrue(blocker.in_transaction, "Cleanup depended on the database becoming writable")
                            self.assertNotEqual(runtime.wait(task["id"])["status"], "succeeded")
                    finally:
                        if blocker.in_transaction:
                            blocker.execute("ROLLBACK")
                        runtime.close()
                restarted_store = Store(store.home)
                restarted = Runtime(restarted_store, Config(restarted_store), execute, lambda task, result: None,
                    after_commit=lambda task: successors.append(task["id"]))
                try:
                    restarted.recover_tasks()
                    saved = restarted.task(task["id"])
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["model_calls"], 1)
                    commit = restarted_store.read_commit(saved["commit_id"])
                    self.assertEqual(commit["status"], "rolled_back")
                    for name in ("a", "b"):
                        self.assertEqual((source / (name + ".txt")).read_bytes(), ("old-" + name).encode())
                        item = next(item for item in commit["items"] if item["path"] == name + ".txt")
                        self.assertEqual(restarted_store.read_version(item["after"]), ("new-" + name).encode())
                    self.assertEqual(calls, [task["id"]])
                    self.assertEqual(successors, [])
                    restarted.recover_tasks()
                    self.assertEqual(restarted.task(task["id"])["model_calls"], 1)
                finally:
                    restarted.close()


if __name__ == "__main__":
    unittest.main()
