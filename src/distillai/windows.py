"""Windows file handles used for conflict-safe publication, not a sandbox."""
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import time
import threading


if os.name != "nt":
    raise OSError("DistillAI publication requires Windows")

k = ctypes.WinDLL("kernel32", use_last_error=True)


def _function(name, result, *arguments):
    function = getattr(k, name)
    function.restype = result
    function.argtypes = arguments
    return function


_create = _function("CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
                    w.LPVOID, w.DWORD, w.DWORD, w.HANDLE)
_close = _function("CloseHandle", w.BOOL, w.HANDLE)
_read = _function("ReadFile", w.BOOL, w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
_write = _function("WriteFile", w.BOOL, w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
_seek = _function("SetFilePointerEx", w.BOOL, w.HANDLE, ctypes.c_longlong, w.LPVOID, w.DWORD)
_truncate = _function("SetEndOfFile", w.BOOL, w.HANDLE)
_flush = _function("FlushFileBuffers", w.BOOL, w.HANDLE)
_set_info = _function("SetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
_set_time = _function("SetFileTime", w.BOOL, w.HANDLE, ctypes.POINTER(w.FILETIME),
                      ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME))
_get_type = _function("GetFileType", w.DWORD, w.HANDLE)
_final_path = _function("GetFinalPathNameByHandleW", w.DWORD, w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
INVALID = ctypes.c_void_p(-1).value


class _Info(ctypes.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME),
                ("accessed", w.FILETIME), ("modified", w.FILETIME),
                ("volume", w.DWORD), ("size_high", w.DWORD), ("size_low", w.DWORD),
                ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]


class _Stream(ctypes.Structure):
    _fields_ = [("size", ctypes.c_longlong), ("name", w.WCHAR * 296)]


class _Rename(ctypes.Structure):
    _fields_ = [("replace", w.BOOLEAN), ("root", w.HANDLE), ("length", w.DWORD), ("name", w.WCHAR * 1)]


_get_info = _function("GetFileInformationByHandle", w.BOOL, w.HANDLE, ctypes.POINTER(_Info))
_first_stream = _function("FindFirstStreamW", w.HANDLE, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(_Stream), w.DWORD)
_next_stream = _function("FindNextStreamW", w.BOOL, w.HANDLE, ctypes.POINTER(_Stream))
_find_close = _function("FindClose", w.BOOL, w.HANDLE)
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


class FileHandle:
    def __init__(self, path, *, writable=False, create=False, open_always=False, delete=False, directory=False, parent=None):
        self.path = Path(os.path.abspath(path))
        access = 0x80000000 | (0x40000000 if writable else 0) | (0x10000 if delete else 0)
        flags = 0x00200000 | (0x02000000 if directory else 0x80)
        if parent is None:
            self.handle = _create(str(self.path), access, 3 if directory else 1, None,
                                  1 if create else 4 if open_always else 3, flags, None)
        else:
            # Relative native opens bind to the pinned directory object, even if its path changes.
            name = ctypes.create_unicode_buffer(self.path.name)
            size = len(self.path.name.encode("utf-16-le"))
            unicode = _Unicode(size, size + 2, ctypes.cast(name, w.LPWSTR))
            attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent.handle,
                                           ctypes.pointer(unicode), 0x1040, None, None)
            handle = w.HANDLE()
            status = _IOStatus()
            _check_nt(_nt_create(ctypes.byref(handle), access | 0x100000, ctypes.byref(attributes),
                                 ctypes.byref(status), None, 0x10 if directory else 0x80,
                                 3 if directory else 1, 2 if create else 3 if open_always else 1,
                                 0x200020 | (1 if directory else 0x40), None, 0))
            self.handle = handle.value
        if self.handle == INVALID:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = self.info()
            if info["attributes"] & 0x400 or bool(info["attributes"] & 0x10) != directory:
                raise OSError("Reparse points and unexpected file types cannot be published")
            if _get_type(self.handle) != 1 or (not directory and info["links"] != 1):
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
            _check(_close(self.handle))
            self.handle = None

    def info(self):
        info = _Info()
        _check(_get_info(self.handle, ctypes.byref(info)))
        return {"identity": [info.volume, info.index_high, info.index_low],
                "attributes": info.attributes, "links": info.links,
                "created": _ticks(info.created), "modified": _ticks(info.modified),
                "size": (info.size_high << 32) | info.size_low}

    def final_path(self):
        size = _final_path(self.handle, None, 0, 0)
        _check(size)
        buffer = ctypes.create_unicode_buffer(size + 1)
        length = _final_path(self.handle, buffer, len(buffer), 0)
        _check(length and length < len(buffer))
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            raise OSError("Publication requires a local drive directory")
        return Path(value.removeprefix("\\\\?\\"))

    def check_streams(self):
        stream = _Stream()
        search = _first_stream(str(self.path), 0, ctypes.byref(stream), 0)
        if search == INVALID:
            error = ctypes.get_last_error()
            if error == 38:  # Empty files may have no enumerable streams.
                return
            raise ctypes.WinError(error)
        try:
            while True:
                if stream.name != "::$DATA":
                    raise OSError("Alternate data streams cannot be published")
                if not _next_stream(search, ctypes.byref(stream)):
                    error = ctypes.get_last_error()
                    if error != 38:
                        raise ctypes.WinError(error)
                    break
        finally:
            _check(_find_close(search))

    def read(self):
        _check(_seek(self.handle, 0, None, 0))
        data = bytearray()
        buffer = ctypes.create_string_buffer(1024 * 1024)
        count = w.DWORD()
        while True:
            _check(_read(self.handle, buffer, len(buffer), ctypes.byref(count), None))
            if not count.value:
                return bytes(data)
            data.extend(buffer.raw[:count.value])

    def write(self, data, *, offset=0):
        _check(_seek(self.handle, offset, None, 0))
        for offset in range(0, len(data), 1024 * 1024):
            chunk = data[offset:offset + 1024 * 1024]
            count = w.DWORD()
            _check(_write(self.handle, chunk, len(chunk), ctypes.byref(count), None))
            if count.value != len(chunk):
                raise OSError("Incomplete publication write")
        _check(_truncate(self.handle))
        _check(_flush(self.handle))

    def restore_modified(self, ticks):
        timestamp = w.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
        _check(_set_time(self.handle, None, None, ctypes.byref(timestamp)))
        _check(_flush(self.handle))

    def rename(self, destination):
        destination = Path(os.path.abspath(destination))
        with pinned_path(destination) as parent:
            self._rename_relative(destination, parent)

    def _rename_relative(self, destination, parent):
        name = destination.name.encode("utf-16-le")
        offset = _Rename.name.offset
        info = ctypes.create_string_buffer(max(ctypes.sizeof(_Rename), offset + len(name) + 2))
        header = _Rename.from_buffer(info)
        header.root = parent.handle
        header.length = len(name)
        ctypes.memmove(ctypes.addressof(info) + offset, name, len(name))
        status = _IOStatus()
        _check_nt(_nt_set(self.handle, ctypes.byref(status), info, len(info), 10))
        self.path = Path(os.path.abspath(destination))

    def remove(self):
        dispose = w.BOOLEAN(True)
        _check(_set_info(self.handle, 4, ctypes.byref(dispose), ctypes.sizeof(dispose)))


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


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("process_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("times", ctypes.c_int64 * 4), ("faults", w.DWORD), ("total", w.DWORD),
                ("active", w.DWORD), ("terminated", w.DWORD)]


_create_job = _function("CreateJobObjectW", w.HANDLE, w.LPVOID, w.LPCWSTR)
_set_job = _function("SetInformationJobObject", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
_assign_job = _function("AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
_terminate_job = _function("TerminateJobObject", w.BOOL, w.HANDLE, w.UINT)
_query_job = _function("QueryInformationJobObject", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID)
_open_process = _function("OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
_resume_process = nt.NtResumeProcess
_resume_process.restype = ctypes.c_long
_resume_process.argtypes = [w.HANDLE]


class ProcessJob:
    """Assign a suspended child before it can spawn; stop the inherited tree."""
    def __init__(self):
        self._lock = threading.RLock()
        self.handle = _create_job(None, None)
        _check(self.handle)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000
        try:
            _check(_set_job(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            _close(self.handle)
            self.handle = None
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def assign(self, pid):
        with self._lock:
            process = _open_process(0x101101, False, pid)
            _check(process)
            try:
                _check(_assign_job(self.handle, process))
            finally:
                _check(_close(process))

    def resume(self, pid):
        with self._lock:
            process = _open_process(0x800, False, pid)
            _check(process)
            try:
                _check_nt(_resume_process(process))
            finally:
                _check(_close(process))

    def stop(self, timeout=5):
        with self._lock:
            if self.handle is None:
                return
            _check(_terminate_job(self.handle, 1))
            deadline = time.monotonic() + timeout
            while True:
                accounting = _Accounting()
                _check(_query_job(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None))
                if not accounting.active:
                    return
                if time.monotonic() >= deadline:
                    raise TimeoutError("Task process tree has not stopped; keep its execution slot reserved")
                time.sleep(.01)

    def close(self):
        with self._lock:
            if self.handle is not None:
                self.stop()
                _check(_close(self.handle))
                self.handle = None
