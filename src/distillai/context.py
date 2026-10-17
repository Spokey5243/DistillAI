"""Versioned context preparation and read-only queries owned by individual calls."""
from copy import deepcopy
import json
from pathlib import Path
import re
import uuid
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, TypeAdapter, with_config
from .knowledge import KnowledgeIndex
from .sources import DraftRecordRef, Identifier, NonblankText, RecordRef, SessionKey, SourceRef, Version, queue_path, read_source, scan_queue, contains, now
from .storage import atomic_json, ConflictError, _identifier, _hash


KINDS = {"knowledge": "knowledge", "relations": "relation", "hypotheses": "hypothesis",
         "episodes": "episode", "expansions": "expansion"}


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class AllocationArgs(TypedDict):
    record_kind: Literal["candidate"]


ALLOCATION_ARGS = TypeAdapter(AllocationArgs)


class NamedRecord(RecordRef):
    name: NonblankText
    source_knowledge_id: NotRequired[Identifier]
    target_knowledge_id: NotRequired[Identifier]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class Subgraph(TypedDict):
    knowledge_refs: list[NamedRecord]
    relations: list[NamedRecord]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ContextSummary(TypedDict):
    record_refs: list[RecordRef]
    summary: NonblankText
    source_refs: list[SourceRef]
    status: NonblankText
    reason: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class Candidate(TypedDict):
    id: Identifier
    revision: int
    record_refs: list[RecordRef]
    text: NonblankText
    conditions: NonblankText
    rationale: NonblankText
    reanalysis_versions: NotRequired[dict[Identifier, Version]]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ContextRecord(TypedDict):
    id: Identifier
    session_key: SessionKey
    episode_ref: RecordRef
    record_refs: list[RecordRef]
    subgraph: Subgraph
    mcp_context: list[ContextSummary]
    injection_candidates: list[Candidate]
    material_updates: int


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ContextResult(TypedDict):
    context_ref: DraftRecordRef
    reason: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class QueryItem(TypedDict):
    record_kind: Literal["knowledge", "relation", "hypothesis", "episode", "expansion"]
    record_ref: RecordRef


class PreparedQueryItem(QueryItem):
    record: dict[str, Any]
    source_refs: list[SourceRef]
    user_model_fields: list[str]
    reanalysis: list[dict[str, Any]]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class QueryResult(TypedDict):
    status: Literal["ok", "no_match"]
    items: list[QueryItem]
    source_refs: list[SourceRef]
    reason: NonblankText


class PreparedQueryResult(QueryResult):
    items: list[PreparedQueryItem]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class SelectionResult(TypedDict):
    selected_ids: list[str]
    reason: NonblankText
    selected: NotRequired[list[Candidate]]


CONTEXT_RECORD = TypeAdapter(ContextRecord)
CONTEXT_RESULT = TypeAdapter(ContextResult)
QUERY_RESULT = TypeAdapter(QueryResult)
PREPARED_QUERY_RESULT = TypeAdapter(PreparedQueryResult)
SELECTION_RESULT = TypeAdapter(SelectionResult)


def _invocation(runtime, identifier):
    folder = runtime.store.home / "events" / "queries"
    folder.mkdir(exist_ok=True)
    return folder / (_identifier(identifier) + ".json")


def _item(kind, identifier, version, record, reanalysis=()):
    return {"record_kind": kind, "record_ref": {"id": identifier, "version": version},
            "record": record, "source_refs": _sources(record), "reanalysis": list(reanalysis),
            "user_model_fields": [name for name in ("observations", "hypotheses", "cognition", "hypothesis_refs") if name in record]}


def _sources(value):
    refs = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"source_refs", "basis_refs", "external_evidence_refs"} and isinstance(child, list):
                for ref in child:
                    if ref not in refs:
                        refs.append(ref)
            else:
                for ref in _sources(child):
                    if ref not in refs:
                        refs.append(ref)
    elif isinstance(value, list):
        for child in value:
            for ref in _sources(child):
                if ref not in refs:
                    refs.append(ref)
    return refs


def _direct(runtime, query):
    from .cognition import reanalysis
    index = getattr(runtime, "knowledge_index", None)
    if index is None:
        index = runtime.knowledge_index = KnowledgeIndex(runtime.store)
    items = []
    explicit = re.fullmatch(r"(?:(knowledge|relation):)?([0-9a-f]{32})", query.strip())
    if explicit:
        for kind in ([explicit[1]] if explicit[1] else ["knowledge", "relation"]):
            try:
                detail = index.detail(kind, explicit[2])
                items.append(_item(kind, explicit[2], detail["version"], detail["record"], reanalysis(runtime.store, explicit[2])))
            except FileNotFoundError:
                continue
    else:
        matches = index.lookup(query)["matches"]
        if not matches:
            return None
        for ref in matches:
            for kind in ("knowledge", "relation"):
                try:
                    detail = index.detail(kind, ref["id"], version=ref["version"])
                    items.append(_item(kind, ref["id"], ref["version"], detail["record"], reanalysis(runtime.store, ref["id"])))
                    break
                except FileNotFoundError:
                    continue
    return {"status": "ok" if items else "not_found", "items": items,
            "source_refs": _sources([item["record"] for item in items]), "reason": "Exact record lookup"}


def start_query(runtime, session_key, query, invocation_id, knowledge_refs=None, relation_refs=None):
    queue_path(runtime.store.home, session_key)
    if not isinstance(query, str) or not query.strip() or len(query) > 65536:
        raise ValueError("A nonempty query of at most 65536 characters is required")
    known = {"knowledge_refs": knowledge_refs if knowledge_refs is not None else [],
             "relation_refs": relation_refs if relation_refs is not None else []}
    index = getattr(runtime, "knowledge_index", None) or KnowledgeIndex(runtime.store)
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relation")):
        if not isinstance(known[field], list):
            raise ValueError("Known records must be references")
        for ref in known[field]:
            if not isinstance(ref, dict) or set(ref) != {"id", "version"}:
                raise ValueError("Known records need ID and version")
            index.detail(kind, ref["id"], version=ref["version"])
    request = {"session_key": session_key, "query": query, **known}
    with runtime.store.locked():
        path = _invocation(runtime, invocation_id)
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if "request" in saved and saved["request"] != request:
                raise ConflictError("Query invocation already belongs to another request")
            return query_status(runtime, invocation_id)
        result = _direct(runtime, query)
        saved = {"request": request}
        if result is not None:
            saved["result_version"] = runtime.store.put_version(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        else:
            prompt = (Path(__file__).parent / "prompts" / "context.txt").read_text(encoding="utf-8")
            task = runtime.register("query", {**request, "mode": "query", "invocation_id": invocation_id},
                                    "mcp_query", prompt=prompt)
            saved["task_id"] = task["id"]
        atomic_json(path, saved)
        return query_status(runtime, invocation_id)


def query_status(runtime, invocation_id):
    from .cognition import reanalysis
    def annotate(result):
        for item in result.get("items", []):
            item["reanalysis"] = reanalysis(runtime.store, item["record_ref"]["id"])
        return result
    with runtime.store.locked():
        saved = json.loads(_invocation(runtime, invocation_id).read_text(encoding="utf-8"))
        if saved.get("cancel_reason"):
            return {"status": "cancelled", "reason": saved["cancel_reason"]}
        if "result_version" in saved:
            return {"status": "completed", "result": annotate(json.loads(runtime.store.read_version(saved["result_version"])))}
        task = runtime.task(saved["task_id"])
        result = {"task_id": task["id"], "status": "completed" if task["status"] == "succeeded" else task["status"]}
        if task["status"] == "succeeded":
            result["result"] = annotate(json.loads(runtime.store.read_version(task["result_version"])))
        elif task["status"] in {"failed", "cancelled", "recovery_conflict"}:
            result["error"] = task["error"]
            result["reason"] = task["cancel_reason"]
        return result


def cancel_query(runtime, invocation_id, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Query cancellation requires a reason")
    with runtime.store.locked():
        path = _invocation(runtime, invocation_id)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if "result_version" in saved:
            return query_status(runtime, invocation_id)
        saved["cancel_reason"] = reason
        atomic_json(path, saved)
        task_id = saved.get("task_id")
    # Stopping a process tree must not hold the store lock needed by its execution thread.
    if task_id:
        runtime.cancel(task_id, reason)
    return query_status(runtime, invocation_id)


def _snapshot(runtime, session_key):
    from .cognition import reanalysis
    files, _ = runtime.store._scan(runtime.store.home, allowed=[*KINDS, "contexts/" + session_key + ".json"])
    records, current_context = [], None
    for name, info in sorted(files.items()):
        parts = Path(name).parts
        if len(parts) != 2 or Path(name).suffix != ".json":
            raise ValueError("Invalid record in context snapshot")
        record = json.loads(runtime.store.read_version(info["version"]))
        if parts[0] == "contexts":
            current_context = {"context_ref": {"id": record["id"], "version": info["version"]}, "record": record}
            continue
        identifier = _identifier(Path(name).stem)
        if record.get("id") != identifier:
            raise ValueError("Snapshot identity mismatch")
        records.append({"id": identifier, "version": info["version"], "record_kind": KINDS[parts[0]], "record": record,
                        "reanalysis": reanalysis(runtime.store, identifier)})
    return records, current_context


def execution_task(runtime, task):
    if task["kind"] == "screening":
        return task
    if task["kind"] == "context":
        return _prepare_execution(runtime, task)
    if task["kind"] != "query":
        raise ValueError("Unsupported context task mode")
    with runtime.store.locked():
        live = runtime.task(task["id"])
        if live.get("execution_input_version"):
            inputs = json.loads(runtime.store.read_version(live["execution_input_version"]))
        else:
            records, current_context = _snapshot(runtime, task["inputs"]["session_key"])
            for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relation")):
                for ref in task["inputs"].get(field, []):
                    if not any(item["id"] == ref["id"] and item["version"] == ref["version"] and item["record_kind"] == kind for item in records):
                        detail = KnowledgeIndex(runtime.store).detail(kind, ref["id"], version=ref["version"])
                        records.append({**ref, "record_kind": kind, "record": detail["record"]})
            refs = _sources([item["record"] for item in records])
            inputs = {**deepcopy(task["inputs"]), "records": records, "source_refs": refs, "current_context": current_context,
                      "sources": [read_source(runtime.store.home, ref) for ref in refs],
                      "catalog": [{name: item[name] for name in ("id", "version", "record_kind")} | {
                          name: item["record"][name] for name in ("name", "aliases", "source_knowledge_id", "target_knowledge_id") if name in item["record"]}
                          for item in records]}
            live["execution_input_version"] = runtime.store.put_version(json.dumps(inputs, ensure_ascii=False).encode("utf-8"))
            live["read_record_refs"], live["read_source_refs"] = [], []
            runtime._save(live)
        live.pop("query_prepared", None)
        runtime._save(live)
        return {**deepcopy(task), "inputs": inputs}


def audit_reads(runtime, task_id, records=(), sources=()):
    with runtime.store.locked():
        task = runtime.task(task_id)
        if task["kind"] != "query" or task["status"] != "running" or not task.get("execution_input_version"):
            raise ValueError("Read audit requires a running query snapshot")
        inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
        available = [{name: item[name] for name in ("id", "version", "record_kind")} for item in inputs["records"]]
        for values, allowed, field in ((records, available, "read_record_refs"), (sources, inputs["source_refs"], "read_source_refs")):
            if not isinstance(values, (list, tuple)) or any(value not in allowed for value in values):
                raise ValueError("Read is outside the fixed query snapshot")
            for value in values:
                if value not in task[field]:
                    task[field].append(value)
        task["query_read_performed"] = True
        runtime._save(task)
        return {"recorded": True}


def validate_task(runtime, task, result):
    if task["kind"] == "context":
        return _validate_prepare(runtime, task, result)
    if task["kind"] == "screening":
        if task["scope"] is not None:
            raise ValueError("Selection must be read only")
        if result is not None:
            SELECTION_RESULT.validate_python(result)
        if result is not None and "selected" in result and result != task.get("selection_prepared"):
            raise ValueError("Program-prepared selection changed")
        return
    if task["kind"] != "query" or task["scope"] is not None:
        raise ValueError("Query must be read only")
    if result is None:
        queue_path(runtime.store.home, task["inputs"]["session_key"])
        _identifier(task["inputs"]["invocation_id"])
        return
    (PREPARED_QUERY_RESULT if task.get("query_prepared") else QUERY_RESULT).validate_python(result)
    if (result["status"] == "no_match") != (not result["items"]):
        raise ValueError("Invalid query output")
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    seen, permitted_sources = set(), list(task.get("read_source_refs", []))
    for item in result["items"]:
        ref = item["record_ref"]
        read = {**ref, "record_kind": item["record_kind"]}
        key = (item["record_kind"], ref["id"], ref["version"])
        if read not in task.get("read_record_refs", []) or key in seen:
            raise ValueError("Returned records must have been read once from the fixed snapshot")
        seen.add(key)
        frozen = next(value for value in inputs["records"] if all(value[name] == read[name] for name in read))
        record = frozen["record"]
        permitted_sources.extend(_sources(record))
        if task.get("query_prepared") and item != _item(item["record_kind"], ref["id"], ref["version"], record, frozen.get("reanalysis", [])):
            raise ValueError("Query body differs from its actual immutable version")
    if any(ref not in permitted_sources for ref in result["source_refs"]):
        raise ValueError("Query source has not been read")
    if not result["items"] and inputs["records"] and not task.get("query_read_performed"):
        raise ValueError("No match requires an actual query read")


def prepare_result(runtime, task, result):
    if task["kind"] == "context":
        return _prepare_context_result(runtime, task, result)
    if task["kind"] == "screening":
        validate_task(runtime, task, result)
        ids = result["selected_ids"]
        candidates = {item["id"]: item for item in task["inputs"]["candidates"]}
        path = _context_path(runtime, task["inputs"]["session_key"])
        current = {item["id"]: item for item in json.loads(path.read_text(encoding="utf-8")).get("injection_candidates", [])} if path.exists() else {}
        def same_candidate(identifier):
            return identifier in current and all(candidates[identifier].get(field) == current[identifier].get(field)
                for field in ("revision", "text", "conditions", "record_refs", "reanalysis_versions"))
        versions = _record_versions(runtime)
        selected = [deepcopy(candidates[identifier]) for identifier in ids[:3]
                    if ids.count(identifier) == 1 and identifier in candidates and same_candidate(identifier)
                    and _candidate_current(runtime, candidates[identifier], versions)]
        prepared = {"selected_ids": [item["id"] for item in selected], "selected": selected, "reason": result["reason"]}
        live = runtime.task(task["id"])
        live["selection_prepared"] = prepared
        runtime._save(live)
        return prepared
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    prepared = deepcopy(result)
    prepared["items"] = []
    for item in result["items"]:
        frozen = next(value for value in inputs["records"] if value["record_kind"] == item["record_kind"]
            and value["id"] == item["record_ref"]["id"] and value["version"] == item["record_ref"]["version"])
        prepared["items"].append(_item(item["record_kind"], frozen["id"], frozen["version"], frozen["record"], frozen.get("reanalysis", [])))
    live = runtime.task(task["id"])
    live["query_prepared"] = True
    runtime._save(live)
    return prepared


def after_commit(runtime, task):
    if task["kind"] == "screening":
        path = _selection_path(runtime, task["inputs"]["round_key"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        result = json.loads(runtime.store.read_version(task["result_version"]))
        saved.update(status="prepared", selected=result["selected"], reason=result["reason"], prompt_version=task["prompt_version"])
        atomic_json(path, saved)
    return None


def _context_path(runtime, key):
    queue_path(runtime.store.home, key)
    return runtime.store.home / "contexts" / (key + ".json")


def register_prepare(runtime, session_key, episode_ref, material_updates, reason, *, dependencies=(), force=False):
    path = _context_path(runtime, session_key)
    if type(material_updates) is not int or material_updates < 1:
        raise ValueError("Context refresh requires a successful material update count")
    with runtime.store.locked():
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        inputs = {"mode": "prepare", "session_key": session_key, "episode_refs": [episode_ref],
                  "material_updates": material_updates, "reason": reason, "refresh_trigger": list(dependencies)}
        scope = {"root": str(runtime.store.home), "paths": ["contexts/" + session_key + ".json"]}
        dedup = runtime._dedup("context", inputs, "context_refresh", scope)
        all_tasks = [task for task in runtime.tasks() if task["kind"] == "context" and task["inputs"].get("session_key") == session_key]
        for task in all_tasks:
            if task["dedup"] == dedup or dedup in task.get("dedup_aliases", []):
                return task
        tasks = [task for task in all_tasks if task["status"] not in {"succeeded", "failed", "cancelled", "recovery_conflict"}]
        period = runtime.config.read()["values"]["context"]["refresh_update_count"]
        if (not force and not tasks and current and current["episode_ref"]["id"] == episode_ref["id"]
                and material_updates - current["material_updates"] < period):
            return None
        for task in tasks:
            if task["status"] == "queued" and not task["started"]:
                previous = task["input_version"]
                task.update(inputs=deepcopy(inputs), input_version=runtime.store.put_version(json.dumps(inputs, ensure_ascii=False).encode("utf-8")),
                            dependencies=list(dict.fromkeys([*task["dependencies"], *dependencies])))
                task["dedup_aliases"] = list(dict.fromkeys([*task.get("dedup_aliases", []), task["dedup"], dedup]))
                task["dedup"] = runtime._dedup("context", inputs, "context_refresh", task["scope"])
                runtime._save(task)
                runtime.store.event({"event": "context_prepare_merged", "task_id": task["id"], "before": previous, "after": task["input_version"]})
                runtime.wake()
                return task
        prompt = (Path(__file__).parent / "prompts/context.txt").read_text(encoding="utf-8")
        return runtime.register("context", inputs, "context_refresh", scope=scope, dependencies=dependencies, prompt=prompt)


def refresh_dependencies(runtime, task):
    result = json.loads(runtime.store.read_version(task["result_version"]))
    changed = {ref["id"] for field in ("knowledge_refs", "relation_refs", "hypothesis_refs") for ref in result.get(field, [])}
    changed.update(task.get("reanalysis_resolved_ids", []))
    if not changed:
        return
    from .episode import state
    with runtime.store.locked():
        for path in sorted((runtime.store.home / "contexts").glob("*.json")):
            current = json.loads(path.read_text(encoding="utf-8"))
            if not changed.intersection(ref["id"] for ref in current["record_refs"]):
                continue
            status = state(runtime.store.home, path.stem)
            if status["active_episode_id"] != current["episode_ref"]["id"]:
                continue
            episode_path = runtime.store.home / "episodes" / (status["active_episode_id"] + ".json")
            ref = {"id": status["active_episode_id"], "version": runtime.store.put_version(episode_path.read_bytes())}
            register_prepare(runtime, path.stem, ref, status["material_updates"], "Direct context dependency changed",
                             dependencies=[task["id"]], force=True)


def _prepare_execution(runtime, task):
    with runtime.store.locked():
        live = runtime.task(task["id"])
        if live.get("execution_input_version"):
            inputs = json.loads(runtime.store.read_version(live["execution_input_version"]))
        else:
            records, _ = _snapshot(runtime, task["inputs"]["session_key"])
            path = Path(task["workspace"]) / "contexts" / (task["inputs"]["session_key"] + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            template = {"id": previous["id"] if previous else uuid.uuid4().hex, "session_key": task["inputs"]["session_key"],
                "episode_ref": task["inputs"]["episode_refs"][0], "record_refs": [],
                "subgraph": {"knowledge_refs": [], "relations": []}, "mcp_context": [], "injection_candidates": [],
                "material_updates": task["inputs"]["material_updates"]}
            # Private initialization precedes the child; rename makes upstream Windows stat/fstat guards disagree.
            path.write_text(json.dumps(template, ensure_ascii=False) + "\n", encoding="utf-8")
            refs = _sources([item["record"] for item in records])
            inputs = {**task["inputs"], "records": records, "source_refs": refs,
                      "sources": [read_source(runtime.store.home, ref) for ref in refs],
                      "previous_context": previous, "context_template": template,
                      "name_graph": [{"id": item["id"], "version": item["version"], **{
                          name: item["record"][name] for name in ("name", "source_knowledge_id", "target_knowledge_id") if name in item["record"]}}
                          for item in records if item["record_kind"] in {"knowledge", "relation"}]}
            live["execution_input_version"] = runtime.store.put_version(json.dumps(inputs, ensure_ascii=False).encode("utf-8"))
        live.pop("context_prepared", None)
        runtime._save(live)
        return {**task, "inputs": inputs}


def allocate_candidate(runtime, task_id):
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "context" or task["status"] != "running":
            raise ValueError("Candidates are allocated during context preparation")
        identifier = uuid.uuid4().hex
        task.setdefault("allocated_candidate_ids", []).append(identifier)
        runtime._save(task)
        return {"id": identifier, "record_kind": "candidate"}


def _validate_prepare(runtime, task, result):
    if result is None:
        runtime._check_input(task)
        return
    CONTEXT_RESULT.validate_python(result)
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    key = inputs["session_key"]
    expected = "contexts/" + key + ".json"
    files = [path.relative_to(task["workspace"]).as_posix() for path in Path(task["workspace"]).rglob("*") if path.is_file()]
    if files != [expected]:
        raise ValueError("Preparation may only write the session context")
    record = json.loads((Path(task["workspace"]) / expected).read_text(encoding="utf-8"))
    CONTEXT_RECORD.validate_python(record)
    if set(record) != set(inputs["context_template"]) or any(record[name] != inputs["context_template"][name]
            for name in ("id", "session_key", "episode_ref", "material_updates")):
        raise ValueError("Context identity and material count belong to the program")
    available = [{"id": item["id"], "version": item["version"]} for item in inputs["records"]]
    def refs(values):
        if not isinstance(values, list) or any(value not in available for value in values) or len({json.dumps(value, sort_keys=True) for value in values}) != len(values):
            raise ValueError("Context references must belong to its actual input versions")
    refs(record["record_refs"])
    current_versions = _record_versions(runtime)
    if any((ref["id"], ref["version"]) not in current_versions for ref in record["record_refs"]):
        raise ValueError("Context dependency changed before publication")
    graph = record["subgraph"]
    for field, kind in (("knowledge_refs", "knowledge"), ("relations", "relation")):
        for item in graph[field]:
            if item not in inputs["name_graph"] or not any(value["id"] == item["id"] and value["record_kind"] == kind for value in inputs["records"]):
                raise ValueError("Subgraph must preserve actual names and endpoints")
            if {"id": item["id"], "version": item["version"]} not in record["record_refs"]:
                raise ValueError("Subgraph dependencies must remain in prepared record references")
    for item in record["mcp_context"]:
        refs(item["record_refs"])
        if not item["record_refs"] or any(ref not in record["record_refs"] for ref in item["record_refs"]):
            raise ValueError("MCP summaries need actual prepared record references")
        if any(ref not in inputs["source_refs"] for ref in item["source_refs"]):
            raise ValueError("Context source must have been available")
    previous = {item["id"]: item for item in (inputs["previous_context"] or {}).get("injection_candidates", [])}
    seen = set()
    for item in record["injection_candidates"]:
        if item["id"] in seen:
            raise ValueError("Invalid candidate identity, text, conditions or rationale")
        identifier = _identifier(item["id"])
        seen.add(identifier)
        refs(item["record_refs"])
        from .cognition import reanalysis_versions
        if task.get("context_prepared") and item.get("reanalysis_versions") != reanalysis_versions(runtime.store, item["record_refs"]):
            raise ValueError("Candidate reanalysis dependencies changed")
        if not item["record_refs"] or any(ref not in record["record_refs"] for ref in item["record_refs"]):
            raise ValueError("Candidate must cite prepared records")
        old = previous.get(identifier)
        if old is None and identifier not in task.get("allocated_candidate_ids", []):
            raise ValueError("New candidates need a program ID; existing candidates keep theirs")
        if old is None and any(all(item[field] == prior[field] for field in ("text", "conditions", "record_refs")) for prior in previous.values()):
            raise ValueError("An unchanged existing candidate must retain its identity")
        if not task.get("context_prepared") and item["revision"] != (old["revision"] if old else 0):
            raise ValueError("The program maintains candidate revisions")
    ref = result["context_ref"]
    if ref != ({"id": record["id"], "version": _hash((Path(task["workspace"]) / expected).read_bytes())} if task.get("context_prepared") else {"id": record["id"]}):
        raise ValueError("Context reference does not describe the prepared file")


def _prepare_context_result(runtime, task, result):
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    path = Path(task["workspace"]) / "contexts" / (inputs["session_key"] + ".json")
    record = json.loads(path.read_text(encoding="utf-8"))
    previous = {item["id"]: item for item in (inputs["previous_context"] or {}).get("injection_candidates", [])}
    for item in record["injection_candidates"]:
        old = previous.get(item["id"])
        fields = ("text", "conditions", "record_refs")
        from .cognition import reanalysis_versions
        item["reanalysis_versions"] = reanalysis_versions(runtime.store, item["record_refs"])
        item["revision"] = 1 if old is None else old["revision"] + int(any(item[field] != old[field] for field in fields)
            or item["reanalysis_versions"] != old.get("reanalysis_versions", {}))
    atomic_json(path, record)
    prepared = {"context_ref": {"id": record["id"], "version": runtime.store.put_version(path.read_bytes())}, "reason": result["reason"]}
    live = runtime.task(task["id"])
    live["context_prepared"] = prepared
    runtime._save(live)
    return prepared


def _record_versions(runtime):
    files, _ = runtime.store._scan(runtime.store.home, allowed=list(KINDS))
    return {(Path(name).stem, value["version"]) for name, value in files.items()}


def _candidate_current(runtime, candidate, versions=None):
    from .cognition import reanalysis, reanalysis_versions
    versions = _record_versions(runtime) if versions is None else versions
    refs = candidate["record_refs"]
    affected = [item for item in reanalysis(runtime.store) if item["record_ref"]["id"] in {ref["id"] for ref in refs}]
    return (all((ref["id"], ref["version"]) in versions for ref in refs)
        and not any(item["status"] == "waiting" for item in affected)
        and (not affected or candidate.get("reanalysis_versions") == reanalysis_versions(runtime.store, refs)))


def _selection_path(runtime, round_key):
    folder = runtime.store.home / "events" / "selections"
    folder.mkdir(exist_ok=True)
    return folder / (_identifier(round_key) + ".json")


def start_selection(runtime, session_key, prompt):
    path = _context_path(runtime, session_key)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Selection requires the current prompt")
    with runtime.store.locked():
        round_key = uuid.uuid4().hex
        saved = {"round_key": round_key, "session_key": session_key, "status": "prepared", "selected": [],
                 "reason": "No prepared candidates", "restore_attempts": 0,
                 "request_version": runtime.store.put_version(prompt.encode("utf-8"))}
        prepared_context = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if prepared_context.get("episode_ref"):
            saved["episode_ref"] = prepared_context["episode_ref"]
        candidates = prepared_context.get("injection_candidates", [])
        versions = _record_versions(runtime)
        candidates = [item for item in candidates if _candidate_current(runtime, item, versions)]
        if candidates:
            selection_prompt = (Path(__file__).parent / "prompts/selection.txt").read_text(encoding="utf-8")
            history = [json.loads(item.read_text(encoding="utf-8")) for item in sorted(_selection_path(runtime, round_key).parent.glob("*.json"))]
            history = [{"round_key": item["round_key"], "selected": item["selected"]} for item in history if item["session_key"] == session_key and item.get("output_phase")]
            task = runtime.register("screening", {"session_key": session_key, "round_key": round_key, "prompt": prompt,
                "candidates": candidates, "history": history}, "user_prompt_selection", prompt=selection_prompt)
            saved.update(task_id=task["id"], status="queued")
        atomic_json(_selection_path(runtime, round_key), saved)
        pointer = runtime.store.home / "events" / "selections" / (session_key + ".current")
        atomic_json(pointer, {"round_key": round_key})
        return {"round_key": round_key, **({"task_id": saved["task_id"]} if "task_id" in saved else {}), "status": saved["status"]}


def selection_status(runtime, round_key):
    with runtime.store.locked():
        saved = json.loads(_selection_path(runtime, round_key).read_text(encoding="utf-8"))
        if "task_id" in saved:
            task = runtime.task(saved["task_id"])
            if task["status"] != "succeeded":
                return {"round_key": round_key, "status": task["status"], "selected": [], "error": task["error"]}
        return saved


def restore_selection(runtime, session_key):
    _context_path(runtime, session_key)
    with runtime.store.locked():
        pointer = runtime.store.home / "events/selections" / (session_key + ".current")
        if not pointer.exists():
            return {"status": "prepared", "selected": []}
        round_key = json.loads(pointer.read_text(encoding="utf-8"))["round_key"]
        saved = selection_status(runtime, round_key)
        if saved["status"] != "prepared":
            return {"status": saved["status"], "selected": []}
        saved["restore_attempts"] += 1
        atomic_json(_selection_path(runtime, round_key), saved)
        return saved


def write_selection(runtime, round_key, writer, *, compact=False):
    """writer returns only after writing additionalContext; this cannot confirm platform receipt."""
    with runtime.store.locked():
        saved = selection_status(runtime, round_key)
        if saved["status"] != "prepared" or not saved["selected"]:
            return False
        if compact and "emitted_items" not in saved:
            return False
        pointer = runtime.store.home / "events/selections" / (saved["session_key"] + ".current")
        if not pointer.exists() or json.loads(pointer.read_text(encoding="utf-8"))["round_key"] != round_key:
            return False
        selected = saved.get("emitted_items", saved["selected"])
        if not compact:
            path = _context_path(runtime, saved["session_key"])
            current = {item["id"]: item for item in json.loads(path.read_text(encoding="utf-8")).get("injection_candidates", [])} if path.exists() else {}
            versions = _record_versions(runtime)
            selected = [item for item in selected if item["id"] in current and all(
                item.get(field) == current[item["id"]].get(field) for field in ("revision", "text", "conditions", "record_refs", "reanalysis_versions"))
                and _candidate_current(runtime, item, versions)]
        if not selected:
            return False
        prompt = (runtime.store.read_version(saved["injection_prompt_version"]) if compact else
                  (Path(__file__).parent / "prompts/injection.txt").read_bytes())
        payload = {"delivery_type": "compact_restore" if compact else "current_round", "round_key": round_key,
                   "selection_prompt_version": saved["prompt_version"], "request_version": saved["request_version"], "items": selected}
        text = prompt.decode("utf-8").strip() + "\n\n" + json.dumps(payload, ensure_ascii=False)
        attempt = {"delivery_type": payload["delivery_type"], "prompt_version": runtime.store.put_version(prompt),
                   "context_version": runtime.store.put_version(text.encode("utf-8")), "at": now()}
        try:
            writer(text)
        except Exception as error:
            runtime.store.event({"event": "selection_output_failed", "round_key": round_key, "code": type(error).__name__})
            return False
        saved["output_phase"] = "additional_context_written"
        saved.setdefault("emitted_items", deepcopy(selected))
        saved.setdefault("injection_prompt_version", attempt["prompt_version"])
        saved.setdefault("outputs", []).append(attempt)
        atomic_json(_selection_path(runtime, round_key), saved)
        return True


def record_request(runtime, session_key, prompt):
    """Record a trusted UserPromptSubmit boundary; this is not a source identity."""
    queue_path(runtime.store.home, session_key)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Request boundary requires the actual prompt")
    with runtime.store.locked():
        folder = runtime.store.home / "events" / "requests"
        folder.mkdir(exist_ok=True)
        path = folder / (session_key + ".json")
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        rows, invalid = scan_queue(runtime.store.home, session_key)
        if invalid is not None:
            raise ValueError("Cannot anchor a request to an invalid source queue")
        boundary = {"sequence": len(previous) + 1, "floor": len(rows), "prompt": prompt}
        atomic_json(path, [*previous, boundary])
        return boundary


def _feedback_path(runtime, feedback_id):
    folder = runtime.store.home / "events" / "feedback"
    folder.mkdir(exist_ok=True)
    return folder / (_identifier(feedback_id, 64) + ".json")


def feedback_status(runtime, feedback_id):
    with runtime.store.locked():
        saved = json.loads(_feedback_path(runtime, feedback_id).read_text(encoding="utf-8"))
        result = {"feedback_id": feedback_id, "stage": saved["stage"]}
        if "task_id" in saved:
            result["task_id"] = saved["task_id"]
            result["task_status"] = runtime.task(saved["task_id"])["status"]
        return result


def submit_feedback(runtime, request):
    required = {"client_request_id", "session_key", "performance", "task", "help", "knowledge_refs", "relation_refs", "source_refs"}
    if (not isinstance(request, dict) or set(request) != required
            or any(not isinstance(request[name], str) or not request[name].strip() or len(request[name]) > 65536
                   for name in ("client_request_id", "performance", "task", "help"))):
        raise ValueError("Feedback needs a stable request ID and the actual performance, task and help")
    queue_path(runtime.store.home, request["session_key"])
    if not isinstance(request["source_refs"], list):
        raise ValueError("Feedback sources must be a list")
    for ref in request["source_refs"]:
        source = read_source(runtime.store.home, ref)
        if (ref["session_key"] != request["session_key"] or not any(
                row["role"] == "user" and request["performance"] in row["text"] for row in source["rows"])):
            raise ValueError("Feedback requires actual user text in this session")
    index = getattr(runtime, "knowledge_index", None) or KnowledgeIndex(runtime.store)
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relation")):
        if not isinstance(request[field], list):
            raise ValueError("Feedback targets must be record references")
        for ref in request[field]:
            if not isinstance(ref, dict) or set(ref) != {"id", "version"}:
                raise ValueError("Feedback target needs ID and version")
            index.detail(kind, ref["id"], version=ref["version"])
    identifier = _hash(request["client_request_id"].encode("utf-8"))
    with runtime.store.locked():
        path = _feedback_path(runtime, identifier)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8"))["request"] != request:
                raise ValueError("Feedback request ID already belongs to different content")
            return feedback_status(runtime, identifier)
        boundary_path = runtime.store.home / "events" / "requests" / (request["session_key"] + ".json")
        boundaries = json.loads(boundary_path.read_text(encoding="utf-8")) if boundary_path.exists() else []
        saved = {"request": deepcopy(request), "stage": "awaiting_source",
                 "request_boundary": boundaries[-1] if boundaries else None}
        atomic_json(path, saved)
        _associate_feedback(runtime, path, saved)
        runtime.wake()
        return feedback_status(runtime, identifier)


def _associate_feedback(runtime, path, saved):
    request = saved["request"]
    if "task_id" in saved:
        task = runtime.task(saved["task_id"])
        if task["status"] != "cancelled" or task["cancel_reason"] not in {"input_or_permission_changed", "Fixed episode input was superseded"}:
            return
    refs = request["source_refs"]
    if not refs:
        boundary = saved.get("request_boundary")
        if not boundary or request["performance"] not in boundary["prompt"]:
            return
        rows, _ = scan_queue(runtime.store.home, request["session_key"])
        boundaries = json.loads((runtime.store.home / "events/requests" / (request["session_key"] + ".json")).read_text(encoding="utf-8"))
        later = [item["floor"] for item in boundaries if item["sequence"] > boundary["sequence"]]
        ceiling = min(later) if later else len(rows)
        matches = [position for position, row in enumerate(rows, 1) if boundary["floor"] < position <= ceiling
                   and row["role"] == "user" and row["text"].strip() == boundary["prompt"].strip()]
        if len(matches) != 1:
            return
        refs = [{"connector": "codex", "session_key": request["session_key"], "line_start": matches[0], "line_end": matches[0]}]
    files, _ = runtime.store._scan(runtime.store.home, allowed=["episodes"])
    owners = []
    for name, info in files.items():
        record = json.loads(runtime.store.read_version(info["version"]))
        if record.get("session_key") == request["session_key"] and all(contains(ref, record.get("source_refs", [])) for ref in refs):
            owners.append({"id": record["id"], "version": info["version"]})
    if len(owners) != 1:
        return
    feedback = {**request, "source_refs": refs, "feedback_id": path.stem}
    prompt = (Path(__file__).parent / "prompts/cognition.txt").read_text(encoding="utf-8")
    task = runtime.register("cognition", {"episode_refs": owners, "feedback": feedback}, "mcp_feedback",
        scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations", "hypotheses", "cognition/reanalysis.json"]}, prompt=prompt)
    saved.update(stage="registered", task_id=task["id"])
    atomic_json(path, saved)


def reconcile_feedback(runtime):
    with runtime.store.locked():
        for path in sorted((runtime.store.home / "events" / "feedback").glob("*.json")):
            try:
                _associate_feedback(runtime, path, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError) as error:
                runtime.store.event({"event": "feedback_association_pending", "feedback_id": path.stem, "code": type(error).__name__})
