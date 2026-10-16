"""Official SDK stdio tools bridge to the independently running local backend."""
import asyncio
from contextlib import nullcontext
from pathlib import Path
import json
import sys
import threading
from typing import Any
import uuid
from urllib.error import HTTPError, URLError


class QueryError(RuntimeError):
    pass


class Bridge:
    def __init__(self, request, *, cancellation_scope=nullcontext):
        self.request = request
        self.cancellation_scope = cancellation_scope

    async def query_context(self, session_key, query, knowledge_refs=None, relation_refs=None):
        invocation = uuid.uuid4().hex
        path = "/v1/queries/" + invocation
        complete = False
        try:
            status = await asyncio.to_thread(self.request, path, method="POST", body={
                "session_key": session_key, "query": query,
                "knowledge_refs": knowledge_refs or [], "relation_refs": relation_refs or []})
            while status["status"] in {"queued", "running", "validating", "recovering"}:
                await asyncio.sleep(.05)
                status = await asyncio.to_thread(self.request, path)
            if status["status"] != "completed":
                raise QueryError("Query " + status["status"] + ": " + str(status.get("error") or status.get("reason") or "execution stopped"))
            complete = True
            return status["result"]
        finally:
            if not complete:
                # The UUID is known before registration, including when its response is lost.
                with self.cancellation_scope():
                    try:
                        await asyncio.shield(asyncio.to_thread(self.request, path + "/cancel", method="POST",
                            body={"reason": "MCP call cancelled, disconnected, or failed before a result was returned"}))
                    except Exception:
                        print("DistillAI could not confirm query cancellation with the backend.", file=sys.stderr)

    async def submit_feedback(self, client_request_id, session_key, performance, task, help,
                              knowledge_refs=None, relation_refs=None, source_refs=None):
        return await asyncio.to_thread(self.request, "/v1/feedback", method="POST", body={
            "client_request_id": client_request_id, "session_key": session_key, "performance": performance,
            "task": task, "help": help, "knowledge_refs": knowledge_refs or [],
            "relation_refs": relation_refs or [], "source_refs": source_refs or []})


def local_request(home):
    from .startup import live_instance, instance_request
    instance = None
    lock = threading.Lock()

    def request(path, *, method="GET", body=None):
        nonlocal instance
        with lock:
            if instance is None:
                instance = live_instance(home)
                if instance is None:
                    # shortcut: the verified Windows SDK reaps descendants on disconnect; enable cold start after G2 proves a persistent entry.
                    raise QueryError("backend_not_started: Start scripts/start.ps1 -Action Serve before connecting MCP")
        try:
            return instance_request(instance, path, method=method, body=body)
        except HTTPError as error:
            try:
                with error:
                    code = json.loads(error.read(1024 * 1024))["error"]["code"]
            except (ValueError, KeyError):
                code = "backend_http_error"
            raise QueryError(code) from None
        except (URLError, OSError):
            raise QueryError("service_unavailable") from None
    return request


def run_stdio(home):
    from mcp.server import MCPServer
    import anyio

    server = MCPServer("distillai", log_level="ERROR")
    bridge = Bridge(local_request(home), cancellation_scope=lambda: anyio.CancelScope(shield=True))
    prompts = Path(__file__).parent / "prompts"

    @server.tool(description=(prompts / "query-tool.txt").read_text(encoding="utf-8"), structured_output=True)
    async def query_context(session_key: str, query: str, knowledge_refs: list[dict] | None = None,
                            relation_refs: list[dict] | None = None) -> dict[str, Any]:
        return await bridge.query_context(session_key, query, knowledge_refs, relation_refs)

    @server.tool(description=(prompts / "feedback-tool.txt").read_text(encoding="utf-8"), structured_output=True)
    async def submit_feedback(client_request_id: str, session_key: str, performance: str, task: str, help: str,
                              knowledge_refs: list[dict] | None = None, relation_refs: list[dict] | None = None,
                              source_refs: list[dict] | None = None) -> dict[str, Any]:
        return await bridge.submit_feedback(client_request_id, session_key, performance, task, help,
                                             knowledge_refs, relation_refs, source_refs)

    server.run(transport="stdio")
