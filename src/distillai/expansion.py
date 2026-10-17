"""Periodic, version-bound exploration with controller-owned Tavily tools."""
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import socket
import time
import uuid
from urllib.parse import urlsplit
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from .knowledge import _snapshot, _references, _text
from .sources import DraftRecordRef, Identifier, NonblankText, RecordRef, SourceRef, now as timestamp, read_source, record_submission
from .storage import atomic_json, _hash, _identifier


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class SearchArgs(TypedDict):
    query: Annotated[NonblankText, Field(max_length=2000)]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class FetchArgs(TypedDict):
    url: Annotated[str, Field(max_length=8192)]


SEARCH_ARGS = TypeAdapter(SearchArgs)
FETCH_ARGS = TypeAdapter(FetchArgs)


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class CandidateEndpoint(TypedDict):
    candidate: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class OpenQuestion(TypedDict):
    statement: NonblankText
    source_refs: list[SourceRef]
    verification: NotRequired[Any]
    conditions: NotRequired[Any]
    status: NotRequired[Any]
    value: NotRequired[Any]
    source: NotRequired[Any]
    target: NotRequired[Any]


class Claim(OpenQuestion):
    verification: NonblankText
    status: Literal["supported", "conflicting", "unverified"]


class Connection(Claim):
    source: RecordRef | CandidateEndpoint
    target: RecordRef | CandidateEndpoint


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ExpansionRecord(TypedDict):
    id: Identifier
    input_refs: list[RecordRef]
    question: NonblankText
    reason: NonblankText
    claims: list[Claim]
    proposed_connections: list[Connection]
    open_questions: list[OpenQuestion]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ExpansionResult(TypedDict):
    expansion_refs: list[DraftRecordRef]
    reason: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class RequestArgs(TypedDict):
    client_request_id: Annotated[NonblankText, Field(max_length=128)]
    knowledge_refs: Annotated[list[RecordRef], Field(min_length=1)]
    question: NonblankText
    reason: NonblankText


EXPANSION_RECORD = TypeAdapter(ExpansionRecord)
EXPANSION_RESULT = TypeAdapter(ExpansionResult)
REQUEST_ARGS = TypeAdapter(RequestArgs)


def _url(value):
    if not isinstance(value, str) or len(value) > 8192 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError("Expected a public HTTP(S) URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Expected a public HTTP(S) URL without credentials")
    parsed.port
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except OSError as error:
        raise ValueError("Source hostname cannot be resolved") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Private or local source URLs are not supported")
    return value


def prepare_web_call(runtime, task_id, tool, args):
    if tool not in {"web_search", "fetch_page"}:
        raise ValueError("Invalid web tool")
    if tool == "web_search":
        SEARCH_ARGS.validate_python(args)
        endpoint, payload = "search", {"query": args["query"], "max_results": 5, "include_raw_content": False, "include_images": False}
    else:
        FETCH_ARGS.validate_python(args)
        endpoint, payload = "extract", {"urls": [_url(args["url"])], "include_images": False}
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "expansion" or task["status"] != "running":
            raise ValueError("Only running M06 tasks may search or read the web")
    return {"endpoint": endpoint, "payload": payload}


def web_tool(runtime, task_id, tool, args, response):
    prepare_web_call(runtime, task_id, tool, args)
    try:
        if isinstance(response, dict) and set(response) == {"error"}:
            error = response["error"]
            code = error.get("code")
            if code not in {"quota_or_rate_limit", "search_failed", "page_read_failed"} or set(error) - {"code", "http_status"}:
                raise ValueError("Invalid web error")
            result = {"error": dict(error)}
        elif tool == "web_search":
            if not isinstance(response, dict) or response.get("success") is not True or not isinstance(response.get("data", {}).get("web"), list):
                raise ValueError("Invalid search result")
            result = {"results": response["data"]["web"], "content_kind": "search_snippets", "searched_at": timestamp()}
        else:
            document = next((item for item in response if isinstance(item, dict) and item.get("url") == args["url"] and not item.get("error")), None) if isinstance(response, list) else None
            if document is None or not _text(document.get("content")):
                result = {"error": {"code": "page_read_failed"}, "url": args["url"]}
            else:
                text = document["content"][:16000]
                record = {"id": uuid.uuid4().hex, "source_kind": "external", "task_id": task_id,
                          "url": args["url"], "title": str(document.get("title", "")), "read_at": timestamp(),
                          "text": text, "truncated": len(text) < len(document["content"]), "provider": "tavily"}
                with runtime.store.locked():
                    runtime._live(task_id)  # A late network response must not publish after cancellation.
                    folder = runtime.store.home / "external-sources"
                    folder.mkdir(exist_ok=True)
                    path = folder / (record["id"] + ".json")
                    atomic_json(path, record)
                    ref = {"source_kind": "external", "id": record["id"], "version": runtime.store.put_version(path.read_bytes())}
                    task = runtime._live(task_id)
                    task.setdefault("external_source_refs", []).append(ref)
                    runtime._save(task)
                result = {"source_ref": ref, "url": record["url"], "title": record["title"], "text": text,
                          "read_at": record["read_at"], "truncated": record["truncated"], "content_kind": "extracted_excerpt"}
    except (OSError, ValueError, KeyError, TypeError):
        result = {"error": {"code": "search_failed" if tool == "web_search" else "page_read_failed"}}
    with runtime.store.locked():
        task = runtime._live(task_id)
        key = runtime.config.private(task["config"]["version"])["values"]["search"]["api_key"] or getattr(runtime, "search_environment_key", "")
        version = runtime.store.put_version(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        task.setdefault("web_calls", []).append({"tool": tool, "arguments": args, "result_version": version,
                                                "access_mode": "keyed" if key else "keyless"})
        runtime._save(task)
    return result


def _state(runtime):
    path = runtime.store.home / "events" / "expansion-coverage.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "completed": {}, "waiting_since": None, "last_scheduled_at": None, "pending_task_id": None}


def status(runtime):
    with runtime.store.locked():
        state = _state(runtime)
        state["unavailable_reason"] = None if getattr(runtime, "expansion_ready", False) else "g3_validation_pending"
        llm = runtime.config.read()["values"]["llm"]
        if state["unavailable_reason"] is None and not (llm["base_url"] and llm["model"]):
            state["unavailable_reason"] = "model_not_configured"
        return state


def tick(runtime, *, now=None):
    now = time.time() if now is None else now
    with runtime.store.locked():
        state = _state(runtime)
        if status(runtime)["unavailable_reason"]:
            return None
        if state["pending_task_id"]:
            pending = runtime.task(state["pending_task_id"])
            if pending["status"] == "cancelled" and pending["cancel_reason"] in {"input_or_permission_changed", "Fixed exploration input was superseded"}:
                state["pending_task_id"] = None
                state["waiting_since"] = now
                atomic_json(runtime.store.home / "events" / "expansion-coverage.json", state)
                return None
            return pending
        path = runtime.store.home / "events" / "expansion-coverage.json"
        if state["waiting_since"] is None:
            state["waiting_since"] = now
            atomic_json(path, state)
            return None
        config = runtime.config.read()["values"]["expansion"]
        if now - state["waiting_since"] < config["interval_seconds"]:
            return None
        records, versions = _snapshot(runtime.store)
        selected, bases = [], {}
        identifiers = sorted(records["knowledge"])
        cursor = state.get("cursor", "")
        for identifier in [item for item in identifiers if item > cursor] + [item for item in identifiers if item <= cursor]:
            related = sorted((rid, versions[rid]) for rid, relation in records["relations"].items()
                             if identifier in (relation["source_knowledge_id"], relation["target_knowledge_id"]))
            basis = _hash(json.dumps([versions[identifier], related]).encode("utf-8"))
            if state["completed"].get(identifier) != basis:
                selected.append({"id": identifier, "version": versions[identifier]})
                bases[identifier] = basis
            if len(selected) == config["batch_size"]:
                break
        state["waiting_since"] = now
        if not selected:
            atomic_json(path, state)
            return None
        prompt = (Path(__file__).parent / "prompts" / "expansion.txt").read_text(encoding="utf-8")
        identifier = uuid.uuid4().hex
        task = runtime.register("expansion", {"knowledge_refs": selected, "basis": bases, "expansion_id": identifier},
            "periodic_coverage", scope={"root": str(runtime.store.home), "paths": ["expansions/" + identifier + ".json"]}, prompt=prompt)
        state["pending_task_id"] = task["id"]
        state["last_scheduled_at"] = now
        atomic_json(path, state)
        return task


def register_request(runtime, request):
    REQUEST_ARGS.validate_python(request)
    refs = request["knowledge_refs"]
    if len({ref["id"] for ref in refs}) != len(refs):
        raise ValueError("Explicit exploration requires distinct versioned knowledge references")
    with runtime.store.locked():
        if status(runtime)["unavailable_reason"]:
            raise ValueError("Exploration is unavailable until G3 and model configuration are ready")
        if len(refs) > runtime.config.read()["values"]["expansion"]["batch_size"]:
            raise ValueError("Exploration request exceeds the configured batch size")
        records, versions = _snapshot(runtime.store)
        for ref in refs:
            if ref["id"] not in records["knowledge"] or versions[ref["id"]] != _identifier(ref["version"], 64):
                from .storage import ConflictError
                raise ConflictError("Exploration input changed")
        submission = record_submission(runtime.store, request, request["reason"], identifier=_hash(("expansion/" + request["client_request_id"]).encode("utf-8"))[:32])
        identifier = _hash((submission["id"] + submission["version"]).encode())[:32]
        prompt = (Path(__file__).parent / "prompts" / "expansion.txt").read_text(encoding="utf-8")
        return runtime.register("expansion", {"knowledge_refs": refs, "basis": {}, "expansion_id": identifier,
            "question": request["question"], "user_request_ref": submission}, "user_requested",
            scope={"root": str(runtime.store.home), "paths": ["expansions/" + identifier + ".json"]}, prompt=prompt)


def execution_task(runtime, task):
    with runtime.store.locked():
        saved = runtime._live(task["id"])
        if saved.get("execution_input_version"):
            inputs = json.loads(runtime.store.read_version(saved["execution_input_version"]))
        else:
            records, versions = _snapshot(runtime.store)
            sources = {}
            catalog = []
            for kind, values in records.items():
                for identifier, record in sorted(values.items()):
                    catalog.append({"id": identifier, "version": versions[identifier], "record_kind": "knowledge" if kind == "knowledge" else "relation", "record": record})
                    for ref in _references(record):
                        sources[json.dumps(ref, sort_keys=True)] = read_source(runtime.store.home, ref)
            existing, _ = runtime.store._scan(runtime.store.home, allowed=["expansions"])
            template = {"id": task["inputs"]["expansion_id"], "input_refs": task["inputs"]["knowledge_refs"],
                        "question": task["inputs"].get("question", "本批知识有哪些值得核查的新联系或深化问题？"), "reason": "用户要求" if task["trigger"] == "user_requested" else "本批覆盖",
                        "claims": [], "proposed_connections": [], "open_questions": []}
            inputs = {**task["inputs"], "records": catalog, "sources": list(sources.values()),
                      "source_refs": [item["ref"] for item in sources.values()], "expansion_template": template,
                      "prior_expansions": [json.loads(runtime.store.read_version(item["version"])) for item in existing.values()]}
            if task["inputs"].get("user_request_ref"):
                inputs["sources"].append(read_source(runtime.store.home, task["inputs"]["user_request_ref"]))
                inputs["source_refs"].append(task["inputs"]["user_request_ref"])
            saved["execution_input_version"] = runtime.store.put_version(json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        file = Path(task["workspace"]) / "expansions" / (task["inputs"]["expansion_id"] + ".json")
        file.parent.mkdir(exist_ok=True)
        file.write_text(json.dumps(inputs["expansion_template"], ensure_ascii=False) + "\n", encoding="utf-8")
        saved.pop("expansion_prepared", None)
        runtime._save(saved)
        return {**task, "inputs": inputs}


def validate_task(runtime, task, result):
    if task["kind"] != "expansion":
        raise ValueError("Expected an expansion task")
    if result is None:
        return
    EXPANSION_RESULT.validate_python(result)
    identifier = task["inputs"]["expansion_id"]
    refs = result["expansion_refs"]
    network_errors = [call for call in task.get("web_calls", []) if "error" in json.loads(runtime.store.read_version(call["result_version"]))]
    if network_errors and (not refs or not task.get("external_source_refs")):
        raise ValueError("Unavailable web evidence is not a successful empty exploration")
    if refs not in ([], [{"id": identifier}]) and not task.get("expansion_prepared"):
        raise ValueError("Expansion result must refer only to its allocated result")
    if task.get("expansion_prepared") and result != task["expansion_prepared"]:
        raise ValueError("Prepared expansion result changed")
    root = Path(task["workspace"])
    file = root / "expansions" / (identifier + ".json")
    expected = {file.relative_to(root).as_posix()} if refs or not task.get("expansion_prepared") else set()
    if {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} != expected:
        raise ValueError("Expansion task wrote outside its allocated result")
    if not refs:
        return
    record = json.loads(file.read_text(encoding="utf-8"))
    EXPANSION_RECORD.validate_python(record)
    if record["id"] != identifier or record["input_refs"] != task["inputs"]["knowledge_refs"]:
        raise ValueError("Invalid expansion identity, question or fixed input")
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    known = {(item["id"], item["version"]) for item in inputs["records"]}
    def endpoint(value):
        if "candidate" in value:
            return
        if (value["id"], value["version"]) not in known:
            raise ValueError("Connection endpoint must be an input record or explicit candidate")
    for group in ("claims", "proposed_connections", "open_questions"):
        for item in record[group]:
            if group != "open_questions":
                if item["status"] != "unverified" and not item["source_refs"]:
                    raise ValueError("Verified claims require actual read evidence")
            if group == "proposed_connections":
                endpoint(item.get("source")); endpoint(item.get("target"))
            for ref in item["source_refs"]:
                if ref not in task.get("external_source_refs", []):
                    raise ValueError("Claim source was not actually read by this task")
                read_source(runtime.store.home, ref)
    if task.get("expansion_prepared") and refs[0]["version"] != _hash(file.read_bytes()):
        raise ValueError("Expansion bytes changed after preparation")


def prepare_result(runtime, task, result):
    result = deepcopy(result)
    path = Path(task["workspace"]) / "expansions" / (task["inputs"]["expansion_id"] + ".json")
    if result["expansion_refs"]:
        result["expansion_refs"][0]["version"] = runtime.store.put_version(path.read_bytes())
    else:
        path.unlink(missing_ok=True)
    task = runtime.task(task["id"])
    task["expansion_prepared"] = result
    runtime._save(task)
    return result


def after_commit(runtime, task):
    result = json.loads(runtime.store.read_version(task["result_version"]))
    if result["expansion_refs"]:
        from .knowledge import register_expansion_analysis
        register_expansion_analysis(runtime, result["expansion_refs"], result["reason"], task["commit_id"], dependencies=[task["id"]])
    state = _state(runtime)
    state["completed"].update(task["inputs"]["basis"])
    if task["trigger"] == "periodic_coverage":
        state["cursor"] = task["inputs"]["knowledge_refs"][-1]["id"]
    if state["pending_task_id"] == task["id"]:
        state["pending_task_id"] = None
    atomic_json(runtime.store.home / "events" / "expansion-coverage.json", state)
