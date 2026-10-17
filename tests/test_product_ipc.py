"""Task communication must remain bounded during connection, authentication and cancellation."""
from multiprocessing.connection import Client
from multiprocessing import AuthenticationError
import json
import multiprocessing
import threading
import time
import unittest

import win32api
import win32con
import win32event

from distillai.ipc import MAX_MESSAGE, TaskPipe
from distillai.windows import ProcessJob


def pipe_peer(address, authkey, mode, gate, ready, transfer):
    if not gate.wait(10):
        return
    try:
        with Client(address, family="AF_PIPE", authkey=authkey) as connection:
            if mode != "no_read":
                connection.recv_bytes(MAX_MESSAGE)
            ready.set()
            if mode == "large_request":
                connection.send_bytes(b"x" * MAX_MESSAGE)
            elif mode == "large_response":
                connection.send_bytes(b"request")
                if connection.poll(5):
                    transfer.set()
            time.sleep(15)
    except (EOFError, OSError):
        pass


def pipe_owner(report):
    context = multiprocessing.get_context("spawn")
    with ProcessJob() as job, TaskPipe(job) as channel:
        gate, ready, transfer = (context.Event() for _ in range(3))
        peer = context.Process(target=pipe_peer, args=(channel.address, channel.authkey, "no_read", gate, ready, transfer))
        peer.start()
        job.assign(peer.pid)
        gate.set()
        channel.accept(timeout=5)
        if not ready.wait(5):
            return
        report.send_bytes(json.dumps([channel.process.pid, peer.pid]).encode())
        report.close()
        time.sleep(15)


class PipeTests(unittest.TestCase):
    def peer(self, channel, job, mode):
        context = multiprocessing.get_context("spawn")
        gate, ready, transfer = (context.Event() for _ in range(3))
        peer = context.Process(target=pipe_peer, args=(channel.address, channel.authkey, mode, gate, ready, transfer))
        peer.start()
        def reap():
            if peer.is_alive():
                peer.terminate()
            peer.join(3)
            peer.close()
        self.addCleanup(reap)
        job.assign(peer.pid)
        gate.set()
        channel.accept(timeout=5)
        if mode != "no_read":
            channel.send(b"bootstrap")
        self.assertTrue(ready.wait(5))
        return peer, transfer

    def test_no_connection_and_unfinished_authentication_are_reaped(self):
        for connect in (False, True):
            with self.subTest(connect=connect), TaskPipe() as channel:
                connection = Client(channel.address, family="AF_PIPE") if connect else None
                try:
                    with self.assertRaises(TimeoutError):
                        channel.accept(timeout=.15)
                    start = time.monotonic()
                    channel.close()
                    self.assertLess(time.monotonic() - start, 3)
                    self.assertFalse(channel.process.is_alive())
                finally:
                    if connection is not None:
                        connection.close()

    def test_authenticated_messages_and_cancellation_do_not_leave_a_waiter(self):
        with TaskPipe() as channel:
            received = []
            def child():
                with Client(channel.address, family="AF_PIPE", authkey=channel.authkey) as connection:
                    self.assertEqual(connection.recv_bytes(), b'{"bootstrap":true}')
                    connection.send_bytes(b'{"operation":"synthetic"}')
                    received.append(connection.recv_bytes())
            thread = threading.Thread(target=child)
            thread.start()
            channel.accept(timeout=3)
            channel.send(b'{"bootstrap":true}')
            self.assertEqual(channel.receive(timeout=3), b'{"operation":"synthetic"}')
            channel.send(b'{"result":"ok"}')
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received, [b'{"result":"ok"}'])
            with self.assertRaises(EOFError):
                channel.receive(timeout=1)

    def test_wrong_authentication_and_oversized_messages_fail_closed(self):
        with TaskPipe() as channel:
            with self.assertRaises(AuthenticationError):
                Client(channel.address, family="AF_PIPE", authkey=b"wrong-key")
            with self.assertRaises(EOFError):
                channel.accept(timeout=3)
        with TaskPipe() as channel:
            with self.assertRaises(ValueError):
                channel.send(b"x" * (8 * 1024 * 1024 + 1))

    def test_authenticated_peer_that_never_replies_can_be_cancelled_and_reaped(self):
        with ProcessJob() as job, TaskPipe(job) as channel:
            peer, _ = self.peer(channel, job, "no_reply")
            cancelled = threading.Event()
            timer = threading.Timer(.1, cancelled.set)
            timer.start()
            try:
                start = time.monotonic()
                with self.assertRaises(InterruptedError):
                    channel.receive(cancelled=cancelled.is_set)
                job.stop()
                channel.close()
                peer.join(3)
                self.assertLess(time.monotonic() - start, 3)
                self.assertFalse(peer.is_alive())
                self.assertFalse(channel.process.is_alive())
            finally:
                timer.cancel()
                timer.join(3)

    def test_large_request_and_response_writes_can_be_stopped_without_a_waiter(self):
        for mode in ("large_request", "large_response"):
            with self.subTest(mode=mode), ProcessJob() as job, TaskPipe(job) as channel:
                peer, transfer = self.peer(channel, job, mode)
                writer = None
                finished, writing = threading.Event(), threading.Event()
                errors = []
                if mode == "large_response":
                    self.assertEqual(channel.receive(timeout=5), b"request")

                    def send():
                        writing.set()
                        try:
                            channel.send(b"x" * MAX_MESSAGE)
                        except (EOFError, OSError, ValueError):
                            pass
                        except Exception as error:
                            errors.append(type(error).__name__)
                        finally:
                            finished.set()
                    writer = threading.Thread(target=send)
                    writer.start()
                    self.assertTrue(writing.wait(3))
                    self.assertTrue(transfer.wait(5), "Peer never saw the pending response write")
                else:
                    self.assertTrue(channel.connection.poll(5), "Relay never began forwarding the large request")
                start = time.monotonic()
                job.stop()
                channel.close()
                peer.join(3)
                if writer is not None:
                    writer.join(3)
                    self.assertTrue(finished.is_set())
                    self.assertFalse(writer.is_alive())
                self.assertLess(time.monotonic() - start, 3)
                self.assertFalse(peer.is_alive())
                self.assertFalse(channel.process.is_alive())
                self.assertEqual(errors, [])

    def test_parent_death_stops_the_pipe_owner_and_authenticated_peer(self):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        parent = context.Process(target=pipe_owner, args=(sender,))
        handles = []
        try:
            parent.start()
            sender.close()
            self.assertTrue(receiver.poll(10), "Pipe owner did not report readiness")
            identifiers = json.loads(receiver.recv_bytes(10000))
            handles = [win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, pid) for pid in identifiers]
            parent.terminate()
            parent.join(3)
            self.assertFalse(parent.is_alive())
            for handle in handles:
                self.assertEqual(win32event.WaitForSingleObject(handle, 3000), win32event.WAIT_OBJECT_0)
        finally:
            if parent.is_alive():
                parent.terminate()
                parent.join(3)
            for handle in handles:
                if win32event.WaitForSingleObject(handle, 0) != win32event.WAIT_OBJECT_0:
                    win32api.TerminateProcess(handle, 1)
                    win32event.WaitForSingleObject(handle, 3000)
                handle.Close()
            receiver.close()
            sender.close()
            parent.close()


if __name__ == "__main__":
    unittest.main()
