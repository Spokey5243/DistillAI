"""Transactional control state preserves identities, budgets and failure atomicity."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import multiprocessing
import sqlite3
import tempfile
import threading
import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
