"""MCP calls keep errors distinct and cancellation scoped to their invocation."""
import asyncio
from contextlib import asynccontextmanager
import unittest

from fastmcp import Client
from fastmcp.exceptions import ToolError

from distillai.mcp import Bridge, QueryError, create_server


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_fastmcp_client_preserves_tools_strict_inputs_and_structured_results(self):
        calls = []
        async def request(path, **kwargs):
            calls.append((path, kwargs))
            if path == "/v1/feedback":
                return {"feedback_id": "f" * 64, "stage": "awaiting_source"}
            return {"status": "completed", "result": {"status": "no_match", "items": []}}
        @asynccontextmanager
        async def lifespan(server):
            yield {"bridge": Bridge(request)}
        async with Client(create_server("synthetic", lifespan=lifespan)) as client:
            tools = await client.list_tools()
            self.assertEqual({tool.name for tool in tools}, {"query_context", "submit_feedback"})
            result = await client.call_tool("query_context", {"session_key": "synthetic", "query": "synthetic question"})
            self.assertEqual(result.data, {"status": "no_match", "items": []})
            before = len(calls)
            for bad in ({"session_key": False, "query": "x"}, {"session_key": "synthetic", "query": "x", "unknown": True},
                        {"session_key": "../private", "query": "x"}, {"session_key": "synthetic", "query": " \n"}):
                with self.subTest(arguments=bad), self.assertRaises(ToolError):
                    await client.call_tool("query_context", bad)
            with self.assertRaises(ToolError):
                await client.call_tool("submit_feedback", {"client_request_id": "stable-request", "session_key": "synthetic",
                    "performance": "actual expression", "task": "synthetic task", "help": "none",
                    "source_refs": [{"source_kind": "external", "id": "a" * 32, "version": "b" * 64}]})
            self.assertEqual(len(calls), before)
            result = await client.call_tool("submit_feedback", {"client_request_id": "stable-request", "session_key": "synthetic",
                "performance": "actual expression", "task": "synthetic task", "help": "none"})
            self.assertEqual(result.data["stage"], "awaiting_source")
            self.assertEqual(calls[-1][1]["body"]["client_request_id"], "stable-request")

    async def test_fastmcp_client_cancellation_stops_only_the_associated_invocation(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        paths = []
        async def request(path, **kwargs):
            paths.append(path)
            if path.endswith("/cancel"):
                cancelled.set()
                return {"status": "cancelled"}
            entered.set()
            await asyncio.Event().wait()
        @asynccontextmanager
        async def lifespan(server):
            yield {"bridge": Bridge(request)}
        async with Client(create_server("synthetic", lifespan=lifespan)) as client:
            task = asyncio.create_task(client.call_tool("query_context", {"session_key": "synthetic", "query": "same query"}))
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(cancelled.wait(), 3)
            self.assertEqual(paths[-1], paths[0] + "/cancel")

    async def test_query_waits_for_its_result_and_failure_is_not_a_successful_empty(self):
        calls = []
        async def request(path, *, method="GET", body=None):
            calls.append((path, method, body))
            if method == "POST":
                return {"status": "queued", "task_id": "a" * 32}
            return {"status": "completed", "result": {"status": "no_match", "items": []}}
        result = await Bridge(request).query_context("synthetic", "synthetic question")
        self.assertEqual(result, {"status": "no_match", "items": []})
        self.assertEqual(calls[0][0], calls[1][0])
        async def failing(path, **kwargs):
            return {"status": "failed", "error": {"code": "BudgetError"}}
        with self.assertRaises(QueryError):
            await Bridge(failing).query_context("synthetic", "synthetic question")

    async def test_cancellation_before_registration_reply_saves_a_tombstone_for_only_that_call(self):
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        paths = []
        async def request(path, *, method="GET", body=None):
            paths.append(path)
            if path.endswith("/cancel"):
                cancelled.set()
                return {"status": "cancelled"}
            entered.set()
            await release.wait()
            return {"status": "queued"}
        call = asyncio.create_task(Bridge(request).query_context("synthetic", "same text"))
        try:
            self.assertTrue(await asyncio.wait_for(entered.wait(), 2))
            call.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await call
            self.assertTrue(await asyncio.wait_for(cancelled.wait(), 2))
            self.assertEqual(paths[1], paths[0] + "/cancel")
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
