"""User evidence and qualitative judgments; content belongs to knowledge maintenance."""
from copy import deepcopy
import json
from pathlib import Path
import uuid
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config
from .knowledge import MaintenanceResult, RecordKind as ContentKind, validate_collection as validate_knowledge
from .sources import DraftRecordRef, Identifier, NonblankText, RecordRef, SourceRef, Version, VersionedRef, read_source, utc, now, contains, record_submission
from .storage import _identifier, _hash, atomic_json, ConflictError


FIELDS = {"observations", "hypotheses", "hypothesis_refs", "cognition"}
REANALYSIS = "cognition/reanalysis.json"


RecordKind = Literal["observation", "hypothesis"]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class AllocationArgs(TypedDict):
    record_kind: RecordKind
    source_refs: NotRequired[list[SourceRef]]


ALLOCATION_ARGS = TypeAdapter(AllocationArgs)
RECORD_KIND = TypeAdapter(RecordKind)


type Qualitative = str | list[str] | dict[str, Qualitative]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ObservationSource(TypedDict):
    episode_id: NotRequired[Identifier]
    source_refs: Annotated[list[SourceRef], Field(min_length=1)]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class Observation(TypedDict):
    id: Identifier
    observed_at: str | None
    source: ObservationSource
    task: NonblankText
    help: Annotated[str | dict[str, Any], Field(min_length=1)]
    performance: NonblankText
    scope: NotRequired[Any]
    outcome: NotRequired[Any]
    initiation: NotRequired[Any]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class Hypothesis(TypedDict):
    id: Identifier
    claim: NonblankText
    status: NonblankText
    needed_evidence: str
    changes: NotRequired[list[Any]]


class InlineHypothesis(Hypothesis):
    supporting_observation_ids: list[Identifier]
    counter_observation_ids: list[Identifier]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ObservationLocator(TypedDict):
    record_id: Identifier
    observation_id: Identifier


class SharedHypothesis(Hypothesis):
    knowledge_refs: list[RecordRef]
    relation_refs: list[RecordRef]
    supporting_observations: list[ObservationLocator]
    counter_observations: list[ObservationLocator]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class Judgment(TypedDict):
    assessed_at: str
    understanding: NotRequired[dict[str, Qualitative]]
    summary: NotRequired[str]
    observation_ids: NotRequired[list[Identifier]]
    latest_observed_performance_id: NotRequired[Identifier | None]
    hypothesis_ids: NotRequired[list[Identifier]]
    hypothesis_refs: NotRequired[list[Identifier]]
    hypothesis_scope: NotRequired[Any]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class CorrectionArgs(TypedDict):
    record_kind: ContentKind
    record_id: Identifier
    expected_version: Version
    performance: NonblankText
    help: NonblankText
    reason: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ReanalysisArgs(TypedDict):
    client_request_id: Annotated[NonblankText, Field(max_length=200)]
    record_id: Identifier
    reason: NonblankText


class CognitionResult(MaintenanceResult):
    hypothesis_refs: list[DraftRecordRef]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class WaitingReanalysis(TypedDict):
    record_kind: ContentKind | Literal["hypothesis"]
    record_ref: RecordRef
    previous_episode_ref: RecordRef
    episode_ref: RecordRef
    status: Literal["waiting"]
    reason: NonblankText
    revision_source_refs: list[SourceRef]
    submission_ref: NotRequired[VersionedRef]


class ResolvedReanalysis(WaitingReanalysis):
    status: Literal["ready"]
    resolved_by: Identifier


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ReanalysisState(TypedDict):
    entries: list[WaitingReanalysis | ResolvedReanalysis]


REANALYSIS_STATE = TypeAdapter(ReanalysisState)
OBSERVATIONS = TypeAdapter(list[Observation])
INLINE_HYPOTHESIS = TypeAdapter(InlineHypothesis)
SHARED_HYPOTHESIS = TypeAdapter(SharedHypothesis)
JUDGMENT = TypeAdapter(Judgment)
CORRECTION_ARGS = TypeAdapter(CorrectionArgs)
REANALYSIS_ARGS = TypeAdapter(ReanalysisArgs)
COGNITION_RESULT = TypeAdapter(CognitionResult)
IDENTIFIERS = TypeAdapter(list[Identifier])


def reanalysis(store, record_id=None):
    with store.locked():
        path = store.home / REANALYSIS
        entries = REANALYSIS_STATE.validate_json(path.read_bytes())["entries"] if path.exists() else []
        return [item for item in entries if record_id is None or item["record_ref"]["id"] == record_id]


def reanalysis_versions(store, refs):
    entries = reanalysis(store)
    return {ref["id"]: _hash(json.dumps([item for item in entries if item["record_ref"]["id"] == ref["id"]],
        sort_keys=True, ensure_ascii=False).encode("utf-8")) for ref in refs}


def reset_reanalysis_workspace(runtime, task):
    path = Path(task["workspace"]) / REANALYSIS
    previous = task["baseline"].get(REANALYSIS)
    if previous:
        path.write_bytes(runtime.store.read_version(previous["version"]))
    else:
        path.unlink(missing_ok=True)
    task.pop("reanalysis_prepared_version", None)


def validate_reanalysis_workspace(runtime, task):
    path = Path(task["workspace"]) / REANALYSIS
    expected = task.get("reanalysis_prepared_version") or task["baseline"].get(REANALYSIS, {}).get("version")
    if (path.exists() and _hash(path.read_bytes()) != expected) or (not path.exists() and expected is not None):
        raise ValueError("Reanalysis dependencies belong to the program")


def _save_reanalysis(runtime, task, entries):
    REANALYSIS_STATE.validate_python({"entries": entries})
    path = Path(task["workspace"]) / REANALYSIS
    path.parent.mkdir(exist_ok=True)
    atomic_json(path, {"entries": entries})
    saved = runtime.task(task["id"])
    saved["reanalysis_prepared_version"] = runtime.store.put_version(path.read_bytes())
    runtime._save(saved)


def mark_reanalysis(runtime, task, result, *, inputs=None):
    from .episode import _positions
    inputs = inputs or json.loads(runtime.store.read_version(task["execution_input_version"]))
    cause = {"revision_source_refs": inputs.get("revision_source_refs", [inputs["submission_ref"]] if "submission_ref" in inputs else [])}
    if "submission_ref" in inputs:
        cause["submission_ref"] = inputs["submission_ref"]
    before = {ref["id"]: ref for ref in inputs["episode_refs"]}
    after = {ref["id"]: ref for ref in result["episode_refs"]}
    changed_sources = {}
    for assignment in inputs["assignments"]:
        identifier = assignment["episode_id"]
        changed_sources[identifier] = set(_positions(inputs["episode_records"][identifier]["source_refs"], inputs["session_key"])) ^ set(
            _positions(assignment["source_refs"], inputs["session_key"]))
    entries = [item for item in reanalysis(runtime.store) if item["episode_ref"]["id"] not in after or item["status"] == "waiting"]
    # A second revision supersedes the required analysis version without losing unresolved dependencies.
    for item in entries:
        if item["episode_ref"]["id"] in after:
            item.update(episode_ref=after[item["episode_ref"]["id"]], status="waiting", reason=inputs["reason"], **cause)
            if "submission_ref" not in cause:
                item.pop("submission_ref", None)
            item.pop("resolved_by", None)
    records, dependent_observations = {}, {}
    for directory, kind in (("knowledge", "knowledge"), ("relations", "relation")):
        files, _ = runtime.store._scan(runtime.store.home, allowed=[directory])
        for name, info in sorted(files.items()):
            record = json.loads(runtime.store.read_version(info["version"]))
            records[record["id"]] = (kind, info["version"], record)
            for observation in record.get("observations", []):
                source = observation["source"]
                affected = source.get("episode_id")
                if affected in changed_sources and any(ref.get("connector") == "codex" and ref.get("session_key") == inputs["session_key"]
                        and changed_sources[affected].intersection(range(ref["line_start"], ref["line_end"] + 1)) for ref in source["source_refs"]):
                    dependent_observations[(record["id"], observation["id"])] = affected
    def mark(kind, identifier, version, episode_id):
        entries[:] = [item for item in entries if (item["record_ref"]["id"], item["episode_ref"]["id"]) != (identifier, episode_id)]
        entries.append({"record_kind": kind, "record_ref": {"id": identifier, "version": version},
            "previous_episode_ref": before[episode_id], "episode_ref": after[episode_id], "status": "waiting",
            "reason": inputs["reason"], **cause})
    for identifier, (kind, version, record) in records.items():
        evidence = set(_named_references(record.get("cognition", {}), {"observation_ids"}))
        latest = record.get("cognition", {}).get("latest_observed_performance_id")
        if latest:
            evidence.add(latest)
        for claim in record.get("hypotheses", []):
            evidence.update(claim["supporting_observation_ids"] + claim["counter_observation_ids"])
        for observation_id in evidence:
            affected = dependent_observations.get((identifier, observation_id))
            if affected:
                mark(kind, identifier, version, affected)
    files, _ = runtime.store._scan(runtime.store.home, allowed=["hypotheses"])
    for name, info in sorted(files.items()):
        claim = json.loads(runtime.store.read_version(info["version"]))
        for locator in claim.get("supporting_observations", []) + claim.get("counter_observations", []):
            affected = dependent_observations.get((locator["record_id"], locator["observation_id"]))
            if affected:
                mark("hypothesis", claim["id"], info["version"], affected)
                # This judgment explicitly cites the shared hypothesis; graph neighbors alone do not depend on it.
                for identifier, (kind, version, record) in records.items():
                    if claim["id"] in set(_named_references({"cognition": record.get("cognition", {}),
                            "hypothesis_refs": record.get("hypothesis_refs", [])}, {"hypothesis_ids", "hypothesis_refs"})):
                        mark(kind, identifier, version, affected)
    _save_reanalysis(runtime, task, sorted(entries, key=lambda item: (item["record_ref"]["id"], item["episode_ref"]["id"])))


def source_identity(store, refs):
    if not isinstance(refs, list) or not refs:
        raise ValueError("Observation requires actual user sources")
    users = set()
    for ref in refs:
        source = read_source(store.home, ref)
        for offset, row in enumerate(source["rows"]):
            if row["role"] == "user":
                users.add((ref["session_key"], ref["line_start"] + offset) if ref.get("connector") == "codex" else
                          ("user_submission/" + ref["id"] + "/" + ref["version"], 1))
    if not users:
        raise ValueError("Assistant-only material cannot establish a user performance")
    return tuple(sorted(users))


def _content(record):
    projection = {name: deepcopy(value) for name, value in record.items() if name not in FIELDS | {"changes", "provenance"}}
    provenance = record.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("Provenance must be an object")
    projection["provenance"] = {name: value for name, value in provenance.items()
                                if not name.startswith(("cognition_", "observation_", "hypothesis_"))}
    return projection


def _ids(value):
    ids = IDENTIFIERS.validate_python(value, strict=True)
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated evidence identity")
    return set(ids)


def _claim(hypothesis, *, external=False):
    (SHARED_HYPOTHESIS if external else INLINE_HYPOTHESIS).validate_python(hypothesis)


def _named_references(value, names):
    if isinstance(value, dict):
        for name, child in value.items():
            if name in names:
                yield from _ids(child)
            else:
                yield from _named_references(child, names)


def validate_collection(store, knowledge, relations, hypotheses, *, baseline):
    validate_knowledge(store, knowledge, relations)
    records = {**knowledge, **relations}
    previous = {**baseline["knowledge"], **baseline["relations"]}
    if set(knowledge) != set(baseline["knowledge"]) or set(relations) != set(baseline["relations"]):
        raise ValueError("Cognition maintenance cannot create or delete knowledge content")
    observations, global_ids, local_hypotheses, inline_ids = {}, {}, {}, set()
    for identifier, record in records.items():
        old = previous[identifier]
        if _content(record) != _content(old):
            raise ValueError("Cognition maintenance cannot change content, endpoints, assessment or content provenance")
        changes, old_changes = record.get("changes", []), old.get("changes", [])
        if not isinstance(changes, list) or changes[:len(old_changes)] != old_changes:
            raise ValueError("Prior change history must remain intact")
        items = record.get("observations", [])
        OBSERVATIONS.validate_python(items)
        seen = set()
        observations[identifier] = {}
        for item in items:
            observation_id = item["id"]
            if observation_id in observations[identifier]:
                raise ValueError("Repeated observation ID in one record")
            if item["observed_at"] is not None and utc(item["observed_at"]) is None:
                raise ValueError("Observation time must be UTC-parsable or unknown")
            source = item["source"]
            if "episode_id" in source:
                episode_id = _identifier(source["episode_id"])
                path = store.home / "episodes" / (episode_id + ".json")
                if not path.is_file() or json.loads(path.read_text(encoding="utf-8")).get("id") != episode_id:
                    raise ValueError("Observation episode does not exist")
            elif not isinstance(source["source_refs"], list) or not source["source_refs"] or any(
                    not isinstance(ref, dict) or ref.get("source_kind") != "user_submission" for ref in source["source_refs"]):
                raise ValueError("Independent observations require actual user submissions")
            identity = source_identity(store, source["source_refs"])
            if identity in seen:
                raise ValueError("The same source performance must reuse one observation")
            seen.add(identity)
            if observation_id in global_ids and global_ids[observation_id] != identity:
                raise ValueError("Observation ID was reused for a different source performance")
            global_ids[observation_id] = identity
            observations[identifier][observation_id] = item
        claims = record.get("hypotheses", [])
        if not isinstance(claims, list) or identifier in relations and claims:
            raise ValueError("Relations reference external hypotheses instead of storing inline claims")
        local_hypotheses[identifier] = set()
        for claim in claims:
            _claim(claim)
            if claim["id"] in inline_ids or claim["id"] in hypotheses:
                raise ValueError("A shared hypothesis has one external identity, not duplicate inline records")
            inline_ids.add(claim["id"])
            local_hypotheses[identifier].add(claim["id"])
            for field in ("supporting_observation_ids", "counter_observation_ids"):
                if not _ids(claim[field]).issubset(observations[identifier]):
                    raise ValueError("Hypothesis references an unknown local observation")
        judgment = record.get("cognition")
        if judgment:
            JUDGMENT.validate_python(judgment)
            if utc(judgment["assessed_at"]) is None:
                raise ValueError("Judgment must retain its assessment time")
            if "observation_ids" not in judgment and "observation_ids" not in judgment.get("understanding", {}):
                raise ValueError("Judgment must declare the observations it uses, including an empty list for unknown")
            if any(reference not in observations[identifier] for reference in _named_references(judgment, {"observation_ids"})):
                raise ValueError("Judgment references an unknown observation")
            latest = judgment.get("latest_observed_performance_id")
            if latest is not None and latest not in observations[identifier]:
                raise ValueError("Latest performance must name an actual observation")
    for identifier, claim in hypotheses.items():
        _identifier(identifier)
        _claim(claim, external=True)
        if claim["id"] != identifier:
            raise ValueError("External hypothesis ID and filename disagree")
        affected = set()
        for field, collection, content_field in (("knowledge_refs", knowledge, "summary"), ("relation_refs", relations, "statement")):
            for ref in claim[field]:
                if ref["id"] not in collection:
                    raise ValueError("Unknown affected record")
                saved = json.loads(store.read_version(_identifier(ref["version"], 64)))
                if saved.get("id") != ref["id"] or content_field not in saved.get("content", {}):
                    raise ValueError("Affected record version has the wrong identity or kind")
                affected.add(ref["id"])
        if not affected:
            raise ValueError("External hypothesis must identify its affected records")
        for field in ("supporting_observations", "counter_observations"):
            for locator in claim[field]:
                if locator["record_id"] not in affected or locator["observation_id"] not in observations[locator["record_id"]]:
                    raise ValueError("Unknown cross-object observation locator")
    for identifier, record in records.items():
        for reference in _named_references({"hypothesis_refs": record.get("hypothesis_refs", []), "cognition": record.get("cognition", {})}, {"hypothesis_ids", "hypothesis_refs"}):
            if reference not in local_hypotheses[identifier] and reference not in hypotheses:
                raise ValueError("Judgment references an unknown hypothesis")
            if reference in hypotheses and identifier not in {ref["id"] for ref in hypotheses[reference]["knowledge_refs"] + hypotheses[reference]["relation_refs"]}:
                raise ValueError("Hypothesis does not apply to this record")


def register_analysis(runtime, refs, knowledge_result, reason, source_commit, *, dependencies=(), revision=False):
    prompt = (Path(__file__).parent / "prompts/cognition.txt").read_text(encoding="utf-8")
    return runtime.register("cognition", {"episode_refs": refs, "knowledge_result": knowledge_result,
        "reason": reason, "source_commit": source_commit, **({"episode_revision": True} if revision else {})}, "knowledge_analysis_complete",
        scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations", "hypotheses", REANALYSIS]},
        dependencies=dependencies, prompt=prompt)


def register_correction(runtime, request):
    CORRECTION_ARGS.validate_python(request)
    identifier = _identifier(request["record_id"])
    directory = "knowledge" if request["record_kind"] == "knowledge" else "relations"
    with runtime.store.locked():
        path = runtime.store.home / directory / (identifier + ".json")
        if not path.exists() or _hash(path.read_bytes()) != _identifier(request["expected_version"], 64):
            raise ConflictError("Judgment record version changed; reload before correcting")
        submission = record_submission(runtime.store, request, request["reason"],
            identifier=_hash(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8"))[:32])
        prompt = (Path(__file__).parent / "prompts/cognition.txt").read_text(encoding="utf-8")
        return runtime.register("cognition", {"user_correction": deepcopy(request), "submission_ref": submission,
            "reason": request["reason"]}, "user_correction",
            scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations", "hypotheses", REANALYSIS]}, prompt=prompt)


def request_reanalysis(runtime, request):
    REANALYSIS_ARGS.validate_python(request)
    identifier = _identifier(request["record_id"])
    with runtime.store.locked():
        submission = record_submission(runtime.store, request, request["reason"],
            identifier=_hash(("reanalysis/" + request["client_request_id"]).encode("utf-8"))[:32])
        for task in runtime.tasks():
            source = task["inputs"].get("source_commit")
            if task["kind"] == "knowledge" and isinstance(source, dict) and source.get("request_ref") == submission:
                return task
        required = {item["episode_ref"]["id"] for item in reanalysis(runtime.store, identifier) if item["status"] == "waiting"}
        if not required:
            raise ConflictError("This record has no waiting episode analysis")
        refs = []
        for episode_id in sorted(required):
            path = runtime.store.home / "episodes" / (_identifier(episode_id) + ".json")
            refs.append({"id": episode_id, "version": runtime.store.put_version(path.read_bytes())})
        from .knowledge import register_episode_analysis
        return register_episode_analysis(runtime, refs, request["reason"], {"request_ref": submission, "record_id": identifier}, revision=True)


def execution_task(runtime, task):
    from .knowledge import execution_task as prepare_snapshot
    prepared = prepare_snapshot(runtime, task)
    with runtime.store.locked():
        saved = runtime.task(task["id"])
        if "assessment_at" not in prepared["inputs"]:
            prepared["inputs"]["assessment_at"] = now()
            saved["execution_input_version"] = runtime.store.put_version(json.dumps(prepared["inputs"], ensure_ascii=False, allow_nan=False).encode("utf-8"))
        saved.pop("cognition_prepared", None)
        reset_reanalysis_workspace(runtime, saved)
        runtime._save(saved)
    return prepared


def allocate_id(runtime, task_id, kind, refs=None):
    RECORD_KIND.validate_python(kind, strict=True)
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "cognition" or task["status"] != "running" or not task.get("execution_input_version"):
            raise ValueError("Cognition IDs require a running prepared cognition task")
        inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
        identifier = None
        if kind == "observation":
            if not isinstance(refs, list) or not refs or any(not contains(ref, inputs["source_refs"]) for ref in refs):
                raise ValueError("Observation requires user source_refs inside this task")
            identity = source_identity(runtime.store, refs)
            key = _hash(json.dumps(identity, ensure_ascii=False).encode("utf-8"))
            for record in inputs["records"]:
                for observation in record["record"].get("observations", []):
                    if source_identity(runtime.store, observation["source"]["source_refs"]) == identity:
                        identifier = observation["id"]
                        break
            allocated = task.setdefault("allocated_observation_sources", {})
            identifier = identifier or allocated.get(key) or uuid.uuid4().hex
            allocated[key] = identifier
        else:
            identifier = uuid.uuid4().hex
        task.setdefault("allocated_record_ids", {})[identifier] = kind
        runtime._save(task)
        return {"id": identifier, "record_kind": kind}


def _records(runtime, task):
    root = Path(task["workspace"])
    current = {"knowledge": {}, "relations": {}, "hypotheses": {}}
    baseline = {kind: {} for kind in current}
    versions = {}
    files = {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}
    if not set(task["baseline"]).issubset(files):
        raise ValueError("Keep record and hypothesis history; withdraw hypotheses with their treatment and reason")
    for name, path in files.items():
        if name == REANALYSIS:
            continue
        parts = Path(name).parts
        if len(parts) != 2 or parts[0] not in current or path.suffix != ".json":
            raise ValueError("Cognition task wrote outside its field scope")
        identifier = _identifier(path.stem)
        data = path.read_bytes()
        record = json.loads(data)
        if record.get("id") != identifier:
            raise ValueError("Record ID and file disagree")
        current[parts[0]][identifier] = record
        versions[(parts[0], identifier)] = _hash(data)
    for name, info in task["baseline"].items():
        if name == REANALYSIS:
            continue
        parts = Path(name).parts
        baseline[parts[0]][Path(name).stem] = json.loads(runtime.store.read_version(info["version"]))
    return current, baseline, versions


def validate_task(runtime, task, result):
    if task["kind"] != "cognition" or not (task["inputs"].get("episode_refs") or task["inputs"].get("user_correction")):
        raise ValueError("Unsupported cognition input mode")
    if result is None:
        runtime._check_input(task)
        return
    COGNITION_RESULT.validate_python(result)
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    validate_reanalysis_workspace(runtime, task)
    current, baseline, versions = _records(runtime, task)
    validate_collection(runtime.store, **current, baseline=baseline)
    correction = task["inputs"].get("user_correction")
    allocated = task.get("allocated_record_ids", {})
    changed = {kind: set() for kind in current}
    for kind, records in current.items():
        for identifier, record in records.items():
            old = baseline[kind].get(identifier)
            if versions[(kind, identifier)] == task["baseline"].get(kind + "/" + identifier + ".json", {}).get("version"):
                continue
            changed[kind].add(identifier)
            if correction and kind != "hypotheses" and identifier != correction["record_id"]:
                raise ValueError("A user correction may change only its selected judgment")
            if kind == "hypotheses":
                if correction and any(ref["id"] != correction["record_id"] for field in ("knowledge_refs", "relation_refs") for ref in record[field]):
                    raise ValueError("Cross-object corrections need their own explicit affected targets")
                if old is None and allocated.get(identifier) != "hypothesis":
                    raise ValueError("New hypothesis ID must be allocated by the program")
                continue
            old_observations = {observation["id"]: observation for observation in old.get("observations", [])}
            old_claims = {claim["id"] for claim in old.get("hypotheses", [])}
            for claim in record.get("hypotheses", []):
                if claim["id"] not in old_claims and allocated.get(claim["id"]) != "hypothesis":
                    raise ValueError("New inline hypothesis needs a program ID")
            for observation in record.get("observations", []):
                identity = source_identity(runtime.store, observation["source"]["source_refs"])
                if any(not contains(ref, inputs["source_refs"]) for ref in observation["source"]["source_refs"]):
                    raise ValueError("Observation is outside the fixed task sources")
                previous = old_observations.get(observation["id"])
                if previous:
                    if identity != source_identity(runtime.store, previous["source"]["source_refs"]):
                        raise ValueError("A performance ID cannot be moved to a different raw source")
                else:
                    if correction and observation["source"] != {"source_refs": [inputs["submission_ref"]]}:
                        raise ValueError("New Web correction evidence must cite its independent submission")
                    key = _hash(json.dumps(identity, ensure_ascii=False).encode("utf-8"))
                    if allocated.get(observation["id"]) != "observation" or task.get("allocated_observation_sources", {}).get(key) != observation["id"]:
                        raise ValueError("New observation must use its source-bound program ID")
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relations"), ("hypothesis_refs", "hypotheses")):
        refs = result[field]
        identifiers = [ref["id"] for ref in refs]
        if len(identifiers) != len(set(identifiers)) or set(identifiers) != changed[kind]:
            raise ValueError("Cognition result must describe the actual changed records")
        for ref in refs:
            if task.get("cognition_prepared"):
                if ref.get("version") != versions[(kind, ref["id"])]:
                    raise ValueError("Cognition record changed after version preparation")
            elif "version" in ref:
                raise ValueError("The program fills cognition versions")
    if task.get("cognition_prepared") and task["cognition_prepared"] != result:
        raise ValueError("Program-prepared cognition result changed")


def prepare_result(runtime, task, result):
    result = deepcopy(result)
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relations"), ("hypothesis_refs", "hypotheses")):
        result[field] = [{"id": ref["id"], "version": runtime.store.put_version(
            (Path(task["workspace"]) / kind / (ref["id"] + ".json")).read_bytes())} for ref in result[field]]
    entries = reanalysis(runtime.store)
    refs = task["inputs"].get("episode_refs", [])
    resolved = []
    for item in entries:
        if item["status"] == "waiting" and item["episode_ref"] in refs:
            item.update(status="ready", resolved_by=task["id"])
            resolved.append(item["record_ref"]["id"])
    if resolved:
        _save_reanalysis(runtime, task, entries)
    saved = runtime.task(task["id"])
    saved["reanalysis_resolved_ids"] = sorted(set(resolved))
    saved["cognition_prepared"] = result
    runtime._save(saved)
    return result


def after_commit(runtime, task):
    from .knowledge import KnowledgeIndex
    if not hasattr(runtime, "knowledge_index"):
        runtime.knowledge_index = KnowledgeIndex(runtime.store)
    runtime.knowledge_index.rebuild()
    from .context import refresh_dependencies
    refresh_dependencies(runtime, task)
