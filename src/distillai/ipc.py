"""Authenticated task pipes with a separately reapable blocking accept/IO owner."""
import multiprocessing
from multiprocessing.connection import Listener
import secrets
import time
import uuid


MAX_MESSAGE = 8 * 1024 * 1024


def _serve(parent, address, authkey):
    try:
        with parent, Listener(address, family="AF_PIPE", authkey=authkey) as listener:
            parent.send_bytes(b"listening")
            with listener.accept() as child:
                parent.send_bytes(b"connected")
                child.send_bytes(parent.recv_bytes(MAX_MESSAGE))
                while True:
                    parent.send_bytes(child.recv_bytes(MAX_MESSAGE))
                    child.send_bytes(parent.recv_bytes(MAX_MESSAGE))
    except (EOFError, OSError, multiprocessing.AuthenticationError):
        pass


class TaskPipe:
    def __init__(self, job=None):
        self.address = r"\\.\pipe\distillai-" + uuid.uuid4().hex
        self.authkey = secrets.token_bytes(32)
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe(duplex=True)
        # Listener.accept does not expose its in-flight handle; a process owns all blocking IO.
        self.process = context.Process(target=_serve, args=(child, self.address, self.authkey), daemon=True)
        self.process.start()
        child.close()
        try:
            if job is not None:
                job.assign(self.process.pid)
            if self.receive(timeout=10) != b"listening":
                raise ValueError("Task pipe failed to start")
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def receive(self, *, timeout=None, cancelled=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if cancelled is not None and cancelled():
                raise InterruptedError("Task pipe cancelled")
            try:
                if self.connection.poll(.05):
                    return self.connection.recv_bytes(MAX_MESSAGE)
            except (BrokenPipeError, ConnectionResetError):
                raise EOFError("Task pipe disconnected") from None
            if not self.process.is_alive():
                raise EOFError("Task pipe owner exited")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Task pipe deadline expired")

    def accept(self, *, timeout=10, cancelled=None):
        if self.receive(timeout=timeout, cancelled=cancelled) != b"connected":
            raise ValueError("Invalid task pipe handshake")

    def send(self, payload):
        if not isinstance(payload, bytes) or len(payload) > MAX_MESSAGE:
            raise ValueError("Task pipe message exceeds 8 MiB")
        self.connection.send_bytes(payload)

    def close(self):
        self.connection.close()
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(2)
        if self.process.is_alive():
            raise TimeoutError("Task communication process did not exit")
