"""Windows file handles used for conflict-safe publication, not a sandbox."""
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import time
import threading
import pywintypes
import win32api
import win32file
import win32job


if os.name != "nt":
    raise OSError("DistillAI publication requires Windows")

k = ctypes.WinDLL("kernel32", use_last_error=True)


def _function(name, result, *arguments):
    function = getattr(k, name)
    function.restype = result
    function.argtypes = arguments
    return function


# pywin32 time values lose the last FILETIME digit; recovery compares exact 100 ns ticks.
_set_time = _function("SetFileTime", w.BOOL, w.HANDLE, ctypes.POINTER(w.FILETIME),
                      ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME))


class _Info(ctypes.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME),
                ("accessed", w.FILETIME), ("modified", w.FILETIME),
                ("volume", w.DWORD), ("size_high", w.DWORD), ("size_low", w.DWORD),
                ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]


class _Rename(ctypes.Structure):
    _fields_ = [("replace", w.BOOLEAN), ("root", w.HANDLE), ("length", w.DWORD), ("name", w.WCHAR * 1)]


_get_info = _function("GetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.POINTER(_Info))
nt = ctypes.WinDLL("ntdll", use_last_error=True)


class _Unicode(ctypes.Structure):
    _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", w.LPWSTR)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [("length", w.ULONG), ("root", w.HANDLE), ("name", ctypes.POINTER(_Unicode)),
                ("attributes", w.ULONG), ("security", w.LPVOID), ("quality", w.LPVOID)]


class _IOStatus(ctypes.Structure):
    _fields_ = [("status", w.LPVOID), ("information", ctypes.c_size_t)]


_nt_create = nt.NtCreateFile
_nt_create.restype = w.LONG
_nt_create.argtypes = [ctypes.POINTER(w.HANDLE), w.DWORD, ctypes.POINTER(_ObjectAttributes),
                       ctypes.POINTER(_IOStatus), w.LPVOID, w.ULONG, w.ULONG, w.ULONG,
                       w.ULONG, w.LPVOID, w.ULONG]
_nt_set = nt.NtSetInformationFile
_nt_set.restype = w.LONG
_nt_set.argtypes = [w.HANDLE, ctypes.POINTER(_IOStatus), w.LPVOID, w.ULONG, w.ULONG]
_nt_error = nt.RtlNtStatusToDosError
_nt_error.restype = w.ULONG
_nt_error.argtypes = [w.LONG]


def _check_nt(status):
    if status < 0:
        raise ctypes.WinError(_nt_error(status))


def _check(success):
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())


def _ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _win32(function, *args):
    # pywintypes.error is not OSError; preserve callers' existing failure contract.
    try:
        return function(*args)
    except pywintypes.error as error:
        raise ctypes.WinError(error.winerror) from None


class FileHandle:
    def __init__(self, path, *, writable=False, create=False, open_always=False, delete=False, directory=False, parent=None):
        self.path = Path(os.path.abspath(path))
        access = 0x80000000 | (0x40000000 if writable else 0) | (0x10000 if delete else 0)
        flags = 0x00200000 | (0x02000000 if directory else 0x80)
        if parent is None:
            self.handle = _win32(win32file.CreateFile, str(self.path), access, 3 if directory else 1, None,
                                  1 if create else 4 if open_always else 3, flags, None)
        else:
            # Relative native opens bind to the pinned directory object, even if its path changes.
            name = ctypes.create_unicode_buffer(self.path.name)
            size = len(self.path.name.encode("utf-16-le"))
            unicode = _Unicode(size, size + 2, ctypes.cast(name, w.LPWSTR))
            attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), int(parent.handle),
                                           ctypes.pointer(unicode), 0x1040, None, None)
            handle = w.HANDLE()
            status = _IOStatus()
            _check_nt(_nt_create(ctypes.byref(handle), access | 0x100000, ctypes.byref(attributes),
                                 ctypes.byref(status), None, 0x10 if directory else 0x80,
                                 3 if directory else 1, 2 if create else 3 if open_always else 1,
                                 0x200020 | (1 if directory else 0x40), None, 0))
            self.handle = pywintypes.HANDLE(handle.value)
        try:
            info = self.info()
            if info["attributes"] & 0x400 or bool(info["attributes"] & 0x10) != directory:
                raise OSError("Reparse points and unexpected file types cannot be published")
            if _win32(win32file.GetFileType, self.handle) != win32file.FILE_TYPE_DISK or (not directory and info["links"] != 1):
                raise OSError("Only single-link disk files can be published")
            # Sparse/compressed/encrypted/offline metadata needs a different recovery strategy.
            if not directory and info["attributes"] & ~0xA7:
                raise OSError("Unsupported file attributes")
            if not directory:
                self.check_streams()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.handle is not None:
            _win32(self.handle.Close)
            self.handle = None

    def info(self):
        info = _Info()
        _check(_get_info(int(self.handle), ctypes.byref(info)))
        return {"identity": [info.volume, info.index_high, info.index_low],
                "attributes": info.attributes, "links": info.links,
                "created": _ticks(info.created), "modified": _ticks(info.modified),
                "size": (info.size_high << 32) | info.size_low}

    def final_path(self):
        value = _win32(win32file.GetFinalPathNameByHandle, self.handle, 0)
        if value.startswith("\\\\?\\UNC\\"):
            raise OSError("Publication requires a local drive directory")
        return Path(value.removeprefix("\\\\?\\"))

    def check_streams(self):
        streams = _win32(win32file.GetFileInformationByHandleEx, self.handle, win32file.FileStreamInfo)
        if any(stream["StreamName"] != "::$DATA" for stream in streams):
            raise OSError("Alternate data streams cannot be published")

    def read(self):
        _win32(win32file.SetFilePointer, self.handle, 0, win32file.FILE_BEGIN)
        data = bytearray()
        while True:
            _, chunk = _win32(win32file.ReadFile, self.handle, 1024 * 1024)
            if not chunk:
                return bytes(data)
            data.extend(chunk)

    def write(self, data, *, offset=0):
        _win32(win32file.SetFilePointer, self.handle, offset, win32file.FILE_BEGIN)
        for offset in range(0, len(data), 1024 * 1024):
            chunk = data[offset:offset + 1024 * 1024]
            _, count = _win32(win32file.WriteFile, self.handle, chunk)
            if count != len(chunk):
                raise OSError("Incomplete publication write")
        _win32(win32file.SetEndOfFile, self.handle)
        _win32(win32file.FlushFileBuffers, self.handle)

    def restore_modified(self, ticks):
        timestamp = w.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
        _check(_set_time(int(self.handle), None, None, ctypes.byref(timestamp)))
        _win32(win32file.FlushFileBuffers, self.handle)

    def rename(self, destination):
        destination = Path(os.path.abspath(destination))
        with pinned_path(destination) as parent:
            self._rename_relative(destination, parent)

    def _rename_relative(self, destination, parent):
        # SetFileInformationByHandle rejects a non-null RootDirectory here (WinError 87).
        name = destination.name.encode("utf-16-le")
        offset = _Rename.name.offset
        info = ctypes.create_string_buffer(max(ctypes.sizeof(_Rename), offset + len(name) + 2))
        header = _Rename.from_buffer(info)
        header.root = int(parent.handle)
        header.length = len(name)
        ctypes.memmove(ctypes.addressof(info) + offset, name, len(name))
        status = _IOStatus()
        _check_nt(_nt_set(int(self.handle), ctypes.byref(status), info, len(info), 10))
        self.path = Path(os.path.abspath(destination))

    def remove(self):
        _win32(win32file.SetFileInformationByHandle, self.handle, win32file.FileDispositionInfo, True)


@contextmanager
def pinned_path(path):
    """Hold every existing ancestor without following junctions or symlinks."""
    path = Path(os.path.abspath(path))
    if str(path).startswith("\\\\") or any(":" in part for part in path.parts[1:]):
        raise OSError("Publication requires a local drive path without streams")
    with ExitStack() as stack:
        handle = None
        for parent in reversed(path.parents):
            handle = stack.enter_context(FileHandle(parent, directory=True, parent=handle))
        yield handle


def canonical_directory(path):
    with pinned_path(Path(os.path.abspath(path)) / ".directory-check") as directory:
        return directory.final_path()


_resume_process = nt.NtResumeProcess
_resume_process.restype = ctypes.c_long
_resume_process.argtypes = [w.HANDLE]


def resume_process(pid, *, require_detached=False):
    process = _win32(win32api.OpenProcess, 0x1800 if require_detached else 0x800, False, pid)
    try:
        if require_detached and _win32(win32job.IsProcessInJob, process, None):
            return False
        _check_nt(_resume_process(int(process)))
        return True
    finally:
        _win32(process.Close)


class ProcessJob:
    """Assign a suspended child before it can spawn; stop the inherited tree."""
    def __init__(self):
        self._lock = threading.RLock()
        self.handle = _win32(win32job.CreateJobObject, None, "")
        limits = _win32(win32job.QueryInformationJobObject, self.handle, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            _win32(win32job.SetInformationJobObject, self.handle, win32job.JobObjectExtendedLimitInformation, limits)
        except BaseException:
            _win32(self.handle.Close)
            self.handle = None
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def assign(self, pid):
        with self._lock:
            process = _win32(win32api.OpenProcess, 0x101101, False, pid)
            try:
                _win32(win32job.AssignProcessToJobObject, self.handle, process)
            finally:
                _win32(process.Close)

    def resume(self, pid):
        with self._lock:
            resume_process(pid)

    def stop(self, timeout=5):
        with self._lock:
            if self.handle is None:
                return
            _win32(win32job.TerminateJobObject, self.handle, 1)
            deadline = time.monotonic() + timeout
            while True:
                accounting = _win32(win32job.QueryInformationJobObject, self.handle, win32job.JobObjectBasicAccountingInformation)
                if not accounting["ActiveProcesses"]:
                    return
                if time.monotonic() >= deadline:
                    raise TimeoutError("Task process tree has not stopped; keep its execution slot reserved")
                time.sleep(.01)

    def close(self):
        with self._lock:
            if self.handle is not None:
                self.stop()
                _win32(self.handle.Close)
                self.handle = None
