"""Knowledge details remain authoritative; the name multigraph is rebuilt from them."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from .sources import read_source, contains, record_submission
from .storage import _hash, _identifier, ConflictError, atomic_json
from .windows import FileHandle, pinned_path


class IndexNotReady(RuntimeError):
    pass


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _source_refs(store, value):
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"source_refs", "basis_refs", "external_evidence_refs"}:
                if not isinstance(child, list):
                    raise ValueError("Source references must be lists")
                for ref in child:
                    read_source(store.home, ref)
            else:
                _source_refs(store, child)
    elif isinstance(value, list):
        for child in value:
            _source_refs(store, child)


def validate_collection(store, knowledge, relations, *, baseline=None):
    names = {}
    for kind, records in (("knowledge", knowledge), ("relations", relations)):
        for identifier, record in records.items():
            _identifier(identifier)
            if not isinstance(record, dict) or record.get("id") != identifier or not _text(record.get("name")):
                raise ValueError("Record ID, filename and name must agree")
            common = {"id", "name", "aliases", "content", "provenance", "observations", "hypotheses", "cognition", "hypothesis_refs", "changes"}
            allowed = common | ({"relations"} if kind == "knowledge" else {
                "source_knowledge_id", "target_knowledge_id", "kind", "relation_type", "direction_semantics", "record_status", "analogy", "assessment", "symmetric"})
            if set(record) - allowed:
                raise ValueError("Unknown record fields")
            content = record.get("content")
            field = "summary" if kind == "knowledge" else "statement"
            if not isinstance(content, dict) or not _text(content.get(field)) or not content.get("source_refs"):
                raise ValueError("Content and actual source references are required")
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list) or any(not _text(alias) for alias in aliases):
                raise ValueError("Aliases must be nonempty strings")
            status = record.get("record_status", "active")
            if status not in ("active", "inactive"):
                raise ValueError("Invalid record status")
            if status == "active":
                name = record["name"].strip().casefold()
                if name in names:
                    raise ValueError("Active primary names must be unique; distinguish meanings in the name")
                names[name] = identifier
            _source_refs(store, record)
            if kind == "relations":
                if record.get("kind") not in ("knowledge_relation", "user_association"):
                    raise ValueError("Invalid relation kind")
                if not _text(record.get("relation_type")) or not _text(record.get("direction_semantics")):
                    raise ValueError("Relation type and direction semantics are required")
                for endpoint in ("source_knowledge_id", "target_knowledge_id"):
                    _identifier(record.get(endpoint))
                    if record[endpoint] not in knowledge:
                        raise ValueError("Relation endpoint is missing from the resulting collection")
                if "symmetric" in record and type(record["symmetric"]) is not bool:
                    raise ValueError("Symmetric must be a boolean")
            if baseline is not None:
                previous = baseline.get(kind, {}).get(identifier, {})
                for field in ("observations", "hypotheses", "cognition", "hypothesis_refs"):
                    if field in previous:
                        if record.get(field) != previous[field]:
                            raise ValueError("Knowledge maintenance cannot change user-model fields")
                    elif record.get(field) not in (None, [], {}):
                        raise ValueError("Knowledge maintenance cannot create user-model evidence or judgments")
                old_provenance, new_provenance = previous.get("provenance", {}), record.get("provenance", {})
                if not isinstance(new_provenance, dict):
                    raise ValueError("Provenance must be an object")
                owned = lambda key: key.startswith(("cognition_", "observation_", "hypothesis_"))
                if ({name: value for name, value in old_provenance.items() if owned(name)}
                        != {name: value for name, value in new_provenance.items() if owned(name)}):
                    raise ValueError("User-model provenance belongs to cognition maintenance")
                changes = record.get("changes", [])
                old_changes = previous.get("changes", [])
                if not isinstance(changes, list) or changes[:len(old_changes)] != old_changes:
                    raise ValueError("Existing change history must remain intact")
    for identifier, record in knowledge.items():
        refs = record.get("relations", [])
        if not isinstance(refs, list) or len(refs) != len(set(refs)):
            raise ValueError("Explicit relation references must be distinct IDs")
        for relation_id in refs:
            relation = relations.get(relation_id)
            if relation is None or identifier not in (relation["source_knowledge_id"], relation["target_knowledge_id"]):
                raise ValueError("Explicit relation must belong to this knowledge point")


def _snapshot(store):
    files, _ = store._scan(store.home, allowed=["knowledge", "relations"])
    records = {"knowledge": {}, "relations": {}}
    versions = {}
    for name, info in files.items():
        parts = Path(name).parts
        if len(parts) != 2 or Path(name).suffix != ".json":
            raise ValueError("Record directories contain only ID-named JSON details")
        identifier = _identifier(Path(name).stem)
        records[parts[0]][identifier] = json.loads(store.read_version(info["version"]))
        versions[identifier] = info["version"]
    if set(records["knowledge"]) & set(records["relations"]):
        raise ValueError("Knowledge and relations cannot share a stable ID")
    return records, versions


class KnowledgeIndex:
    def __init__(self, store):
        self.store = store
        self._index = None

    def rebuild(self):
        import networkx as nx
        with self.store.locked():
            self._index = None
            records, versions = _snapshot(self.store)
            validate_collection(self.store, **records)
            names, nodes, edges = {}, {}, {}
            for kind, items in records.items():
                for identifier, record in sorted(items.items()):
                    if record.get("record_status", "active") != "active":
                        continue
                    ref = {"id": identifier, "name": record["name"], "version": versions[identifier]}
                    for name in [record["name"], *record.get("aliases", [])]:
                        names.setdefault(name.strip().casefold(), {})[identifier] = ref
                    if kind == "knowledge":
                        nodes[identifier] = ref
                    else:
                        edges[identifier] = {**ref, "source_knowledge_id": record["source_knowledge_id"],
                                             "target_knowledge_id": record["target_knowledge_id"],
                                             "symmetric": record.get("symmetric", False)}
            graph = nx.MultiDiGraph()
            graph.add_nodes_from(nodes.items())
            for identifier, edge in edges.items():
                source, target = edge["source_knowledge_id"], edge["target_knowledge_id"]
                graph.add_edge(source, target, key=identifier, **edge)
                if edge["symmetric"]:
                    graph.add_edge(target, source, key=identifier, **edge)
            self._index = {"names": names, "graph": graph}

    def lookup(self, name):
        if not _text(name):
            raise ValueError("A nonempty exact name or alias is required")
        with self.store.locked():
            if self._index is None:
                raise IndexNotReady("Knowledge index has not been rebuilt successfully")
            matches = self._index["names"].get(name.strip().casefold(), {})
            return {"matches": [deepcopy(matches[identifier]) for identifier in sorted(matches)]}

    def detail(self, kind, identifier, *, version=None):
        directory = {"knowledge": "knowledge", "relation": "relations"}.get(kind)
        if directory is None:
            raise ValueError("Invalid record kind")
        identifier = _identifier(identifier)
        with self.store.locked():
            if version is None:
                path = self.store.home / directory / (identifier + ".json")
                if not path.is_file():
                    raise FileNotFoundError("Record not found")
                with pinned_path(path) as parent, FileHandle(path, parent=parent) as handle:
                    data = handle.read()
                version = self.store.put_version(data)
            else:
                data = self.store.read_version(_identifier(version, 64))
            record = json.loads(data)
            if record.get("id") != identifier or not _text(record.get("name")) or not isinstance(record.get("content"), dict):
                raise FileNotFoundError("Record version does not belong to the requested identity")
            if ("summary" if kind == "knowledge" else "statement") not in record["content"]:
                raise FileNotFoundError("Record version does not belong to the requested kind")
            return {"record": record, "version": version}

    def neighbors(self, identifier, *, direction="both"):
        identifier = _identifier(identifier)
        if direction not in ("in", "out", "both"):
            raise ValueError("Invalid graph direction")
        with self.store.locked():
            if self._index is None:
                raise IndexNotReady("Knowledge index is not ready; details remain readable")
            graph = self._index["graph"]
            if identifier not in graph:
                raise FileNotFoundError("Knowledge point not found")
            neighbors, relations = {}, []
            directions = ("in", "out") if direction == "both" else (direction,)
            selected = {}
            for part in directions:
                edges = graph.in_edges(identifier, keys=True, data=True) if part == "in" else graph.out_edges(identifier, keys=True, data=True)
                selected.update((key, edge) for _, _, key, edge in edges)
            for edge_id in sorted(selected):
                edge = selected[edge_id]
                source, target = edge["source_knowledge_id"], edge["target_knowledge_id"]
                other = source if target == identifier else target
                neighbors[other] = graph.nodes[other]
                relations.append({name: value for name, value in edge.items() if name != "symmetric"})
            return {"knowledge_refs": [deepcopy(neighbors[key]) for key in sorted(neighbors)], "relations": relations}


def register_episode_analysis(runtime, refs, reason, source_commit, *, dependencies=(), revision=False):
    prompt = (Path(__file__).parent / "prompts" / "knowledge.txt").read_text(encoding="utf-8")
    return runtime.register("knowledge", {"episode_refs": refs, "reason": reason, "source_commit": source_commit,
        **({"episode_revision": True} if revision else {})},
        "episode_closed_or_revised", scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations"]},
        dependencies=dependencies, prompt=prompt)


def _merge_edit(record, changes):
    result = deepcopy(record)
    for field, value in changes.items():
        result[field] = _merge_edit(result[field], value) if isinstance(value, dict) and isinstance(result.get(field), dict) else deepcopy(value)
    return result


def register_expansion_analysis(runtime, refs, reason, source_commit, *, dependencies=()):
    prompt = (Path(__file__).parent / "prompts" / "knowledge.txt").read_text(encoding="utf-8")
    return runtime.register("knowledge", {"expansion_refs": refs, "reason": reason, "source_commit": source_commit},
        "expansion_committed", scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations"]},
        dependencies=dependencies, prompt=prompt)


def register_user_edit(runtime, request):
    if (not isinstance(request, dict) or set(request) != {"record_kind", "record_id", "expected_version", "changes", "reason"}
            or request["record_kind"] not in {"knowledge", "relation"} or not _text(request["reason"])):
        raise ValueError("Knowledge edits require kind, ID, expected version, changes and reason")
    _identifier(request["record_id"])
    _identifier(request["expected_version"], 64)
    changes = request["changes"]
    allowed = {"name", "aliases", "content", "relations"} if request["record_kind"] == "knowledge" else {
        "name", "aliases", "content", "source_knowledge_id", "target_knowledge_id", "kind", "relation_type", "direction_semantics", "record_status", "analogy", "assessment", "symmetric"}
    def source_edit(value):
        if isinstance(value, dict):
            return any(name in {"source_refs", "basis_refs", "external_evidence_refs"} or source_edit(child) for name, child in value.items())
        return isinstance(value, list) and any(source_edit(child) for child in value)
    if not isinstance(changes, dict) or not changes or set(changes) - allowed or source_edit(changes):
        raise ValueError("IDs, sources, history and user-model fields are read only in a content edit")
    directory = "knowledge" if request["record_kind"] == "knowledge" else "relations"
    with runtime.store.locked():
        records, versions = _snapshot(runtime.store)
        old = records[directory].get(request["record_id"])
        if old is None:
            raise FileNotFoundError("Record not found")
        if versions[request["record_id"]] != request["expected_version"]:
            raise ConflictError("Record changed since the editor loaded it")
        proposed = deepcopy(records)
        proposed[directory][request["record_id"]] = _merge_edit(old, changes)
        validate_collection(runtime.store, **proposed, baseline=records)
        identifier = _hash(json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8"))[:32]
        source = record_submission(runtime.store, request, request["reason"], identifier=identifier)
        prompt = (Path(__file__).parent / "prompts/knowledge.txt").read_text(encoding="utf-8")
        return runtime.register("knowledge", {"mode": "user_edit", "user_edit": deepcopy(request),
            "submission_ref": source, "reason": request["reason"]}, "user_edit",
            scope={"root": str(runtime.store.home), "paths": ["knowledge", "relations"]}, prompt=prompt)


def _edited_record(runtime, task, baseline, *, prepared):
    request = task["inputs"]["user_edit"]
    record = _merge_edit(baseline, request["changes"])
    if prepared and record != baseline:
        ref = task["inputs"]["submission_ref"]
        source = read_source(runtime.store.home, ref)
        if "content" in request["changes"] and ref not in record["content"]["source_refs"]:
            record["content"]["source_refs"].append(ref)
        record.setdefault("changes", []).append({"at": source["record"]["submitted_at"], "reason": request["reason"],
                                                 "fields": sorted(request["changes"]), "source_refs": [ref]})
    return record


def _references(value):
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"source_refs", "basis_refs", "external_evidence_refs"}:
                yield from child
            else:
                yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def execution_task(runtime, task):
    with runtime.store.locked():
        saved = runtime.task(task["id"])
        if saved.get("execution_input_version"):
            inputs = json.loads(runtime.store.read_version(saved["execution_input_version"]))
        else:
            episodes = []
            refs = []
            for ref in task["inputs"].get("episode_refs", []):
                record = json.loads(runtime.store.read_version(ref["version"]))
                feedback = task["inputs"].get("episode_revision") or task["kind"] == "cognition" and task["trigger"] == "mcp_feedback"
                if record["id"] != ref["id"] or record["state"] not in ({"open", "closed"} if feedback else {"closed"}):
                    raise ValueError("Knowledge analysis requires committed closed episode inputs")
                episodes.append({"ref": ref, "record": record})
                refs.extend(record["source_refs"])
            expansions = []
            for ref in task["inputs"].get("expansion_refs", []):
                record = json.loads(runtime.store.read_version(ref["version"]))
                if record.get("id") != ref["id"] or not {"claims", "proposed_connections", "open_questions"}.issubset(record):
                    raise ValueError("Knowledge analysis requires a committed expansion result")
                expansions.append({"ref": ref, "record": record})
                refs.extend(_references(record))
            if not episodes and not expansions and not task["inputs"].get("user_edit") and not task["inputs"].get("user_correction"):
                raise ValueError("Knowledge input mode is not implemented yet")
            if task["inputs"].get("user_edit") or task["inputs"].get("user_correction"):
                refs.append(task["inputs"]["submission_ref"])
            records = []
            for name, info in task["baseline"].items():
                if name == "cognition/reanalysis.json":
                    continue
                record = json.loads(runtime.store.read_version(info["version"]))
                records.append({"id": record["id"], "version": info["version"], "record": record})
                refs.extend(_references(record))
            sources = {}
            for ref in refs:
                identity = json.dumps(ref, sort_keys=True)
                sources[identity] = read_source(runtime.store.home, ref)
            # shortcut: freeze all existing details; narrow on demand if real inputs reach the subprocess size limit.
            inputs = {**task["inputs"], "episodes": episodes, "expansions": expansions, "records": records,
                      "source_refs": [source["ref"] for source in sources.values()], "sources": list(sources.values())}
            saved["execution_input_version"] = runtime.store.put_version(json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        saved.pop("knowledge_prepared", None)
        runtime._save(saved)
        return {**task, "inputs": inputs}


def allocate_id(runtime, task_id, kind):
    if kind not in {"knowledge", "relation"}:
        raise ValueError("Invalid record kind")
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "knowledge" or task["status"] != "running":
            raise ValueError("Only running knowledge maintenance may allocate these record IDs")
        identifier = uuid.uuid4().hex
        task.setdefault("allocated_record_ids", {})[identifier] = kind
        runtime._save(task)
        return {"id": identifier, "record_kind": kind}


def _workspace(runtime, task):
    root = Path(task["workspace"])
    current, baseline, versions = {"knowledge": {}, "relations": {}}, {"knowledge": {}, "relations": {}}, {}
    files = {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}
    if not set(task["baseline"]).issubset(files):
        raise ValueError("Records must be kept; retire relations with inactive instead of deleting history")
    for name, path in files.items():
        parts = Path(name).parts
        if len(parts) != 2 or parts[0] not in current or Path(name).suffix != ".json":
            raise ValueError("Knowledge task wrote outside its record scope")
        identifier = _identifier(Path(name).stem)
        data = path.read_bytes()
        current[parts[0]][identifier] = json.loads(data)
        versions[(parts[0], identifier)] = _hash(data)
    for name, info in task["baseline"].items():
        parts = Path(name).parts
        baseline[parts[0]][Path(name).stem] = json.loads(runtime.store.read_version(info["version"]))
    return current, baseline, versions


def validate_task(runtime, task, result):
    if task["kind"] != "knowledge" or not (task["inputs"].get("episode_refs") or task["inputs"].get("expansion_refs") or task["inputs"].get("user_edit")):
        raise ValueError("Unsupported knowledge task input")
    if result is None:
        runtime._check_input(task)
        return
    if (not isinstance(result, dict) or set(result) != {"knowledge_refs", "relation_refs", "reason"}
            or not _text(result["reason"])):
        raise ValueError("Invalid knowledge result")
    inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
    records, baseline, versions = _workspace(runtime, task)
    validate_collection(runtime.store, **records, baseline=baseline)
    if task["inputs"].get("user_edit"):
        request = task["inputs"]["user_edit"]
        directory = "knowledge" if request["record_kind"] == "knowledge" else "relations"
        expected = deepcopy(baseline)
        expected[directory][request["record_id"]] = _edited_record(runtime, task, baseline[directory][request["record_id"]], prepared=bool(task.get("knowledge_prepared")))
        if records != expected:
            raise ValueError("User edit must preserve every unspecified field and record")
    changed = {"knowledge": set(), "relations": set()}
    for kind, items in records.items():
        for identifier, record in items.items():
            name = kind + "/" + identifier + ".json"
            if versions[(kind, identifier)] != task["baseline"].get(name, {}).get("version"):
                changed[kind].add(identifier)
                if identifier not in baseline[kind] and task.get("allocated_record_ids", {}).get(identifier) != ("knowledge" if kind == "knowledge" else "relation"):
                    raise ValueError("New stable record ID must be allocated by the program")
                for source in _references(record):
                    if not contains(source, inputs["source_refs"]):
                        raise ValueError("New record source is outside the fixed task input")
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relations")):
        refs = result[field]
        if not isinstance(refs, list) or any(not isinstance(ref, dict) or set(ref) not in ({"id"}, {"id", "version"}) for ref in refs):
            raise ValueError("Invalid changed record references")
        identifiers = [_identifier(ref["id"]) for ref in refs]
        if len(set(identifiers)) != len(identifiers) or set(identifiers) != changed[kind]:
            raise ValueError("Result references must describe the actual record changes")
        for ref in refs:
            if task.get("knowledge_prepared"):
                if ref.get("version") != versions[(kind, ref["id"])]:
                    raise ValueError("Record bytes changed after version preparation")
            elif "version" in ref:
                raise ValueError("The program fills record versions")
    if task.get("knowledge_prepared") and result != task["knowledge_prepared"]:
        raise ValueError("Program-prepared knowledge result changed")


def prepare_result(runtime, task, result):
    if task["inputs"].get("user_edit"):
        request = task["inputs"]["user_edit"]
        directory = "knowledge" if request["record_kind"] == "knowledge" else "relations"
        previous = json.loads(runtime.store.read_version(task["baseline"][directory + "/" + request["record_id"] + ".json"]["version"]))
        edited = _edited_record(runtime, task, previous, prepared=True)
        if edited != previous:
            atomic_json(Path(task["workspace"]) / directory / (request["record_id"] + ".json"), edited)
    result = deepcopy(result)
    for field, kind in (("knowledge_refs", "knowledge"), ("relation_refs", "relations")):
        result[field] = [{"id": ref["id"], "version": runtime.store.put_version(
            (Path(task["workspace"]) / kind / (ref["id"] + ".json")).read_bytes())} for ref in result[field]]
    saved = runtime.task(task["id"])
    saved["knowledge_prepared"] = result
    runtime._save(saved)
    return result


def after_commit(runtime, task):
    if not hasattr(runtime, "knowledge_index"):
        runtime.knowledge_index = KnowledgeIndex(runtime.store)
    runtime.knowledge_index.rebuild()
    from .context import refresh_dependencies
    refresh_dependencies(runtime, task)
    result = json.loads(runtime.store.read_version(task["result_version"]))
    from .cognition import register_analysis
    if task["inputs"].get("episode_refs"):
        register_analysis(runtime, task["inputs"]["episode_refs"], result, task["inputs"]["reason"], task["commit_id"], dependencies=[task["id"]],
                          revision=bool(task["inputs"].get("episode_revision")))
