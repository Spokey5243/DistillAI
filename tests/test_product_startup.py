"""Multiple native entrypoints share one verified service and recover after stop."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from distillai.startup import live_instance, start_background, stop_background, load_launch, service_lifespan
from distillai.storage import atomic_json, Store
from distillai.windows import ProcessJob, resume_process


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "data"
        self.addCleanup(lambda: stop_background(self.home))
        source = str(Path(__file__).resolve().parents[1] / "src")
        code = (f"import sys;sys.path.insert(0,{source!r});"
                "from distillai.storage import Store;from distillai.config import Config;"
                "from distillai.runtime import Runtime;from distillai.startup import run_service;"
                f"s=Store({str(self.home)!r});run_service(Runtime(s,Config(s),lambda task,control: {{}},lambda task,result: None))")
        self.command = [sys.executable, "-I", "-c", code]
        # Fixtures are runner-owned; real detachment refusals run in separate, unpatched processes below.
        self.enterContext(patch("distillai.startup.resume_process", side_effect=lambda pid, **options: resume_process(pid)))

    def test_launch_uses_cli_then_declared_environment_then_saved_values(self):
        (self.home / "config").mkdir(parents=True)
        atomic_json(self.home / "config/launch.json", {"hermes_source": "saved-source", "hermes_python": "saved-python", "base_python": "old-runtime-detail"})
        with patch.dict(os.environ, {"DISTILLAI_HERMES_SOURCE": "env-source", "DISTILLAI_HERMES_PYTHON": "env-python"}):
            launch = load_launch(self.home, hermes_source="cli-source")
            self.assertEqual((launch.hermes_source, launch.hermes_python), ("cli-source", "env-python"))
        with patch.dict(os.environ, {}, clear=True):
            launch = load_launch(self.home)
            self.assertEqual((launch.hermes_source, launch.hermes_python), ("saved-source", "saved-python"))

    def test_concurrent_entrypoints_reuse_one_instance_then_stop_and_restart(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start_background(self.home, self.command), range(2)))
        self.assertEqual(results[0]["instance_id"], results[1]["instance_id"])
        self.assertEqual(results[0]["pid"], results[1]["pid"])
        self.assertTrue(stop_background(self.home))
        self.assertIsNone(live_instance(self.home))
        restarted = start_background(self.home, self.command)
        self.assertNotEqual(restarted["instance_id"], results[0]["instance_id"])

    def test_pid_or_instance_identity_mismatch_is_not_reused(self):
        original = start_background(self.home, self.command)
        path = self.home / "instance.json"
        saved = json.loads(path.read_text(encoding="utf-8"))
        try:
            for field, value in (("pid", original["pid"] + 1), ("instance_id", "0" * 32), ("protocol", 999)):
                with self.subTest(field=field):
                    atomic_json(path, {**saved, field: value})
                    self.assertIsNone(live_instance(self.home))
        finally:
            atomic_json(path, saved)

    def test_client_that_forbids_detached_children_cannot_claim_a_resident_start(self):
        source = str(Path(__file__).resolve().parents[1] / "src")
        code = (f"import sys,json;sys.path.insert(0,{source!r});from distillai.startup import start_background;"
                "sys.stdin.readline();\n"
                f"try:start_background({str(self.home)!r},{self.command!r})\n"
                "except RuntimeError as error:print(json.dumps({'error':str(error)}))\n"
                "else:print(json.dumps({'started':True}))")
        with ProcessJob() as job:
            child = subprocess.Popen([sys._base_executable, "-I", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env={**os.environ, "__PYVENV_LAUNCHER__": sys.executable},
                                     creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
            job.assign(child.pid)
            job.resume(child.pid)
            stdout, stderr = child.communicate(b"start\n", timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("independent backend", json.loads(stdout).get("error", ""))
        self.assertIsNone(live_instance(self.home))

    def test_launcher_nested_job_cannot_leave_a_backend_owned_by_the_client(self):
        source = str(Path(__file__).resolve().parents[1] / "src")
        code = (f"import sys,json;sys.path.insert(0,{source!r});from distillai.startup import start_background;"
                "sys.stdin.readline();\n"
                f"try:start_background({str(self.home)!r},{self.command!r})\n"
                "except RuntimeError as error:print(json.dumps({'error':str(error)}))\n"
                "else:print(json.dumps({'started':True}))")
        with ProcessJob() as job:
            child = subprocess.Popen([sys.executable, "-I", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
            job.assign(child.pid)
            job.resume(child.pid)
            stdout, stderr = child.communicate(b"start\n", timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("independent backend", json.loads(stdout).get("error", ""))
        self.assertIsNone(live_instance(self.home))
        self.assertFalse((self.home / "state.sqlite3").exists(), "A refused resident start must not run the backend")

    def test_polling_discovers_complete_material_without_a_notification(self):
        start_background(self.home, self.command)
        queue = self.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_bytes(b'{"role":"user","text":"synthetic material"}\n{"partial":')
        deadline = time.monotonic() + 5
        tasks = []
        while time.monotonic() < deadline:
            tasks = Store(self.home).state.tasks()
            if tasks:
                break
            time.sleep(.05)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["inputs"]["source_refs"], [{"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}])


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_drains_an_independent_scheduled_job_before_returning(self):
        from datetime import datetime, timedelta, timezone
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from distillai.config import Config
        from distillai.runtime import Runtime
        from distillai.diagnostics import diagnostic_sink

        class ReadyExplorer(AsyncIOScheduler):
            def start(self, *args, **kwargs):
                self.modify_job("scan", next_run_time=datetime.now(timezone.utc) + timedelta(hours=1))
                self.modify_job("expansion", next_run_time=datetime.now(timezone.utc))
                super().start(*args, **kwargs)

        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        stop = asyncio.Event()
        def explore(runtime):
            entered.set()
            release.wait(3)
            finished.set()
            raise ValueError("PRIVATE_SCHEDULED_BODY")

        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            runtime = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
            control = SimpleNamespace(stopping=threading.Event(), instance_id="a" * 32,
                url="http://127.0.0.1:8000", token="synthetic-only", server=SimpleNamespace(started=True, should_exit=False))
            async def host():
                async with service_lifespan(runtime, control):
                    await stop.wait()
            with diagnostic_sink(temporary, "backend"), self.assertNoLogs(level="ERROR"), \
                    patch("distillai.startup.AsyncIOScheduler", ReadyExplorer), patch("distillai.expansion.tick", explore):
                serving = asyncio.create_task(host())
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    stop.set()
                    await asyncio.sleep(.1)
                    self.assertFalse(serving.done(), "Shutdown returned while a scheduled write was still running")
                    release.set()
                    await asyncio.wait_for(serving, 2)
                    self.assertTrue(finished.is_set())
                finally:
                    stop.set()
                    release.set()
                    await asyncio.wait_for(serving, 3)
                    runtime.close()
            logs = "".join(path.read_text(encoding="utf-8") for path in (Path(temporary) / "logs").glob("*.jsonl"))
            self.assertNotIn("PRIVATE_SCHEDULED_BODY", logs)
            self.assertTrue(any(json.loads(line)["record"]["extra"].get("error_code") == "ValueError"
                for line in logs.splitlines()))

    async def test_late_deadline_runs_once_and_a_new_request_invalidates_the_old_deadline(self):
        from apscheduler.events import EVENT_JOB_EXECUTED
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from distillai import lifecycle
        from distillai.config import Config
        from distillai.runtime import Runtime

        for new_request in (False, True):
            with self.subTest(new_request=new_request), tempfile.TemporaryDirectory() as temporary:
                store = Store(temporary)
                config = Config(store)
                config.update(1, {"runtime": {"poll_interval_seconds": 3600}})
                runtime = Runtime(store, config, lambda task, control: {}, lambda task, result: None)
                queue = store.home / "codex/queue/synthetic.jsonl"
                queue.parent.mkdir(parents=True)
                queue.write_text('{"role":"user","text":"synthetic request"}\n', encoding="utf-8")
                (store.home / "buffers").mkdir()
                atomic_json(store.home / "buffers/synthetic.json", {"connector": "codex", "session_key": "synthetic",
                    "active_episode_id": "b" * 32, "buffer": [], "processed_line": 1, "material_updates": 1})
                deadline = datetime.now(timezone.utc) + timedelta(seconds=2)
                stopped_at = deadline - timedelta(minutes=30)
                lifecycle.observe(runtime, "synthetic", "request_started", observed_at=(stopped_at - timedelta(seconds=1)).isoformat())
                lifecycle.observe(runtime, "synthetic", "response_stopped", observed_at=stopped_at.isoformat())
                scanned = asyncio.Event()
                loop = asyncio.get_running_loop()

                def scheduler(**kwargs):
                    instance = AsyncIOScheduler(**kwargs)
                    instance.add_listener(lambda event: loop.call_soon_threadsafe(scanned.set), EVENT_JOB_EXECUTED)
                    return instance

                control = SimpleNamespace(stopping=threading.Event(), instance_id="a" * 32,
                    url="http://127.0.0.1:8000", token="synthetic-only", server=SimpleNamespace(started=True, should_exit=False))
                timer = None
                with patch("distillai.startup.AsyncIOScheduler", side_effect=scheduler):
                    async with service_lifespan(runtime, control, material_register=lambda ref: None):
                        try:
                            await asyncio.wait_for(scanned.wait(), 2)
                            self.assertEqual(runtime.tasks(), [])
                            if new_request:
                                timer = threading.Timer(.2, lambda: lifecycle.observe(runtime, "synthetic", "request_started"))
                                timer.start()
                            # Simulate an in-process pause beyond the scheduler's default misfire grace.
                            time.sleep(4)
                            until = time.monotonic() + 2
                            while time.monotonic() < until:
                                if runtime.tasks() or new_request and lifecycle.read(runtime, "synthetic")["kind"] == "request_started":
                                    break
                                await asyncio.sleep(.02)
                            await asyncio.sleep(.1)
                            tasks = runtime.tasks()
                            self.assertEqual(len(tasks), 0 if new_request else 1)
                            if tasks:
                                self.assertEqual((tasks[0]["trigger"], tasks[0]["model_calls"]), ("closing", 0))
                                self.assertEqual(tasks[0]["inputs"]["closing"]["observed_at"], stopped_at.isoformat().replace("+00:00", "Z"))
                        finally:
                            if timer is not None:
                                timer.cancel()
                                timer.join(2)

    async def test_task_wakeup_during_busy_scan_is_not_delayed_until_the_periodic_interval(self):
        from distillai.config import Config
        from distillai.runtime import Runtime

        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            config = Config(store)
            config.update(1, {"runtime": {"poll_interval_seconds": 3600},
                "llm": {"model": "synthetic", "base_url": "https://model.test/v1"}})
            executed = threading.Event()
            runtime = Runtime(store, config, lambda task, control: executed.set() or {}, lambda task, result: None)
            entered, release = threading.Event(), threading.Event()
            dispatch = runtime.dispatch

            def busy_dispatch():
                dispatch()
                if not entered.is_set():
                    entered.set()
                    release.wait(3)

            control = SimpleNamespace(stopping=threading.Event(), instance_id="a" * 32,
                url="http://127.0.0.1:8000", token="synthetic-only", server=SimpleNamespace(started=True, should_exit=False))
            with patch.object(runtime, "dispatch", busy_dispatch):
                async with service_lifespan(runtime, control):
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                        task = runtime.register("query", {}, "synthetic busy-scan wakeup")
                        await asyncio.sleep(.1)
                        release.set()
                        self.assertTrue(await asyncio.to_thread(executed.wait, 2), "Task wakeup was lost during a running scan")
                        completed = await asyncio.to_thread(runtime.wait, task["id"], timeout=2)
                        self.assertEqual(completed["status"], "succeeded")
                    finally:
                        release.set()


if __name__ == "__main__":
    unittest.main()
