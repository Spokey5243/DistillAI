"""Authenticated FastAPI business API and same-origin Web application."""
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import threading
import time
import uuid
from urllib.parse import parse_qs
from typing import TypedDict

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import ConfigDict, TypeAdapter, ValidationError, with_config
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from .config import ConfigError, UpdateArgs
from .storage import ConflictError, _identifier
from .knowledge import EditArgs, KnowledgeIndex, IndexNotReady
from .cognition import CorrectionArgs as CognitionCorrectionArgs, ReanalysisArgs
from .context import FeedbackArgs, QueryArgs
from .episode import CorrectionArgs as EpisodeCorrectionArgs
from .expansion import RequestArgs as ExpansionRequestArgs
from .runtime import RegisterArgs
from .sources import QueueLocator


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class EmptyArgs(TypedDict):
    pass


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ReasonArgs(TypedDict):
    reason: str


class _APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


@dataclass
class _Control:
    runtime: object
    url: str = "http://127.0.0.1:8000"
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    stopping: threading.Event = field(default_factory=threading.Event)
    web_bootstraps: dict = field(default_factory=dict)
    web_sessions: dict = field(default_factory=dict)



class BackendServer(_Control):
    """Own the bound socket while Uvicorn owns HTTP and ASGI lifecycle."""
    def __init__(self, runtime, *, instance_id=None, token=None, lifespan=None):
        super().__init__(runtime)
        if instance_id is not None:
            self.instance_id = instance_id
        if token is not None:
            self.token = token
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.server_port = self.socket.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.server_port}"
        self.app = create_app(runtime, control=self, lifespan=lifespan)
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_config=None, access_log=False, ws="none", proxy_headers=False))

    def serve_forever(self):
        self.server.run(sockets=[self.socket])

    def shutdown(self):
        self.server.should_exit = True

    def server_close(self):
        self.socket.close()




def _referenced_ids(value):
    if isinstance(value, dict):
        if set(value) == {"id", "version"}:
            yield value["id"]
        else:
            for child in value.values():
                yield from _referenced_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _referenced_ids(child)

class _API:
    def __init__(self, request, body, runtime):
        self.request = request
        self.server = request.app.state.control
        self.runtime = runtime
        self.command, self.path = request.method, request.url.path
        self.headers = request.headers
        self.query = parse_qs(request.url.query)
        self.body = body
        self._web_session = request.state.web_session

    def _body(self):
        return self.body

    def related(self):
        runtime = self.runtime
        path, query = self.path, self.query
        return self._related(query), 200

    def reanalysis(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .cognition import request_reanalysis
        if query:
            raise ValueError("Reanalysis does not accept URL parameters")
        task = request_reanalysis(runtime, self._body())
        return {"task_id": task["id"], "status": task["status"]}, 202

    def cognition_correction(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .cognition import register_correction
        if query:
            raise ValueError("Cognition correction does not accept URL parameters")
        task = register_correction(runtime, self._body())
        return {"task_id": task["id"], "status": task["status"]}, 202

    def episode_correction(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .episode import register_correction
        if query:
            raise ValueError("Ownership correction does not accept URL parameters")
        task = register_correction(runtime, self._body())
        return {"task_id": task["id"], "status": task["status"]}, 202

    def expansion_status(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .expansion import status
        return status(runtime), 200

    def expansion_request(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .expansion import register_request
        if query:
            raise ValueError("Exploration request does not accept URL parameters")
        return self._public_task(register_request(runtime, self._body())), 202

    def knowledge_edit(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .knowledge import register_user_edit
        if query:
            raise ValueError("Content edit does not accept URL parameters")
        task = register_user_edit(runtime, self._body())
        return {"task_id": task["id"], "status": task["status"]}, 202

    def bootstrap(self):
        runtime = self.runtime
        path, query = self.path, self.query
        if query:
            raise ValueError("Web bootstrap request has no parameters")
        with runtime.store.locked():
            self.server.web_bootstraps = {key: expiry for key, expiry in self.server.web_bootstraps.items() if expiry > time.monotonic()}
            token = secrets.token_urlsafe(32)
            self.server.web_bootstraps[token] = time.monotonic() + 120
        return {"url": self.server.url + "/web/bootstrap?token=" + token}, 200

    def web_session(self):
        runtime = self.runtime
        path, query = self.path, self.query
        if query or self._web_session is None:
            raise _APIError(401, "browser_session_required")
        return {"csrf_token": self._web_session["csrf_token"]}, 200

    def collection(self):
        runtime = self.runtime
        path, query = self.path, self.query
        collections = {"/v1/episodes": "episodes", "/v1/knowledge": "knowledge", "/v1/relations": "relations",
                       "/v1/hypotheses": "hypotheses", "/v1/expansions": "expansions"}
        collection = collections[path]
        filters = self._list_filters(query, {"session_key", "state"} if collection == "episodes" else {"name"})
        files, _ = runtime.store._scan(runtime.store.home, allowed=[collection])
        items = []
        for name, info in sorted(files.items()):
            record = json.loads(runtime.store.read_version(info["version"]))
            if record.get("id") != _identifier(Path(name).stem) or len(Path(name).parts) != 2:
                raise ValueError("Invalid stored record identity")
            if not all(str(record.get(field, "")).casefold() == value.casefold() for field, value in filters.items()):
                continue
            items.append({"id": record["id"], "version": info["version"], "record_kind": collection,
                          **{field: record[field] for field in ("name", "topic", "goal", "state", "session_key", "claim", "question") if field in record}})
        return self._page(items, collection, query, filters, key=lambda item: item["id"]), 200

    def saved_record(self):
        runtime = self.runtime
        path, query = self.path, self.query
        saved_record = re.fullmatch(r"/v1/(episodes|hypotheses|expansions)/([0-9a-f]{32})", path)
        if set(query) - {"version"} or any(len(value) != 1 for value in query.values()):
            raise ValueError("Record details accept only one version")
        if "version" in query:
            version = _identifier(query["version"][0], 64)
        else:
            files, _ = runtime.store._scan(runtime.store.home, allowed=[saved_record[1] + "/" + saved_record[2] + ".json"])
            if not files:
                raise FileNotFoundError("Record not found")
            version = next(iter(files.values()))["version"]
        record = json.loads(runtime.store.read_version(version))
        required = {"episodes": {"state", "source_refs", "session_key"}, "hypotheses": {"claim", "needed_evidence"},
                    "expansions": {"question", "claims"}}[saved_record[1]]
        if record.get("id") != saved_record[2] or not required.issubset(record):
            raise FileNotFoundError("Version belongs to another record or kind")
        from .cognition import reanalysis
        return {"record": record, "version": version, "reanalysis": reanalysis(runtime.store, saved_record[2])}, 200

    def source(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .sources import read_source
        if set(query) != {"ref"} or len(query["ref"]) != 1:
            raise ValueError("Source lookup requires an exact source reference")
        return read_source(runtime.store.home, json.loads(query["ref"][0])), 200

    def feedback(self):
        runtime = self.runtime
        path, query = self.path, self.query
        from .context import submit_feedback
        if query:
            raise ValueError("Feedback does not accept URL parameters")
        return submit_feedback(runtime, self._body()), 200

    def query_invocation(self):
        runtime = self.runtime
        path, query = self.path, self.query
        invocation = re.fullmatch(r"/v1/queries/([0-9a-f]{32})(/cancel)?", path)
        from .context import start_query, query_status, cancel_query
        if query:
            raise ValueError("Query invocation does not accept URL parameters")
        if self.command == "GET" and not invocation[2]:
            return query_status(runtime, invocation[1]), 200
        if self.command == "POST":
            body = self._body()
            if invocation[2]:
                return cancel_query(runtime, invocation[1], body["reason"]), 200
            return start_query(runtime, body["session_key"], body["query"], invocation[1], body.get("knowledge_refs"), body.get("relation_refs")), 200
        raise ValueError("Invalid query invocation operation")

    def knowledge(self):
        runtime = self.runtime
        path, query = self.path, self.query
        detail = re.fullmatch(r"/v1/records/(knowledge|relation)/([0-9a-f]{32})", path)
        neighbors = re.fullmatch(r"/v1/knowledge/([0-9a-f]{32})/neighbors", path)
        if not hasattr(runtime, "knowledge_index"):
            runtime.knowledge_index = KnowledgeIndex(runtime.store)
        index = runtime.knowledge_index
        allowed = {"name"} if path == "/v1/knowledge/lookup" else {"version"} if detail else {"direction"}
        if set(query) - allowed or any(len(value) != 1 for value in query.values()):
            raise _APIError(422, "invalid_knowledge_query")
        if detail:
            from .cognition import reanalysis
            return {**index.detail(detail[1], detail[2], version=query.get("version", [None])[0]),
                    "reanalysis": reanalysis(runtime.store, detail[2])}, 200
        if neighbors:
            return index.neighbors(neighbors[1], direction=query.get("direction", ["both"])[0]), 200
        return index.lookup(query.get("name", [""])[0]), 200

    def stop(self):
        runtime = self.runtime
        path, query = self.path, self.query
        with runtime.store.locked():
            runtime._accepting = False
            self.server.stopping.set()
            runtime.wake()
        return {"stopping": True}, 202

    def health(self):
        runtime = self.runtime
        path, query = self.path, self.query
        return {"instance_id": self.server.instance_id, "pid": os.getpid(),
                "protocol": 1, "ready": runtime._accepting and not runtime.store.state.failed}, 200

    def config_read(self):
        runtime = self.runtime
        path, query = self.path, self.query
        current = runtime.config.read()
        current["search_environment_configured"] = bool(getattr(runtime, "search_environment_key", ""))
        current["active_task_versions"] = {task["id"]: task["config"]["version"] for task in runtime.tasks()
                                             if task["status"] in {"running", "validating", "recovering"}}
        return current, 200

    def config_update(self):
        runtime = self.runtime
        path, query = self.path, self.query
        body = self._body()
        current = runtime.update_config(body["expected_version"], body["values"])
        current["search_environment_configured"] = bool(getattr(runtime, "search_environment_key", ""))
        return current, 200

    def task_register(self):
        runtime = self.runtime
        path, query = self.path, self.query
        body = self._body()
        return self._public_task(runtime.register(**body)), 202

    def artifact(self):
        runtime = self.runtime
        path, query = self.path, self.query
        artifact = re.fullmatch(r"/v1/tasks/([0-9a-f]{32})/artifacts", path)
        if set(query) not in ({"field"}, {"attempt"}) or any(len(value) != 1 for value in query.values()):
            raise ValueError("Select one task artifact")
        task = runtime.task(artifact[1])
        if "field" in query:
            field = query["field"][0]
            if field not in {"input_version", "execution_input_version", "prompt_version", "result_version", "model_output_version"}:
                raise ValueError("Artifact is not publicly readable")
            version = task.get(field)
        else:
            version = task.get("generation_attempts", {}).get(_identifier(query["attempt"][0]), {}).get("request_version")
        if not version:
            raise FileNotFoundError("Task artifact not found")
        return {"version": version, "text": runtime.store.read_version(version).decode("utf-8")}, 200

    def task(self):
        runtime = self.runtime
        path, query = self.path, self.query
        task_match = re.fullmatch(r"/v1/tasks/([0-9a-f]{32})(/(?:cancel|retry))?", path)
        if self.command == "GET" and not task_match[2]:
            return self._public_task(runtime.task(task_match[1])), 200
        if self.command == "POST" and task_match[2]:
            body = self._body()
            if task_match[2] == "/retry":
                if query:
                    raise _APIError(422, "invalid_retry_request")
                runtime.retry(task_match[1])
                return self._public_task(runtime.task(task_match[1])), 202
            return self._public_task(runtime.cancel(task_match[1], body["reason"])), 202

    def notification(self):
        runtime = self.runtime
        path, query = self.path, self.query
        runtime.wake()
        return {"received": True}, 202

    def history(self):
        runtime = self.runtime
        path, query = self.path, self.query
        filters = self._list_filters(query, {"module", "kind", "status", "task_id", "session_key", "episode_id", "record_id"})
        modules = {"episode": "M03", "correction": "M03", "knowledge": "M04", "cognition": "M05",
                   "expansion": "M06", "context": "M07", "query": "M07", "screening": "M07"}
        tasks = []
        for task in runtime.tasks():
            if any(task[field] != filters[field] for field in ("kind", "status") if field in filters):
                continue
            if "task_id" in filters and task["id"] != filters["task_id"] or "module" in filters and modules[task["kind"]] != filters["module"]:
                continue
            result = json.loads(runtime.store.read_version(task["result_version"])) if task["result_version"] else {}
            def has(value, name, target):
                if isinstance(value, dict):
                    return value.get(name) == target or any(has(child, name, target) for child in value.values())
                return isinstance(value, list) and any(has(child, name, target) for child in value)
            data = [task["inputs"], result]
            if "session_key" in filters and not has(data, "session_key", filters["session_key"]):
                continue
            if "episode_id" in filters and not (has(data, "episode_id", filters["episode_id"]) or any(
                    ref.get("id") == filters["episode_id"] for ref in task["inputs"].get("episode_refs", []) + result.get("episode_refs", []))):
                continue
            if "record_id" in filters and not (has(data, "id", filters["record_id"]) or has(data, "record_id", filters["record_id"])):
                continue
            tasks.append(self._public_task(task))
        return self._page(tasks, "history", query, filters, key=lambda task: -task["order"]), 200

    def _related(self, query):
        filters = self._list_filters(query, {"record_id", "episode_id"})
        if len(filters) != 1:
            raise ValueError("Choose one record or episode")
        field, identifier = next(iter(filters.items()))
        identifier = _identifier(identifier)
        store = self.runtime.store
        directories = ["episodes"] if field == "episode_id" else ["knowledge", "relations", "hypotheses", "expansions"]
        with store.locked():
            files, _ = store._scan(store.home, allowed=[directory + "/" + identifier + ".json" for directory in directories])
            if not files:
                raise FileNotFoundError("Related record does not exist")
            targets, rows = {identifier}, {}
            completed = [(task, json.loads(store.read_version(task["result_version"]))) for task in self.runtime.tasks()
                if task["result_version"] and (task["status"] == "succeeded" or task.get("commit_id")
                    and store.read_commit(task["commit_id"])["status"] == "committed")]
            def add(kind, ref, record=None):
                record = json.loads(store.read_version(ref["version"])) if record is None else record
                if record.get("id", record.get("round_key")) != ref["id"]:
                    raise ValueError("Related version identity mismatch")
                rows[(kind, ref["id"], ref["version"])] = {"record_kind": kind, **ref, "record": record}
            if field == "episode_id":
                for task, result in completed:
                    if task["kind"] == "knowledge" and identifier in {ref["id"] for ref in task["inputs"].get("episode_refs", [])}:
                        for name, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relation")):
                            for ref in result.get(name, []):
                                targets.add(ref["id"])
                                add(kind, ref)
            candidates = []
            for directory, kind in (("contexts", "context"), ("expansions", "expansion")):
                files, _ = store._scan(store.home, allowed=[directory])
                for info in files.values():
                    record = json.loads(store.read_version(info["version"]))
                    candidates.append((kind, {"id": record["id"], "version": info["version"]}, record))
            for task, result in completed:
                refs = [("context", result["context_ref"])] if task["kind"] == "context" and "context_ref" in result else []
                refs.extend(("expansion", ref) for ref in result.get("expansion_refs", []))
                for kind, ref in refs:
                    candidates.append((kind, ref, json.loads(store.read_version(ref["version"]))))
            for path in sorted((store.home / "events/selections").glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                version = store.put_version(path.read_bytes())
                candidates.append(("selection", {"id": record["round_key"], "version": version}, record))
            for kind, ref, record in candidates:
                if targets.intersection(_referenced_ids(record)):
                    add(kind, ref, record)
            return self._page(sorted(rows.values(), key=lambda item: (item["record_kind"], item["id"], item["version"])),
                "related", query, filters, key=lambda item: item["record_kind"] + "/" + item["id"] + "/" + item["version"])

    @staticmethod
    def _list_filters(query, allowed):
        if set(query) - allowed - {"limit", "cursor"} or any(len(value) != 1 for value in query.values()):
            raise ValueError("Invalid list filters")
        return {name: value[0] for name, value in query.items() if name in allowed}

    @staticmethod
    def _public_task(task):
        return {key: value for key, value in task.items() if key not in
                {"token_hash", "baseline", "directories", "workspace_attributes", "workspace_directory_attributes"}}

    def _page(self, items, collection, query, filters, *, key):
        limit = int(query.get("limit", ["20"])[0])
        if not 1 <= limit <= 100:
            raise ValueError("Page limit must be between 1 and 100")
        items = sorted(items, key=key)
        total = len(items)
        signer = URLSafeSerializer(self.server.token, salt="distillai-list-cursor")
        if "cursor" in query:
            try:
                saved = signer.loads(query["cursor"][0])
            except BadSignature:
                raise ValueError("Invalid page cursor") from None
            if not isinstance(saved, dict) or set(saved) != {"collection", "filters", "after"} or saved["collection"] != collection or saved["filters"] != filters:
                raise ValueError("Page cursor belongs to different filters")
            items = [item for item in items if key(item) > saved["after"]]
        page = items[:limit]
        cursor = signer.dumps({"collection": collection, "filters": filters, "after": key(page[-1])}) if len(items) > limit else None
        return {"items": page, "next_cursor": cursor, "total": total}


def get_runtime(request: Request):
    return request.app.state.control.runtime


async def get_api(request: Request, runtime=Depends(get_runtime)):
    control = request.app.state.control
    if request.headers.get("host") != control.url.removeprefix("http://"):
        raise _APIError(403, "invalid_host")
    if request.headers.get("origin") not in (None, control.url):
        raise _APIError(403, "invalid_origin")
    if request.url.path.startswith("//"):
        raise _APIError(400, "invalid_path")
    if "identifier" in request.path_params:
        try:
            _identifier(request.path_params["identifier"])
        except ValueError:
            raise _APIError(404, "not_found") from None
    if runtime.store.state.failed and request.url.path not in {"/v1/health", "/internal/stop"}:
        raise _APIError(503, "control_state_unavailable")
    request.state.web_session = None
    token = request.headers.get("authorization", "")
    if request.url.path != "/web/bootstrap" and not secrets.compare_digest(token, "Bearer " + control.token):
        if token or request.url.path.startswith("/internal/"):
            raise _APIError(401, "unauthorized")
        session = control.web_sessions.get(request.cookies.get("distillai_session", ""))
        if session is None:
            raise _APIError(401, "browser_session_required")
        if request.method not in {"GET", "HEAD"} and (request.headers.get("origin") != control.url or not secrets.compare_digest(request.headers.get("x-distillai-csrf", ""), session["csrf_token"])):
            raise _APIError(403, "web_csrf_required")
        request.state.web_session = session
    body = {}
    if request.method in {"POST", "PUT"}:
        limit = 512 * 1024
        lengths = request.headers.getlist("content-length")
        if request.headers.get("transfer-encoding") or len(lengths) != 1:
            raise _APIError(400, "invalid_framing")
        try:
            length = int(lengths[0])
        except ValueError:
            raise _APIError(400, "invalid_length") from None
        if length < 0:
            raise _APIError(400, "invalid_length")
        if length > limit:
            raise _APIError(413, "body_too_large")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise _APIError(415, "expected_json")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise _APIError(413, "body_too_large")
        if len(raw) != length:
            raise _APIError(400, "incomplete_body")
        def invalid_constant(value):
            raise ValueError("Nonfinite JSON number")
        body = json.loads(raw.decode("utf-8"), parse_constant=invalid_constant)
        if not isinstance(body, dict):
            raise _APIError(422, "expected_object")
    return _API(request, body, runtime)


def create_app(runtime, *, control=None, lifespan=None):
    @asynccontextmanager
    async def default_lifespan(app):
        yield

    app = FastAPI(lifespan=lifespan or default_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.control = control or _Control(runtime)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        if response.status_code == 400 and request.headers.get("host", "").split(":")[0] != "127.0.0.1":
            response = JSONResponse({"error": {"code": "invalid_host"}}, status_code=403)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def handle_error(request, error):
        if isinstance(error, _APIError):
            status, detail = error.status, {"code": error.code}
        elif isinstance(error, ConfigError):
            status, detail = 422, {"code": "invalid_config", "fields": error.fields}
        else:
            status, code = next(((status, code) for kind, status, code in (
                (ConflictError, 409, "conflict"), (IndexNotReady, 503, "index_not_ready"),
                (FileNotFoundError, 404, "not_found"), (KeyError, 404, "not_found"),
                (ValueError, 422, "invalid_request"), (TypeError, 422, "invalid_request"),
                (RequestValidationError, 422, "invalid_request"),
                (sqlite3.Error, 503, "control_state_unavailable")) if isinstance(error, kind)), (500, "internal_error"))
            detail = {"code": code}
        return JSONResponse({"error": detail}, status_code=status)

    for error in (_APIError, ConfigError, ConflictError, IndexNotReady, FileNotFoundError, KeyError, ValueError, TypeError, RequestValidationError, sqlite3.Error, Exception):
        app.add_exception_handler(error, handle_error)

    def endpoint(name, body_model=None, *, error_code="invalid_request"):
        adapter = TypeAdapter(body_model) if body_model is not None else None
        def invoke(api=Depends(get_api)):
            if adapter is not None and api.command in {"POST", "PUT"}:
                try:
                    adapter.validate_python(api.body)
                except ValidationError as error:
                    code = error_code
                    if name == "task_register" and any(item["type"] == "extra_forbidden" and len(item["loc"]) == 1
                            for item in error.errors(include_input=False, include_url=False)):
                        code = "invalid_task_request"
                    raise _APIError(422, code) from None
            with api.runtime.store.locked():
                if api.runtime.store.state.failed and name not in {"health", "stop"}:
                    raise _APIError(503, "control_state_unavailable")
                result, status = getattr(api, name)()
            return JSONResponse(result, status_code=status)
        invoke.__name__ = name
        return invoke

    app.add_api_route('/v1/related', endpoint('related'), methods=['GET'])
    app.add_api_route('/v1/reanalysis-requests', endpoint('reanalysis', ReanalysisArgs), methods=['POST'])
    app.add_api_route('/v1/cognition-corrections', endpoint('cognition_correction', CognitionCorrectionArgs), methods=['POST'])
    app.add_api_route('/v1/episode-corrections', endpoint('episode_correction', EpisodeCorrectionArgs), methods=['POST'])
    app.add_api_route('/v1/expansion-status', endpoint('expansion_status'), methods=['GET'])
    app.add_api_route('/v1/expansion-requests', endpoint('expansion_request', ExpansionRequestArgs), methods=['POST'])
    app.add_api_route('/v1/knowledge-edits', endpoint('knowledge_edit', EditArgs), methods=['POST'])
    app.add_api_route('/internal/web/bootstrap', endpoint('bootstrap', EmptyArgs), methods=['POST'])
    app.add_api_route('/v1/web/session', endpoint('web_session'), methods=['GET'])
    app.add_api_route('/v1/episodes', endpoint('collection'), methods=['GET'])
    app.add_api_route('/v1/knowledge', endpoint('collection'), methods=['GET'])
    app.add_api_route('/v1/relations', endpoint('collection'), methods=['GET'])
    app.add_api_route('/v1/hypotheses', endpoint('collection'), methods=['GET'])
    app.add_api_route('/v1/expansions', endpoint('collection'), methods=['GET'])
    app.add_api_route('/v1/episodes/{identifier}', endpoint('saved_record'), methods=['GET'])
    app.add_api_route('/v1/hypotheses/{identifier}', endpoint('saved_record'), methods=['GET'])
    app.add_api_route('/v1/expansions/{identifier}', endpoint('saved_record'), methods=['GET'])
    app.add_api_route('/v1/sources', endpoint('source'), methods=['GET'])
    app.add_api_route('/v1/feedback', endpoint('feedback', FeedbackArgs), methods=['POST'])
    app.add_api_route('/v1/queries/{identifier}', endpoint('query_invocation', QueryArgs), methods=['GET', 'POST'])
    app.add_api_route('/v1/queries/{identifier}/cancel', endpoint('query_invocation', ReasonArgs), methods=['POST'])
    app.add_api_route('/v1/knowledge/lookup', endpoint('knowledge'), methods=['GET'])
    app.add_api_route('/v1/records/knowledge/{identifier}', endpoint('knowledge'), methods=['GET'])
    app.add_api_route('/v1/records/relation/{identifier}', endpoint('knowledge'), methods=['GET'])
    app.add_api_route('/v1/knowledge/{identifier}/neighbors', endpoint('knowledge'), methods=['GET'])
    app.add_api_route('/internal/stop', endpoint('stop', EmptyArgs, error_code='invalid_stop_request'), methods=['POST'])
    app.add_api_route('/v1/health', endpoint('health'), methods=['GET'])
    app.add_api_route('/v1/config', endpoint('config_read'), methods=['GET'])
    app.add_api_route('/v1/config', endpoint('config_update', UpdateArgs, error_code='invalid_config_request'), methods=['PUT'])
    app.add_api_route('/v1/tasks', endpoint('task_register', RegisterArgs), methods=['POST'])
    app.add_api_route('/v1/tasks/{identifier}/artifacts', endpoint('artifact'), methods=['GET'])
    app.add_api_route('/v1/tasks/{identifier}', endpoint('task'), methods=['GET'])
    app.add_api_route('/v1/tasks/{identifier}/cancel', endpoint('task', ReasonArgs, error_code='invalid_cancel_request'), methods=['POST'])
    app.add_api_route('/v1/tasks/{identifier}/retry', endpoint('task', EmptyArgs, error_code='invalid_retry_request'), methods=['POST'])
    app.add_api_route('/v1/material-notifications', endpoint('notification', QueueLocator, error_code='invalid_material_notification'), methods=['POST'])
    app.add_api_route('/v1/history', endpoint('history'), methods=['GET'])

    @app.get("/web/bootstrap")
    def exchange(api=Depends(get_api)):
        if set(api.query) != {"token"} or len(api.query["token"]) != 1:
            raise _APIError(401, "invalid_web_bootstrap")
        control = api.server
        with control.runtime.store.locked():
            expires = control.web_bootstraps.pop(api.query["token"][0], 0)
            if expires <= time.monotonic():
                raise _APIError(401, "invalid_web_bootstrap")
            identifier = secrets.token_urlsafe(32)
            control.web_sessions[identifier] = {"csrf_token": secrets.token_urlsafe(32)}
        response = RedirectResponse("/", status_code=303, headers={"Referrer-Policy": "no-referrer"})
        response.set_cookie("distillai_session", identifier, httponly=True, samesite="strict")
        return response

    def static_asset(api=Depends(get_api)):
        if api.query:
            raise _APIError(404, "not_found")
        name, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/styles.css": ("styles.css", "text/css")}[api.path]
        return FileResponse(Path(__file__).parent / "web" / name, media_type=mime,
            headers={"Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})

    for route in ("/", "/app.js", "/styles.css"):
        app.add_api_route(route, static_asset, methods=["GET"])



    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    def unknown(api=Depends(get_api)):
        raise _APIError(404, "not_found")

    return app
