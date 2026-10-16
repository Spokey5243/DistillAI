"""MCP calls keep errors distinct and cancellation scoped to their invocation."""
import asyncio
import threading
import unittest

from distillai.mcp import Bridge, QueryError


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_waits_for_its_result_and_failure_is_not_a_successful_empty(self):
        calls = []
        def request(path, *, method="GET", body=None):
            calls.append((path, method, body))
            if method == "POST":
                return {"status": "queued", "task_id": "a" * 32}
            return {"status": "completed", "result": {"status": "no_match", "items": []}}
        result = await Bridge(request).query_context("synthetic", "synthetic question")
        self.assertEqual(result, {"status": "no_match", "items": []})
        self.assertEqual(calls[0][0], calls[1][0])
        def failing(path, **kwargs):
            return {"status": "failed", "error": {"code": "BudgetError"}}
        with self.assertRaises(QueryError):
            await Bridge(failing).query_context("synthetic", "synthetic question")

    async def test_cancellation_before_registration_reply_saves_a_tombstone_for_only_that_call(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        paths = []
        def request(path, *, method="GET", body=None):
            paths.append(path)
            if path.endswith("/cancel"):
                cancelled.set()
                return {"status": "cancelled"}
            entered.set()
            release.wait(3)
            return {"status": "queued"}
        call = asyncio.create_task(Bridge(request).query_context("synthetic", "same text"))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            call.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await call
            self.assertTrue(await asyncio.to_thread(cancelled.wait, 2))
            self.assertEqual(paths[1], paths[0] + "/cancel")
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
