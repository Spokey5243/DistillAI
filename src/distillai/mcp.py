"""FastMCP stdio tools use the independently running business backend."""
from contextlib import asynccontextmanager
from pathlib import Path
import json
from typing import Any
import uuid

import anyio
import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from loguru import logger

from .sources import RecordRef, SourceRef


class QueryError(RuntimeError):
    pass


class Bridge:
    def __init__(self, request):
        self.request = request

    async def query_context(self, session_key, query, knowledge_refs=None, relation_refs=None):
        invocation = uuid.uuid4().hex
        path = "/v1/queries/" + invocation
        complete = False
        try:
            status = await self.request(path, method="POST", body={
                "session_key": session_key, "query": query,
                "knowledge_refs": knowledge_refs or [], "relation_refs": relation_refs or []})
            while status["status"] in {"queued", "running", "validating", "recovering"}:
                await anyio.sleep(.05)
                status = await self.request(path)
            if status["status"] != "completed":
                raise QueryError("Query " + status["status"] + ": " + str(status.get("error") or status.get("reason") or "execution stopped"))
            complete = True
            return status["result"]
        finally:
            if not complete:
                with anyio.CancelScope(shield=True):
                    try:
                        await self.request(path + "/cancel", method="POST",
                            body={"reason": "MCP call cancelled, disconnected, or failed before a result was returned"})
                    except Exception:
                        logger.bind(invocation=invocation, error_code="query_cancel_unconfirmed").warning("query_cancel_unconfirmed")

    async def submit_feedback(self, client_request_id, session_key, performance, task, help,
                              knowledge_refs=None, relation_refs=None, source_refs=None):
        return await self.request("/v1/feedback", method="POST", body={
            "client_request_id": client_request_id, "session_key": session_key, "performance": performance,
            "task": task, "help": help, "knowledge_refs": knowledge_refs or [],
            "relation_refs": relation_refs or [], "source_refs": source_refs or []})


@asynccontextmanager
async def local_request(home):
    from .startup import instance_url, start_product
    instance = None
    lock = anyio.Lock()
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=3) as client:
        async def call(target, path, method, body):
            async with client.stream(method, instance_url(target) + path, json=body,
                    headers={"Authorization": "Bearer " + target["token"], "Content-Type": "application/json"}) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise QueryError("backend_response_too_large")
                payload = json.loads(raw)
                if response.status_code >= 300:
                    raise QueryError(payload.get("error", {}).get("code", "backend_http_error"))
                return payload

        async def request(path, *, method="GET", body=None):
            nonlocal instance
            try:
                async with lock:
                    if instance is None:
                        try:
                            saved = json.loads(await anyio.Path(Path(home) / "instance.json").read_text(encoding="utf-8"))
                            health = await call(saved, "/v1/health", "GET", None)
                            if saved["protocol"] != 1 or not health["ready"] or any(health[field] != saved[field] for field in ("instance_id", "pid", "protocol")):
                                raise ValueError("Backend identity is not ready")
                            instance = saved
                        except (OSError, ValueError, KeyError, httpx.HTTPError, QueryError):
                            try:
                                instance = await anyio.to_thread.run_sync(start_product, home)
                            except (OSError, RuntimeError, TimeoutError):
                                raise QueryError("backend_not_started: Start scripts/start.ps1 -Action Serve outside the MCP client, then reconnect") from None
                return await call(instance, path, method, body)
            except httpx.HTTPError:
                instance = None
                raise QueryError("service_unavailable") from None
            except (OSError, ValueError, KeyError):
                raise QueryError("invalid_backend_response") from None
        yield request


def create_server(home, *, lifespan=None):
    @asynccontextmanager
    async def bridge_lifespan(server):
        async with local_request(home) as request:
            yield {"bridge": Bridge(request)}

    server = FastMCP("distillai", lifespan=lifespan or bridge_lifespan,
                     strict_input_validation=True, mask_error_details=True)
    prompts = Path(__file__).parent / "prompts"

    @server.tool(description=(prompts / "query-tool.txt").read_text(encoding="utf-8"))
    async def query_context(session_key: str, query: str, ctx: Context, knowledge_refs: list[RecordRef] | None = None,
                            relation_refs: list[RecordRef] | None = None) -> dict[str, Any]:
        try:
            return await ctx.lifespan_context["bridge"].query_context(session_key, query, knowledge_refs, relation_refs)
        except QueryError as error:
            raise ToolError(str(error)) from None

    @server.tool(description=(prompts / "feedback-tool.txt").read_text(encoding="utf-8"))
    async def submit_feedback(client_request_id: str, session_key: str, performance: str, task: str, help: str,
                              ctx: Context, knowledge_refs: list[RecordRef] | None = None,
                              relation_refs: list[RecordRef] | None = None, source_refs: list[SourceRef] | None = None) -> dict[str, Any]:
        try:
            return await ctx.lifespan_context["bridge"].submit_feedback(client_request_id, session_key, performance, task, help,
                knowledge_refs, relation_refs, source_refs)
        except QueryError as error:
            raise ToolError(str(error)) from None

    return server


def run_stdio(home):
    create_server(home).run(transport="stdio", show_banner=False)
