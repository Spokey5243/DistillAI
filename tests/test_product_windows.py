"""Protect the exact file/path being compared and preserve its identity."""
from pathlib import Path
import os
import ctypes
from ctypes import wintypes as w
import struct
import sys
import time
import threading
from unittest.mock import patch
import subprocess
import tempfile
import unittest

from distillai.windows import FileHandle, ProcessJob, pinned_path


@unittest.skipUnless(os.name == "nt", "Windows handle contract")
class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_held_handle_blocks_external_mutations_and_preserves_identity(self):
        path = self.root / "file.txt"
        path.write_bytes(b"before")
        with FileHandle(path, writable=True) as handle:
            before = handle.info()["identity"]
            for mutation in (lambda: path.write_bytes(b"bad"), lambda: path.unlink(),
                             lambda: path.rename(self.root / "moved.txt")):
                with self.assertRaises(OSError):
                    mutation()
            handle.write(b"short")
            self.assertEqual(handle.read(), b"short")
            self.assertEqual(handle.info()["identity"], before)
        self.assertEqual(path.read_bytes(), b"short")

    def test_exclusive_creation_and_rename_do_not_replace_user_file(self):
        path = self.root / "file.txt"
        path.write_bytes(b"user")
        with self.assertRaises(OSError):
            FileHandle(path, writable=True, create=True)
        other = self.root / "other.txt"
        other.write_bytes(b"other")
        with FileHandle(other, writable=True, delete=True) as handle:
            with self.assertRaises(OSError):
                handle.rename(path)
        self.assertEqual(path.read_bytes(), b"user")

    def test_pinned_parent_blocks_rename_but_allows_child_creation(self):
        parent = self.root / "parent"
        parent.mkdir()
        with pinned_path(parent / "new.txt"):
            with self.assertRaises(OSError):
                parent.rename(self.root / "moved")
            (parent / "new.txt").write_bytes(b"new")

    def test_junction_in_path_is_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        junction = self.root / "junction"
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        f"New-Item -ItemType Junction -Path '{junction}' -Target '{actual}' | Out-Null"],
                       check=True, capture_output=True)
        with self.assertRaises(OSError):
            with pinned_path(junction / "file.txt"):
                self.fail("junction accepted")

    def test_relative_creation_does_not_follow_repointed_parent(self):
        from distillai.windows import _create, _close, INVALID
        parent = self.root / "parent"
        parent.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        ioctl = ctypes.WinDLL("kernel32", use_last_error=True).DeviceIoControl
        ioctl.argtypes = [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD, w.LPVOID, w.DWORD,
                          ctypes.POINTER(w.DWORD), w.LPVOID]
        ioctl.restype = w.BOOL
        with pinned_path(parent / "new.txt") as pinned:
            writer = _create(str(parent), 0x40000000, 3, None, 3, 0x02200000, None)
            self.assertNotEqual(writer, INVALID)
            substitute = ("\\??\\" + str(outside)).encode("utf-16-le")
            printed = str(outside).encode("utf-16-le")
            names = substitute + b"\0\0" + printed + b"\0\0"
            buffer = struct.pack("<LHHHHHH", 0xA0000003, 8 + len(names), 0, 0,
                                 len(substitute), len(substitute) + 2, len(printed)) + names
            count = w.DWORD()
            try:
                self.assertTrue(ioctl(writer, 0x900A4, buffer, len(buffer), None, 0, ctypes.byref(count), None))
                try:
                    with FileHandle(parent / "new.txt", writable=True, create=True, parent=pinned) as handle:
                        handle.write(b"must not reach outside")
                except OSError:
                    pass  # Rejecting the changed parent is also safe.
                self.assertFalse((outside / "new.txt").exists())
            finally:
                delete = struct.pack("<LHH", 0xA0000003, 0, 0)
                self.assertTrue(ioctl(writer, 0x900AC, delete, len(delete), None, 0, ctypes.byref(count), None))
                _close(writer)

    def test_stopping_job_stops_parent_child_and_grandchild_writes(self):
        program = self.root / "heartbeat.py"
        program.write_text(
            "import os,sys,time,subprocess\nfrom pathlib import Path\n"
            "root=Path(sys.argv[1]);depth=int(sys.argv[2])\n"
            "if depth == 2: sys.stdin.readline()\n"
            "if depth: subprocess.Popen([sys.executable,__file__,str(root),str(depth-1)],"
            "creationflags=subprocess.CREATE_NO_WINDOW)\n"
            "while True:\n (root / (str(os.getpid())+'.heartbeat')).write_text(str(time.time_ns()))\n time.sleep(.02)\n",
            encoding="utf-8")
        parent = subprocess.Popen([sys._base_executable, str(program), str(self.root), "2"],
                                  stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW | 0x4)
        try:
            with ProcessJob() as job:
                job.assign(parent.pid)
                job.resume(parent.pid)
                parent.stdin.write(b"go\n")
                parent.stdin.flush()
                deadline = time.monotonic() + 5
                while len(list(self.root.glob("*.heartbeat"))) != 3 and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(len(list(self.root.glob("*.heartbeat"))), 3)
                job.stop()
                parent.wait(timeout=5)
                before = {p.name: p.read_bytes() for p in self.root.glob("*.heartbeat")}
                time.sleep(.1)
                self.assertEqual({p.name: p.read_bytes() for p in self.root.glob("*.heartbeat")}, before)
        finally:
            parent.stdin.close()
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)

    def test_concurrent_stop_and_close_do_not_reuse_closed_native_handle(self):
        import distillai.windows as windows
        job = ProcessJob()
        self.addCleanup(job.close)
        entered, release, closing = threading.Event(), threading.Event(), threading.Event()
        errors = []
        original = windows._terminate_job

        def delayed(handle, code):
            if threading.current_thread().name == "delayed-stop":
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("Test did not release native call")
            return original(handle, code)

        def run(action):
            try:
                action()
            except Exception as exc:
                errors.append(type(exc).__name__)

        def close():
            closing.set()
            job.close()

        with patch.object(windows, "_terminate_job", side_effect=delayed):
            first = threading.Thread(target=run, args=(job.stop,), name="delayed-stop")
            second = threading.Thread(target=run, args=(close,))
            first.start()
            self.assertTrue(entered.wait(3))
            second.start()
            self.assertTrue(closing.wait(3))
            time.sleep(.05)
            release.set()
            first.join(3)
            second.join(3)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
