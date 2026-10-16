"""Authenticated loopback control API and task-scoped model forwarding."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from .config import ConfigError
from .runtime import BudgetError, CancelledError
from .storage import ConflictError, _identifier
from .knowledge import KnowledgeIndex, IndexNotReady


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        return None


def _history_request(body):
    def visible(value):
        if isinstance(value, list):
            return [visible(item) for item in value if not isinstance(item, dict) or item.get("type") not in
                    {"thinking", "reasoning", "analysis", "redacted_thinking"}]
        if isinstance(value, dict):
            return {name: visible(item) for name, item in value.items() if name not in
                    {"reasoning_content", "reasoning", "thinking", "analysis", "signature"}}
        return value
    return visible({name: item for name, item in body.items() if name in
                    {"model", "messages", "tools", "tool_choice", "parallel_tool_calls", "stream", "stream_options",
                     "max_tokens", "temperature", "top_p", "stop", "response_format"}})


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


class _APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class BackendServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, runtime, *, instance_id=None, token=None):
        self.runtime = runtime
        self.instance_id = instance_id or uuid.uuid4().hex
        self.token = token or secrets.token_urlsafe(32)
        self.opener = build_opener(_NoRedirect())
        self.stopping = threading.Event()
        self.web_bootstraps = {}
        self.web_sessions = {}
        super().__init__(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self.server_port}"

    def model_base(self, task_id):
        return self.url + "/internal/tasks/" + _identifier(task_id) + "/v1"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def _json(self, status, record):
        if getattr(self, "_responded", False):
            self.close_connection = True
            return
        self._responded = True
        data = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self):
        self._responded = False
        try:
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                raise _APIError(403, "invalid_host")
            if self.headers.get("Origin") not in (None, self.server.url):
                raise _APIError(403, "invalid_origin")
            if not self.path.startswith("/") or self.path.startswith("//"):
                raise _APIError(400, "invalid_path")
            parts = urlsplit(self.path)
            if parts.path == "/web/bootstrap":
                self._web_exchange(parse_qs(parts.query))
                return
            token = self.headers.get("Authorization", "")
            boundary = re.fullmatch(r"/internal/tasks/([0-9a-f]{32})/tools/(evaluate_episode_boundary|evaluate_episode_revision|read_episode_source|new_record_id|audit_reads|web_search|fetch_page)", parts.path)
            if boundary:
                if self.command != "POST" or self.headers.get("Origin") is not None:
                    raise _APIError(403, "boundary_tool_request_forbidden")
                if not token.startswith("Bearer "):
                    raise _APIError(401, "unauthorized")
                try:
                    self.server.runtime.verify_token(boundary[1], token[7:])
                except (PermissionError, CancelledError):
                    raise _APIError(401, "invalid_task_authorization") from None
                try:
                    body = self._body()
                    if boundary[2] == "evaluate_episode_boundary":
                        from .episode import evaluate
                        result = evaluate(self.server.runtime, boundary[1], body)
                    elif boundary[2] in {"evaluate_episode_revision", "read_episode_source"}:
                        from .episode import evaluate_revision, read_episode_source
                        result = (evaluate_revision if boundary[2] == "evaluate_episode_revision" else read_episode_source)(self.server.runtime, boundary[1], body)
                    elif boundary[2] == "audit_reads":
                        from .context import audit_reads
                        if not body or set(body) - {"records", "sources"}:
                            raise ValueError("Read audit requires record or source references")
                        result = audit_reads(self.server.runtime, boundary[1], body.get("records", []), body.get("sources", []))
                    elif boundary[2] in {"web_search", "fetch_page"}:
                        from .expansion import web_tool
                        result = web_tool(self.server.runtime, boundary[1], boundary[2], body)
                    else:
                        kind = body.get("record_kind")
                        if kind == "candidate":
                            from .context import allocate_candidate
                            if set(body) != {"record_kind"}:
                                raise ValueError("Candidate allocation requires only record_kind")
                            result = allocate_candidate(self.server.runtime, boundary[1])
                        elif kind in {"observation", "hypothesis"}:
                            from .cognition import allocate_id
                            if set(body) != ({"record_kind", "source_refs"} if kind == "observation" else {"record_kind"}):
                                raise ValueError("Observation IDs require source_refs; hypothesis IDs require only record_kind")
                            result = allocate_id(self.server.runtime, boundary[1], kind, body.get("source_refs"))
                        else:
                            from .knowledge import allocate_id
                            if set(body) != {"record_kind"}:
                                raise ValueError("Record allocation requires record_kind")
                            result = allocate_id(self.server.runtime, boundary[1], kind)
                except ValueError as error:
                    self._json(422, {"error": {"code": "invalid_boundary_evaluation" if boundary[2] == "evaluate_episode_boundary" else "invalid_record_allocation", "message": str(error)}})
                    return
                self._json(200, result)
                return
            internal = re.fullmatch(r"/internal/tasks/([0-9a-f]{32})/v1/(chat/completions|models)", parts.path)
            if internal:
                self._model(internal[1], internal[2], token)
                return
            self._web_session = None
            if not secrets.compare_digest(token, "Bearer " + self.server.token):
                if token or parts.path.startswith("/internal/"):
                    raise _APIError(401, "unauthorized")
                self._authorize_web()
            if parts.path in {"/", "/app.js", "/styles.css"}:
                if self.command != "GET" or parts.query:
                    raise _APIError(404, "not_found")
                self._static(parts.path)
                return
            result, status = self._control(parts.path, parse_qs(parts.query))
            self._json(status, result)
        except _APIError as exc:
            self.close_connection = True
            self._json(exc.status, {"error": {"code": exc.code}})
        except ConfigError as exc:
            self._json(422, {"error": {"code": "invalid_config", "fields": exc.fields}})
        except ConflictError:
            self._json(409, {"error": {"code": "conflict"}})
        except IndexNotReady:
            self._json(503, {"error": {"code": "index_not_ready"}})
        except (FileNotFoundError, KeyError):
            self._json(404, {"error": {"code": "not_found"}})
        except (ValueError, TypeError, UnicodeError):
            self._json(422, {"error": {"code": "invalid_request"}})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            self.close_connection = True
            self._json(500, {"error": {"code": "internal_error"}})

    def _body(self, limit=512 * 1024):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise _APIError(400, "invalid_framing")
        try:
            length = int(lengths[0])
        except ValueError:
            raise _APIError(400, "invalid_length") from None
        if length < 0:
            raise _APIError(400, "invalid_length")
        if length > limit:
            # Drain a bounded body so Windows can deliver 413 before closing the socket.
            remaining = min(length, 8 * 1024 * 1024)
            while remaining:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise _APIError(413, "body_too_large")
        if self.headers.get_content_type() != "application/json":
            raise _APIError(415, "expected_json")
        data = self.rfile.read(length)
        if len(data) != length:
            raise _APIError(400, "incomplete_body")

        def invalid_constant(value):
            raise ValueError("Nonfinite JSON number")

        body = json.loads(data.decode("utf-8"), parse_constant=invalid_constant)
        if not isinstance(body, dict):
            raise _APIError(422, "expected_object")
        return body

    def _static(self, path):
        name, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/styles.css": ("styles.css", "text/css")}[path]
        data = (Path(__file__).parent / "web" / name).read_bytes()
        self._responded = True
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def _control(self, path, query):
        runtime = self.server.runtime
        if path == "/v1/related" and self.command == "GET":
            return self._related(query), 200
        if path == "/v1/reanalysis-requests" and self.command == "POST":
            from .cognition import request_reanalysis
            if query:
                raise ValueError("Reanalysis does not accept URL parameters")
            task = request_reanalysis(runtime, self._body())
            return {"task_id": task["id"], "status": task["status"]}, 202
        if path == "/v1/cognition-corrections" and self.command == "POST":
            from .cognition import register_correction
            if query:
                raise ValueError("Cognition correction does not accept URL parameters")
            task = register_correction(runtime, self._body())
            return {"task_id": task["id"], "status": task["status"]}, 202
        if path == "/v1/episode-corrections" and self.command == "POST":
            from .episode import register_correction
            if query:
                raise ValueError("Ownership correction does not accept URL parameters")
            task = register_correction(runtime, self._body())
            return {"task_id": task["id"], "status": task["status"]}, 202
        if path == "/v1/expansion-status" and self.command == "GET":
            from .expansion import status
            return status(runtime), 200
        if path == "/v1/expansion-requests" and self.command == "POST":
            from .expansion import register_request
            if query:
                raise ValueError("Exploration request does not accept URL parameters")
            return self._public_task(register_request(runtime, self._body())), 202
        if path == "/v1/knowledge-edits" and self.command == "POST":
            from .knowledge import register_user_edit
            if query:
                raise ValueError("Content edit does not accept URL parameters")
            task = register_user_edit(runtime, self._body())
            return {"task_id": task["id"], "status": task["status"]}, 202
        if self.command == "POST" and path == "/internal/web/bootstrap":
            if query or self._body():
                raise ValueError("Web bootstrap request has no parameters")
            with runtime.store.locked():
                self.server.web_bootstraps = {key: expiry for key, expiry in self.server.web_bootstraps.items() if expiry > time.monotonic()}
                token = secrets.token_urlsafe(32)
                self.server.web_bootstraps[token] = time.monotonic() + 120
            return {"url": self.server.url + "/web/bootstrap?token=" + token}, 200
        if self.command == "GET" and path == "/v1/web/session":
            if query or self._web_session is None:
                raise _APIError(401, "browser_session_required")
            return {"csrf_token": self._web_session["csrf_token"]}, 200
        collections = {"/v1/episodes": "episodes", "/v1/knowledge": "knowledge", "/v1/relations": "relations",
                       "/v1/hypotheses": "hypotheses", "/v1/expansions": "expansions"}
        if self.command == "GET" and path in collections:
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
        saved_record = re.fullmatch(r"/v1/(episodes|hypotheses|expansions)/([0-9a-f]{32})", path)
        if self.command == "GET" and saved_record:
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
        if self.command == "GET" and path == "/v1/sources":
            from .sources import read_source
            if set(query) != {"ref"} or len(query["ref"]) != 1:
                raise ValueError("Source lookup requires an exact source reference")
            return read_source(runtime.store.home, json.loads(query["ref"][0])), 200
        if path == "/v1/feedback" and self.command == "POST":
            from .context import submit_feedback
            if query:
                raise ValueError("Feedback does not accept URL parameters")
            return submit_feedback(runtime, self._body()), 200
        invocation = re.fullmatch(r"/v1/queries/([0-9a-f]{32})(/cancel)?", path)
        if invocation:
            from .context import start_query, query_status, cancel_query
            if query:
                raise ValueError("Query invocation does not accept URL parameters")
            if self.command == "GET" and not invocation[2]:
                return query_status(runtime, invocation[1]), 200
            if self.command == "POST":
                body = self._body()
                if invocation[2] and set(body) == {"reason"}:
                    return cancel_query(runtime, invocation[1], body["reason"]), 200
                if not invocation[2] and {"session_key", "query"}.issubset(body) and not set(body) - {"session_key", "query", "knowledge_refs", "relation_refs"}:
                    return start_query(runtime, body["session_key"], body["query"], invocation[1], body.get("knowledge_refs"), body.get("relation_refs")), 200
            raise ValueError("Invalid query invocation operation")
        detail = re.fullmatch(r"/v1/records/(knowledge|relation)/([0-9a-f]{32})", path)
        neighbors = re.fullmatch(r"/v1/knowledge/([0-9a-f]{32})/neighbors", path)
        if self.command == "GET" and (path == "/v1/knowledge/lookup" or detail or neighbors):
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
        if self.command == "POST" and path == "/internal/stop":
            if self._body():
                raise _APIError(422, "invalid_stop_request")
            with runtime.store.locked():
                runtime._accepting = False
                self.server.stopping.set()
                runtime._wake.set()
            return {"stopping": True}, 202
        if self.command == "GET" and path == "/v1/health":
            return {"instance_id": self.server.instance_id, "pid": os.getpid(),
                    "protocol": 1, "ready": runtime._accepting}, 200
        if self.command == "GET" and path == "/v1/config":
            current = runtime.config.read()
            current["search_environment_configured"] = bool(getattr(runtime, "search_environment_key", ""))
            current["active_task_versions"] = {task["id"]: task["config"]["version"] for task in runtime.tasks()
                                                 if task["status"] in {"running", "validating", "recovering"}}
            return current, 200
        if self.command == "PUT" and path == "/v1/config":
            body = self._body()
            if set(body) != {"expected_version", "values"}:
                raise _APIError(422, "invalid_config_request")
            current = runtime.update_config(body["expected_version"], body["values"])
            current["search_environment_configured"] = bool(getattr(runtime, "search_environment_key", ""))
            return current, 200
        if self.command == "POST" and path == "/v1/tasks":
            body = self._body()
            if set(body) - {"kind", "inputs", "trigger", "scope", "dependencies"}:
                raise _APIError(422, "invalid_task_request")
            return self._public_task(runtime.register(**body)), 202
        task_match = re.fullmatch(r"/v1/tasks/([0-9a-f]{32})(/(?:cancel|retry))?", path)
        artifact = re.fullmatch(r"/v1/tasks/([0-9a-f]{32})/artifacts", path)
        if artifact and self.command == "GET":
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
        if task_match:
            if self.command == "GET" and not task_match[2]:
                return self._public_task(runtime.task(task_match[1])), 200
            if self.command == "POST" and task_match[2]:
                body = self._body()
                if task_match[2] == "/retry":
                    if body or query:
                        raise _APIError(422, "invalid_retry_request")
                    runtime.retry(task_match[1])
                    return self._public_task(runtime.task(task_match[1])), 202
                if set(body) != {"reason"} or not isinstance(body["reason"], str):
                    raise _APIError(422, "invalid_cancel_request")
                return self._public_task(runtime.cancel(task_match[1], body["reason"])), 202
        if self.command == "POST" and path == "/v1/material-notifications":
            body = self._body()
            if set(body) != {"connector", "session_key"} or body["connector"] != "codex" or not isinstance(body["session_key"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", body["session_key"]):
                raise _APIError(422, "invalid_material_notification")
            runtime._wake.set()
            return {"received": True}, 202
        if self.command == "GET" and path == "/v1/history":
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
        raise _APIError(404, "not_found")

    def _related(self, query):
        filters = self._list_filters(query, {"record_id", "episode_id"})
        if len(filters) != 1:
            raise ValueError("Choose one record or episode")
        field, identifier = next(iter(filters.items()))
        identifier = _identifier(identifier)
        store = self.server.runtime.store
        directories = ["episodes"] if field == "episode_id" else ["knowledge", "relations", "hypotheses", "expansions"]
        with store.locked():
            files, _ = store._scan(store.home, allowed=[directory + "/" + identifier + ".json" for directory in directories])
            if not files:
                raise FileNotFoundError("Related record does not exist")
            targets, rows = {identifier}, {}
            completed = [(task, json.loads(store.read_version(task["result_version"]))) for task in self.server.runtime.tasks()
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

    def _web_exchange(self, query):
        if self.command != "GET" or set(query) != {"token"} or len(query["token"]) != 1:
            raise _APIError(401, "invalid_web_bootstrap")
        with self.server.runtime.store.locked():
            expires = self.server.web_bootstraps.pop(query["token"][0], 0)
            if expires <= time.monotonic():
                raise _APIError(401, "invalid_web_bootstrap")
            identifier = secrets.token_urlsafe(32)
            self.server.web_sessions[identifier] = {"csrf_token": secrets.token_urlsafe(32)}
        self._responded = True
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "distillai_session=" + identifier + "; Path=/; HttpOnly; SameSite=Strict")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _authorize_web(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            raise _APIError(401, "invalid_browser_session") from None
        identifier = cookies.get("distillai_session")
        with self.server.runtime.store.locked():
            session = self.server.web_sessions.get(identifier.value) if identifier else None
        if session is None:
            raise _APIError(401, "browser_session_required")
        if self.command not in {"GET", "HEAD"}:
            if (self.headers.get("Origin") != self.server.url
                    or not secrets.compare_digest(self.headers.get("X-DistillAI-CSRF", ""), session["csrf_token"])):
                raise _APIError(403, "web_csrf_required")
        self._web_session = session

    @staticmethod
    def _list_filters(query, allowed):
        if set(query) - allowed - {"limit", "cursor"} or any(len(value) != 1 for value in query.values()):
            raise ValueError("Invalid list filters")
        return {name: value[0] for name, value in query.items() if name in allowed}

    def _page(self, items, collection, query, filters, *, key):
        limit = int(query.get("limit", ["20"])[0])
        if not 1 <= limit <= 100:
            raise ValueError("Page limit must be between 1 and 100")
        items = sorted(items, key=key)
        total = len(items)
        if "cursor" in query:
            payload, signature = query["cursor"][0].split(".", 1)
            digest = hmac.new(self.server.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not secrets.compare_digest(digest, signature):
                raise ValueError("Invalid page cursor")
            saved = json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True))
            if set(saved) != {"collection", "filters", "after"} or saved["collection"] != collection or saved["filters"] != filters:
                raise ValueError("Page cursor belongs to different filters")
            items = [item for item in items if key(item) > saved["after"]]
        page = items[:limit]
        cursor = None
        if len(items) > limit:
            data = json.dumps({"collection": collection, "filters": filters, "after": key(page[-1])}, sort_keys=True).encode()
            payload = base64.urlsafe_b64encode(data).decode().rstrip("=")
            cursor = payload + "." + hmac.new(self.server.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return {"items": page, "next_cursor": cursor, "total": total}

    @staticmethod
    def _public_task(task):
        return {key: value for key, value in task.items() if key not in
                {"token_hash", "baseline", "directories", "workspace_attributes", "workspace_directory_attributes"}}

    def _model(self, task_id, route, authorization):
        if self.headers.get("Origin") is not None:
            raise _APIError(403, "model_origin_forbidden")
        if not authorization.startswith("Bearer "):
            raise _APIError(401, "unauthorized")
        token = authorization[7:]
        runtime = self.server.runtime
        try:
            task = runtime.verify_token(task_id, token)
        except (PermissionError, CancelledError):
            raise _APIError(401, "invalid_task_authorization") from None
        llm = runtime.config.private(task["config"]["version"])["values"]["llm"]
        if not llm["base_url"] or not llm["model"]:
            raise _APIError(409, "model_not_configured")
        data = None
        attempt_id = None
        if self.command == "POST" and route == "chat/completions":
            body = self._body(8 * 1024 * 1024)
            if body.get("model") != llm["model"] or not isinstance(body.get("messages"), list) or not body["messages"]:
                raise _APIError(400, "invalid_model_request")
            body.update(llm["parameters"])
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            snapshot = _history_request(body)
            request_version = runtime.store.put_version(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            attempt_id = uuid.uuid4().hex
            try:
                runtime.reserve_generation(task_id, token, attempt_id=attempt_id, request_version=request_version)
            except BudgetError:
                raise _APIError(400, "budget_exhausted") from None
            except (PermissionError, CancelledError):
                raise _APIError(401, "invalid_task_authorization") from None
        elif not (self.command == "GET" and route == "models"):
            raise _APIError(404, "not_found")
        url = llm["base_url"].rstrip("/") + "/" + route
        headers = {"Content-Type": "application/json"}
        if llm["api_key"]:
            headers["Authorization"] = "Bearer " + llm["api_key"]
        request = Request(url, data=data, method=self.command, headers=headers)
        try:
            upstream = self.server.opener.open(request, timeout=300)
        except HTTPError as exc:
            status = exc.code if 400 <= exc.code <= 599 else 502
            exc.close()
            raise _APIError(status, "upstream_model_error") from None
        except URLError as exc:
            if attempt_id is not None and isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror)):
                runtime.release_unissued_generation(task_id, attempt_id)
            raise _APIError(502, "upstream_model_unavailable") from None
        except OSError:
            raise _APIError(502, "upstream_model_unavailable") from None
        with upstream:
            content_type = upstream.headers.get_content_type()
            if content_type not in {"application/json", "text/event-stream"}:
                raise _APIError(502, "unexpected_model_content_type")
            self._responded = True
            self.send_response(upstream.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            size = 0
            while chunk := upstream.read1(65536):
                size += len(chunk)
                if size > 16 * 1024 * 1024:
                    return
                self.wfile.write(chunk)
                self.wfile.flush()
