"""Multiple native entrypoints share one verified service and recover after stop."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest

from distillai.startup import live_instance, start_background, stop_background
from distillai.storage import atomic_json
from distillai.windows import ProcessJob


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
                                     stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
            job.assign(child.pid)
            job.resume(child.pid)
            stdout, stderr = child.communicate(b"start\n", timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("independent backend", json.loads(stdout).get("error", ""))
        self.assertIsNone(live_instance(self.home))

    def test_polling_discovers_complete_material_without_a_notification(self):
        start_background(self.home, self.command)
        queue = self.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_bytes(b'{"role":"user","text":"synthetic material"}\n{"partial":')
        deadline = time.monotonic() + 5
        tasks = []
        while time.monotonic() < deadline:
            tasks = [json.loads(path.read_text()) for path in (self.home / "tasks").glob("*.json")]
            if tasks:
                break
            time.sleep(.05)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["inputs"]["source_refs"], [{"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}])


if __name__ == "__main__":
    unittest.main()
