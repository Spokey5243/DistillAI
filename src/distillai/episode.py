"""Session-local episode ownership; model evidence and program scoring stay separate."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from .sources import read_source, queue_path, record_submission
from .storage import atomic_json, _hash, _identifier, ConflictError


def _positions(refs, key, *, limit=None):
    if not isinstance(refs, list):
        raise ValueError("Source references must be a list")
    positions = []
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != {"connector", "session_key", "line_start", "line_end"}
                or ref["connector"] != "codex" or ref["session_key"] != key
                or type(ref["line_start"]) is not int or type(ref["line_end"]) is not int
                or not 1 <= ref["line_start"] <= ref["line_end"]):
            raise ValueError("Invalid session source range")
        if limit is not None and ref["line_end"] > limit:
            raise ValueError("Source exceeds the fixed boundary")
        if positions and ref["line_start"] <= positions[-1]:
            raise ValueError("Source ranges must remain ordered and disjoint")
        positions.extend(range(ref["line_start"], ref["line_end"] + 1))
    return positions


def _refs(key, lines):
    refs = []
    for line in lines:
        if refs and refs[-1]["line_end"] + 1 == line:
            refs[-1]["line_end"] = line
        else:
            refs.append({"connector": "codex", "session_key": key, "line_start": line, "line_end": line})
    return refs


def turns(home, key, line_end):
    if type(line_end) is not int or line_end < 0:
        raise ValueError("Invalid fixed source boundary")
    if not line_end:
        return []
    rows = read_source(home, {"connector": "codex", "session_key": key, "line_start": 1, "line_end": line_end})["rows"]
    rounds = []
    for number, row in enumerate(rows, 1):
        if row["role"] == "tool":
            continue
        if row["role"] == "user" or not rounds:
            rounds.append({"lines": [], "text": ""})
        rounds[-1]["lines"].append(number)
        rounds[-1]["text"] += ("\n" if rounds[-1]["text"] else "") + row["role"] + ": " + row["text"]
    return [{"source_refs": _refs(key, item["lines"]), "text": item["text"]} for item in rounds]


def _keywords(value):
    if not isinstance(value, list) or any(not isinstance(word, str) for word in value):
        raise ValueError("Keywords must be strings")
    words = list(dict.fromkeys(word.strip().lower() for word in value if word.strip()))
    if len(words) > 5:
        raise ValueError("At most five keywords are allowed")
    return words


def _basis(value, allowed, sources, key):
    if not isinstance(value, list) or not value:
        raise ValueError("Original source evidence is required")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"source_ref", "quote"} or not isinstance(item["quote"], str) or not item["quote"].strip():
            raise ValueError("Evidence needs a source reference and an actual quote")
        positions = _positions([item["source_ref"]], key, limit=max(sources, default=0))
        if not positions or not set(positions).issubset(allowed):
            raise ValueError("Evidence is outside the fixed source scope")
        text = "\n".join(sources[position]["text"] for position in positions)
        if item["quote"] not in text:
            raise ValueError("Evidence quote does not occur in the original source")
    return deepcopy(value)


def score_boundary(inputs, args):
    expected = {"episode_ref", "episode_keywords", "episode_source_refs", "episode_basis", "candidates"}
    if not isinstance(args, dict) or set(args) != expected:
        raise ValueError("Invalid boundary evaluation fields")
    if not inputs.get("active_episode_ref") or args["episode_ref"] != inputs["active_episode_ref"]:
        raise ValueError("Boundary evaluation requires the fixed active episode")
    key = inputs["session_key"]
    sources = {}
    for source in inputs["sources"]:
        positions = _positions([source["ref"]], key, limit=source["ref"]["line_start"] + len(source["rows"]) - 1)
        if len(positions) != len(source["rows"]):
            raise ValueError("Source snapshot does not match its physical range")
        sources.update(zip(positions, source["rows"]))
    old_positions = set(_positions(inputs["active_source_refs"], key, limit=max(sources, default=0)))
    selected = _positions(args["episode_source_refs"], key, limit=max(sources, default=0))
    if not selected or not set(selected).issubset(old_positions):
        raise ValueError("Old episode keywords require old episode sources")
    old_words = _keywords(args["episode_keywords"])
    old_basis = _basis(args["episode_basis"], set(selected), sources, key)
    if not isinstance(args["candidates"], list) or not args["candidates"]:
        raise ValueError("Candidate turns are required")
    allowed_turns = {_json(item["source_refs"]) for item in inputs["turns"]}
    seen, evaluations = set(), []
    for candidate in args["candidates"]:
        if not isinstance(candidate, dict) or set(candidate) != {"source_refs", "keywords", "C", "basis", "reason", "group"}:
            raise ValueError("Invalid candidate fields")
        identity = _json(candidate["source_refs"])
        if identity not in allowed_turns or identity in seen:
            raise ValueError("Candidate must name a distinct complete fixed turn")
        seen.add(identity)
        continuity = candidate["C"]
        if type(continuity) is not int or not 0 <= continuity <= 4:
            raise ValueError("Continuity C must be an integer between zero and four")
        if any(not isinstance(candidate[name], str) or not candidate[name].strip() for name in ("reason", "group")):
            raise ValueError("Candidate reason and grouping basis are required")
        words = _keywords(candidate["keywords"])
        basis = _basis(candidate["basis"], set(_positions(candidate["source_refs"], key)), sources, key)
        overlap = len(set(old_words) & set(words)) / len(set(old_words) | set(words)) if old_words and words else None
        score = 4 - continuity if overlap is None else 4 * (1 - (.2 * overlap + .8 * continuity / 4))
        evaluations.append({**deepcopy(candidate), "keywords": words, "basis": basis, "K": overlap, "S": round(score, 12)})
    return {"episode_ref": deepcopy(args["episode_ref"]), "episode_keywords": old_words,
            "episode_source_refs": deepcopy(args["episode_source_refs"]), "episode_basis": old_basis,
            "evaluations": evaluations}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def state_path(home, key):
    queue_path(home, key)
    return Path(home) / "buffers" / (key + ".json")


def state(home, key):
    path = state_path(home, key)
    if not path.exists():
        return {"connector": "codex", "session_key": key, "active_episode_id": None,
                "buffer": [], "processed_line": 0, "material_updates": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def register_material(runtime, ref):
    """Bootstrap one source turn before later turns can compare with a fixed episode."""
    key = ref["session_key"]
    scope = {"root": str(runtime.store.home), "paths": ["episodes", "buffers/" + key + ".json", "cognition/reanalysis.json"]}
    prompt = (Path(__file__).parent / "prompts" / "episode.txt").read_text(encoding="utf-8")
    with runtime.store.locked():
        current = state(runtime.store.home, key)
        if current["active_episode_id"] is None:
            pending = [task for task in runtime.tasks() if task["kind"] == "episode" and task["trigger"] == "material"
                       and task["status"] != "succeeded" and any(source.get("session_key") == key and source.get("line_end", 0) > current["processed_line"]
                                                                  for source in task["inputs"].get("source_refs", []))]
            if pending:
                return pending[0]
            rows = read_source(runtime.store.home, ref)["rows"]
            if not any(row["role"] != "tool" for row in rows):
                return None
            seen_body = False
            for offset, row in enumerate(rows):
                if row["role"] == "user" and seen_body:
                    ref = {**ref, "line_end": ref["line_start"] + offset - 1}
                    break
                seen_body |= row["role"] != "tool"
            return runtime.register("episode", {"source_refs": [ref]}, "material", scope=scope, prompt=prompt)
        return runtime.register_increment(ref, scope=scope, prompt=prompt)


def execution_task(runtime, task):
    if task["kind"] == "correction":
        return _correction_execution(runtime, task)
    with runtime.store.locked():
        saved = runtime.task(task["id"])
        if saved.get("execution_input_version"):
            inputs = json.loads(runtime.store.read_version(saved["execution_input_version"]))
        else:
            refs = task["inputs"]["source_refs"]
            if len(refs) != 1:
                raise ValueError("Material tasks require one contiguous increment")
            ref = refs[0]
            read_source(runtime.store.home, ref)
            key, end = ref["session_key"], ref["line_end"]
            current = state(task["workspace"], key)
            if ref["line_start"] != current["processed_line"] + 1:
                raise ConflictError("Earlier session material has not committed")
            records = {}
            for name, info in task["baseline"].items():
                if name.startswith("episodes/"):
                    record = json.loads(runtime.store.read_version(info["version"]))
                    if record.get("session_key") == key:
                        records[record["id"]] = {"record": record, "version": info["version"]}
            active = records.get(current["active_episode_id"])
            if current["active_episode_id"] is not None and (active is None or active["record"]["state"] != "open"):
                raise ValueError("Active episode is unavailable")
            pending = set(_positions(refs, key, limit=end))
            for item in current["buffer"]:
                pending.update(_positions(item["source_refs"], key, limit=end))
            rounds = [item for item in turns(runtime.store.home, key, end)
                      if pending.intersection(_positions(item["source_refs"], key, limit=end))]
            active_refs = active["record"]["source_refs"] if active else []
            source_lines = set(_positions(active_refs, key, limit=end)) | pending
            for item in rounds:
                source_lines.update(_positions(item["source_refs"], key, limit=end))
            source_refs = _refs(key, sorted(source_lines))
            inputs = {"session_key": key, "new_source_refs": refs, "source_refs": source_refs,
                      "sources": [read_source(runtime.store.home, item) for item in source_refs], "state": current,
                      "active_episode_ref": {"id": active["record"]["id"], "version": active["version"]} if active else None,
                      "active_source_refs": active_refs, "active_episode": active["record"] if active else None,
                      "turns": rounds, "episode_records": records, "line_end": end,
                      "new_episode_ids": [uuid.uuid4().hex for _ in range(len(rounds) + 1)],
                      "boundary_window": task["config"]["values"]["episode"]["switch_buffer_turns"]}
            saved["execution_input_version"] = runtime.store.put_version(_json(inputs).encode("utf-8"))
            runtime._save(saved)
        if saved.pop("episode_prepared", None) is not None:
            current = state(task["workspace"], inputs["session_key"])
            for name in ("processed_line", "material_updates"):
                current[name] = inputs["state"][name]
            # Initialize before the child without rename; upstream Windows read guards compare stat and fstat.
            state_path(task["workspace"], inputs["session_key"]).write_text(json.dumps(current, ensure_ascii=False) + "\n", encoding="utf-8")
            runtime._save(saved)
        from .cognition import reset_reanalysis_workspace
        reset_reanalysis_workspace(runtime, saved)
        runtime._save(saved)
        return {**task, "inputs": inputs}


def evaluate(runtime, task_id, args):
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "episode" or task["status"] != "running" or not task.get("execution_input_version"):
            raise ValueError("Boundary scoring is only available inside a prepared episode task")
        inputs = json.loads(runtime.store.read_version(task["execution_input_version"]))
        result = score_boundary(inputs, args)
        version = runtime.store.put_version(_json(result).encode("utf-8"))
        task["boundary_evaluations"] = list(dict.fromkeys([*task.get("boundary_evaluations", []), version]))
        runtime._save(task)
        return {"evaluation_version": version, **result}


def read_episode_source(runtime, task_id, args):
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "episode" or task["status"] != "running" or not isinstance(args, dict) or set(args) != {"ref"}:
            raise ValueError("Historical source reads require a prepared episode task")
        inputs = _execution(runtime, task)
        positions = set(_positions([args["ref"]], inputs["session_key"], limit=inputs["line_end"]))
        allowed = set(_positions(inputs["source_refs"], inputs["session_key"]))
        for item in inputs["episode_records"].values():
            allowed.update(_positions(item["record"]["source_refs"], inputs["session_key"]))
        if not positions or not positions.issubset(allowed):
            raise ValueError("Source is outside the fixed episode history")
        identity = _json(args["ref"])
        reads = task.setdefault("episode_source_reads", {})
        if identity not in reads:
            source = read_source(runtime.store.home, args["ref"])
            reads[identity] = runtime.store.put_version(_json(source).encode("utf-8"))
            runtime._save(task)
        return json.loads(runtime.store.read_version(reads[identity]))


def evaluate_revision(runtime, task_id, args):
    with runtime.store.locked():
        task = runtime._live(task_id)
        if task["kind"] != "episode" or task["status"] != "running" or not isinstance(args, dict) or set(args) != {"session_key", "episode_refs", "assignments", "reason", "basis"}:
            raise ValueError("Revision scope requires a running material task and new original evidence")
        inputs = _execution(runtime, task)
        _record_refs(args["episode_refs"])
        if args["session_key"] != inputs["session_key"] or any(
                inputs["episode_records"].get(ref.get("id"), {}).get("version") != ref.get("version") for ref in args["episode_refs"]):
            raise ValueError("Revision records must belong to the fixed session snapshot")
        request = {name: args[name] for name in ("session_key", "episode_refs", "assignments", "reason")}
        records = _correction_request(runtime.store, request)
        sources = {}
        for item in inputs["sources"]:
            sources.update(zip(_positions([item["ref"]], inputs["session_key"]), item["rows"]))
        _basis(args["basis"], set(_positions(inputs["new_source_refs"], inputs["session_key"])), sources, inputs["session_key"])
        proof = {**deepcopy(request), "episode_records": records, "basis": args["basis"],
                 "revision_source_refs": [item["source_ref"] for item in args["basis"]]}
        version = runtime.store.put_version(_json(proof).encode("utf-8"))
        task["episode_revision_version"] = version
        runtime._save(task)
        return {"revision_version": version, "episode_refs": args["episode_refs"], "assignments": args["assignments"],
                "reason": args["reason"], "scope_checked": True, "semantic_quality_accepted": False}


def _execution(runtime, task):
    return json.loads(runtime.store.read_version(task["execution_input_version"]))


def _record_refs(refs):
    if not isinstance(refs, list):
        raise ValueError("Record references must be a list")
    ids = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) not in ({"id"}, {"id", "version"}):
            raise ValueError("Invalid episode reference")
        ids.append(_identifier(ref["id"]))
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated episode reference")
    return set(ids)


def _files(task):
    root = Path(task["workspace"])
    files = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    if not set(task["baseline"]).issubset(files):
        raise ValueError("Episode maintenance cannot delete history")
    return files


def _evaluate_versions(runtime, task, inputs):
    previous = {item["evaluation_version"] for item in inputs["state"]["buffer"]}
    current = set(task.get("boundary_evaluations", []))
    return {version: json.loads(runtime.store.read_version(version)) for version in previous | current}, current


def validate_task(runtime, task, result):
    if task["kind"] == "correction":
        return _validate_correction(runtime, task, result)
    if task["kind"] != "episode" or task["trigger"] != "material":
        raise ValueError("Unsupported episode task")
    if result is None:
        for ref in task["inputs"]["source_refs"]:
            read_source(runtime.store.home, ref)
        return
    fields = {"episode_refs", "closed_episode_refs", "revised_episode_refs", "buffered_source_refs", "reason"}
    if not isinstance(result, dict) or set(result) != fields or not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("Invalid episode result")
    inputs = _execution(runtime, task)
    key, end = inputs["session_key"], inputs["line_end"]
    all_rows = read_source(runtime.store.home, {"connector": "codex", "session_key": key, "line_start": 1, "line_end": end})["rows"]
    body = {number for number, row in enumerate(all_rows, 1) if row["role"] != "tool"}
    files = _files(task)
    from .cognition import validate_reanalysis_workspace
    validate_reanalysis_workspace(runtime, task)
    state_name = "buffers/" + key + ".json"
    current = json.loads(files[state_name])
    if set(current) != set(inputs["state"]):
        raise ValueError("Invalid session state fields")
    for name in ("connector", "session_key", "processed_line", "material_updates"):
        expected = task.get("episode_prepared", {}).get(name, inputs["state"][name])
        if current[name] != expected or type(current[name]) is not type(expected):
            raise ValueError("Agent changed protected processing state")
    if not isinstance(current["buffer"], list):
        raise ValueError("Buffer must be a list")
    evaluations, current_versions = _evaluate_versions(runtime, task, inputs)
    ownership, records, changed = {}, {}, set()
    old_records = inputs["episode_records"]
    revision = json.loads(runtime.store.read_version(task["episode_revision_version"])) if task.get("episode_revision_version") else None
    requested = {item["episode_id"]: item["source_refs"] for item in revision["assignments"]} if revision else {}
    for name, data in files.items():
        if name in {state_name, "cognition/reanalysis.json"}:
            continue
        baseline = task["baseline"].get(name)
        if not name.startswith("episodes/") or name.count("/") != 1 or not name.endswith(".json"):
            raise ValueError("Episode task wrote outside its record scope")
        identifier = _identifier(Path(name).stem)
        record = json.loads(data)
        if record.get("session_key") != key:
            if baseline is None or _hash(data) != baseline["version"]:
                raise ValueError("Episode task changed another session")
            continue
        required = {"id", "connector", "session_key", "topic", "goal", "state", "source_refs", "boundary_basis"}
        allowed = required | {"close_reason", "summary", "related_episode_ids"}
        if set(record) - allowed or not required.issubset(record) or record["id"] != identifier or record["connector"] != "codex":
            raise ValueError("Invalid episode record identity or fields")
        if record["state"] not in ("open", "closed") or any(not isinstance(record[field], str) or not record[field].strip() for field in ("topic", "goal")):
            raise ValueError("Episode needs a topic, goal and state")
        basis = record["boundary_basis"]
        if (not isinstance(basis, dict) or set(basis) != {"reason", "source_refs", "evaluation_versions"}
                or not isinstance(basis["reason"], str) or not basis["reason"].strip()
                or not isinstance(basis["evaluation_versions"], list)):
            raise ValueError("Episode boundary basis is required")
        for source in [*record["source_refs"], *basis["source_refs"]]:
            read_source(runtime.store.home, source)
        positions = _positions(record["source_refs"], key, limit=end)
        if not set(positions) & body or not set(_positions(basis["source_refs"], key, limit=end)):
            raise ValueError("Episode needs actual body sources and boundary evidence")
        if record["state"] == "closed" and any(not isinstance(record.get(field), str) or not record[field].strip() for field in ("summary", "close_reason")):
            raise ValueError("Closed episodes need a summary and closing basis")
        if identifier not in old_records and identifier not in inputs["new_episode_ids"]:
            raise ValueError("New episode ID was not provided by the program")
        for related in record.get("related_episode_ids", []):
            related = _identifier(related)
            if related == identifier or "episodes/" + related + ".json" not in files:
                raise ValueError("Related episode must identify another saved record")
        for position in set(positions) & body:
            if position in ownership:
                raise ValueError("Body source belongs to more than one episode")
            ownership[position] = identifier
        records[identifier] = record
        if baseline is None or _hash(data) != baseline["version"]:
            changed.add(identifier)
        if identifier in requested and old_records[identifier]["record"]["state"] == "closed":
            old = old_records[identifier]["record"]
            if (record["source_refs"] != requested[identifier] or set(record) != set(old)
                    or any(record[field] != old[field] for field in old if field not in {"source_refs", "boundary_basis", "summary"})
                    or record["boundary_basis"]["reason"] != revision["reason"] or record["boundary_basis"]["evaluation_versions"]
                    or not set(_positions(record["boundary_basis"]["source_refs"], key)).issubset(_positions(record["source_refs"], key))):
                raise ValueError("Historical revisions must stay inside the checked assignment and field scope")
    active = [identifier for identifier, record in records.items() if record["state"] == "open"]
    if len(active) > 1 or current["active_episode_id"] != (active[0] if active else None):
        raise ValueError("Session must identify its only open episode")
    buffered = []
    for item in current["buffer"]:
        if not isinstance(item, dict) or set(item) != {"source_refs", "evaluation_version", "keywords", "C", "reason", "group"}:
            raise ValueError("Invalid buffer item")
        evaluation = evaluations.get(item["evaluation_version"])
        match = next((candidate for candidate in evaluation["evaluations"] if candidate["source_refs"] == item["source_refs"]), None) if evaluation else None
        if match is None or any(item[name] != match[name] for name in ("keywords", "C", "reason", "group")) or match["S"] < 2:
            raise ValueError("Buffer must use recorded program scoring")
        positions = _positions(item["source_refs"], key, limit=end)
        for position in set(positions) & body:
            if position in ownership:
                raise ValueError("Buffered and assigned body sources overlap")
            ownership[position] = "buffer"
        buffered.extend(positions)
    if set(ownership) != body:
        raise ValueError("Processed body sources must have an episode or buffer without omissions")
    for turn in turns(runtime.store.home, key, end):
        owners = {ownership[position] for position in _positions(turn["source_refs"], key, limit=end)}
        if len(owners) != 1:
            raise ValueError("A user turn and its assistant fragments cannot be split")
    old_active = inputs["active_episode_ref"]
    if old_active:
        old_id = old_active["id"]
        newly_created = set(records) - set(old_records)
        if newly_created - {current["active_episode_id"]}:
            raise ValueError("Unconfirmed independent exchanges must remain buffered")
        if records[old_id]["goal"] != inputs["active_episode"]["goal"]:
            raise ValueError("Ordinary new material cannot rewrite the old goal")
        for old_id_checked, old in old_records.items():
            old_body = set(_positions(old["record"]["source_refs"], key, limit=end)) & body
            proposed = {position: identifier for identifier, refs in requested.items() for position in _positions(refs, key)}
            if any(ownership[position] != proposed.get(position, old_id_checked) for position in old_body):
                raise ValueError("Boundary corrections require an explicit correction task")
            if old["record"]["state"] == "closed" and old_id_checked in changed and old_id_checked not in requested:
                raise ValueError("Closed history requires a directly scoped correction task")
        old_body = set(_positions(inputs["active_source_refs"], key, limit=end))
        latest = {_json(candidate["source_refs"]): candidate for version in task.get("boundary_evaluations", [])
                  for candidate in evaluations[version]["evaluations"]}
        for turn in inputs["turns"]:
            positions = set(_positions(turn["source_refs"], key, limit=end))
            if positions & old_body:
                continue
            candidate = latest.get(_json(turn["source_refs"]))
            if candidate is None:
                raise ValueError("New user turns require program boundary evaluation")
            if ownership[min(positions)] == old_id and candidate["S"] >= 2:
                raise ValueError("An uncertain new turn must remain buffered until confirmed")
        if current["active_episode_id"] != old_id:
            new_id = current["active_episode_id"]
            if new_id is None or records[old_id]["state"] != "closed":
                raise ValueError("Material tasks may close only by switching to another episode")
            selected = set(_positions(records[new_id]["source_refs"], key, limit=end)) & body
            approved = []
            for version in records[new_id]["boundary_basis"]["evaluation_versions"]:
                if version not in current_versions:
                    raise ValueError("Switch needs a current boundary evaluation")
                for candidate in evaluations[version]["evaluations"]:
                    positions = set(_positions(candidate["source_refs"], key, limit=end))
                    if positions.issubset(selected):
                        approved.append(candidate)
            unique = {_json(candidate["source_refs"]): candidate for candidate in approved}
            if (len(unique) < inputs["boundary_window"] or any(item["S"] < 3 for item in unique.values())
                    or len({item["group"] for item in unique.values()}) != 1
                    or set().union(*(set(_positions(item["source_refs"], key, limit=end)) for item in unique.values())) != selected):
                raise ValueError("Switch requires a whole window with one shared new exchange")
        for previous in inputs["state"]["buffer"]:
            positions = _positions(previous["source_refs"], key, limit=end)
            if any(ownership[position] != "buffer" for position in positions):
                if not any(set(positions).issubset(_positions(candidate["source_refs"], key, limit=end))
                           for version in current_versions for candidate in evaluations[version]["evaluations"]):
                    raise ValueError("Existing buffer must be jointly re-evaluated before reassignment")
    else:
        created = set(records) - set(old_records)
        if len(created) != 1 or current["active_episode_id"] not in created or changed - created - set(requested):
            raise ValueError("Initial material must establish one open episode and preserve closed history")
    expected_closed = {identifier for identifier in changed if records[identifier]["state"] == "closed"
                       and (identifier not in old_records or old_records[identifier]["record"]["state"] == "open")}
    expected_revised = {identifier for identifier in changed if identifier in old_records
                        and (old_records[identifier]["record"]["state"] == "closed" or identifier in requested)}
    if (_record_refs(result["episode_refs"]) != changed or _record_refs(result["closed_episode_refs"]) != expected_closed
            or _record_refs(result["revised_episode_refs"]) != expected_revised
            or _positions(result["buffered_source_refs"], key, limit=end) != sorted(buffered)):
        raise ValueError("Episode result does not describe the actual changes and buffer")
    if task.get("episode_prepared"):
        if result != task["episode_prepared"]["result"]:
            raise ValueError("Program-prepared episode result was changed")
        for ref in result["episode_refs"]:
            if _hash(files["episodes/" + ref["id"] + ".json"]) != ref["version"]:
                raise ValueError("Episode bytes changed after result version preparation")
    elif any("version" in ref for name in ("episode_refs", "closed_episode_refs", "revised_episode_refs") for ref in result[name]):
        raise ValueError("The program fills committed record versions")


def prepare_result(runtime, task, result):
    if task["kind"] == "correction":
        result = deepcopy(result)
        for field in ("episode_refs", "revised_episode_refs"):
            result[field] = [{"id": ref["id"], "version": runtime.store.put_version(
                (Path(task["workspace"]) / "episodes" / (ref["id"] + ".json")).read_bytes())} for ref in result[field]]
        from .cognition import mark_reanalysis
        mark_reanalysis(runtime, task, result)
        saved = runtime.task(task["id"])
        saved["episode_prepared"] = {"result": result}
        runtime._save(saved)
        return result
    inputs = _execution(runtime, task)
    current = state(task["workspace"], inputs["session_key"])
    current["processed_line"] = inputs["line_end"]
    active = current["active_episode_id"]
    if active != inputs["state"]["active_episode_id"]:
        current["material_updates"] = 1
    else:
        record = json.loads((Path(task["workspace"]) / "episodes" / (active + ".json")).read_text(encoding="utf-8"))
        previous = inputs["episode_records"][active]["record"]
        added = set(_positions(record["source_refs"], inputs["session_key"], limit=inputs["line_end"])) - set(
            _positions(previous["source_refs"], inputs["session_key"], limit=inputs["line_end"]))
        current["material_updates"] = inputs["state"]["material_updates"] + int(bool(added))
    atomic_json(state_path(task["workspace"], inputs["session_key"]), current)
    result = deepcopy(result)
    for field in ("episode_refs", "closed_episode_refs", "revised_episode_refs"):
        result[field] = [{"id": ref["id"], "version": runtime.store.put_version(
            (Path(task["workspace"]) / "episodes" / (ref["id"] + ".json")).read_bytes())} for ref in result[field]]
    if task.get("episode_revision_version"):
        revision = json.loads(runtime.store.read_version(task["episode_revision_version"]))
        targets = {item["episode_id"] for item in revision["assignments"]}
        revised = [ref for ref in result["episode_refs"] if ref["id"] in targets]
        if revised:
            from .cognition import mark_reanalysis
            mark_reanalysis(runtime, task, {"episode_refs": revised}, inputs=revision)
    saved = runtime.task(task["id"])
    saved["episode_prepared"] = {"processed_line": current["processed_line"],
                                 "material_updates": current["material_updates"], "result": result}
    runtime._save(saved)
    return result


def after_commit(runtime, task):
    result = json.loads(runtime.store.read_version(task["result_version"]))
    inputs = _execution(runtime, task)
    closed = {ref["id"]: ref for ref in [*result["closed_episode_refs"], *result["revised_episode_refs"]]}
    if closed:
        from .knowledge import register_episode_analysis
        register_episode_analysis(runtime, list(closed.values()), result["reason"], task["commit_id"], dependencies=[task["id"]],
                                  revision=task["kind"] == "correction" or bool(task.get("episode_revision_version")))
    opened = [ref for ref in result["episode_refs"] if json.loads(runtime.store.read_version(ref["version"]))["state"] == "open"]
    if opened:
        from .context import register_prepare
        updates = state(runtime.store.home, inputs["session_key"])["material_updates"]
        register_prepare(runtime, inputs["session_key"], opened[0], updates,
                         result["reason"], dependencies=[task["id"]], force=task["kind"] == "correction")


def _correction_request(store, request):
    if (not isinstance(request, dict) or set(request) != {"session_key", "episode_refs", "assignments", "reason"}
            or not isinstance(request["reason"], str) or not request["reason"].strip()):
        raise ValueError("Correction requires fixed episode versions, assignments and a reason")
    key = request["session_key"]
    queue_path(store.home, key)
    refs = request["episode_refs"]
    identifiers = _record_refs(refs)
    if not identifiers or any(set(ref) != {"id", "version"} for ref in refs):
        raise ValueError("Correction requires expected versions")
    records, before = {}, set()
    for ref in refs:
        path = store.home / "episodes" / (ref["id"] + ".json")
        if not path.exists() or _hash(path.read_bytes()) != _identifier(ref["version"], 64):
            raise ConflictError("Episode version changed; reload before correcting")
        record = json.loads(store.read_version(ref["version"]))
        if record.get("id") != ref["id"] or record.get("session_key") != key or record.get("connector") != "codex":
            raise ValueError("Corrections are scoped to existing records in one session")
        records[ref["id"]] = record
        positions = set(_positions(record["source_refs"], key))
        if before.intersection(positions):
            raise ValueError("Existing source ownership overlaps")
        before.update(positions)
    assignments = request["assignments"]
    if not isinstance(assignments, list) or len(assignments) != len(identifiers):
        raise ValueError("Every affected episode needs one assignment")
    owners, assigned = {}, set()
    for item in assignments:
        if not isinstance(item, dict) or set(item) != {"episode_id", "source_refs"} or item["episode_id"] not in identifiers or item["episode_id"] in assigned:
            raise ValueError("Unknown or repeated correction target")
        assigned.add(item["episode_id"])
        positions = _positions(item["source_refs"], key)
        if not positions or any(position in owners for position in positions):
            raise ValueError("Revised sources must be nonempty and disjoint")
        owners.update({position: item["episode_id"] for position in positions})
    if set(owners) != before:
        raise ValueError("A correction cannot add or lose original source positions")
    for turn in turns(store.home, key, max(before)):
        positions = set(_positions(turn["source_refs"], key))
        if positions.intersection(before) and (not positions.issubset(before) or len({owners[position] for position in positions}) != 1):
            raise ValueError("Correction cannot split a user turn and its assistant fragments")
    if all(item["source_refs"] == records[item["episode_id"]]["source_refs"] for item in assignments):
        raise ValueError("Correction must change source ownership")
    return records


def register_correction(runtime, request):
    with runtime.store.locked():
        records = _correction_request(runtime.store, request)
        identifier = _hash(_json(request).encode("utf-8"))[:32]
        submission = record_submission(runtime.store, request, request["reason"], identifier=identifier)
        prompt = (Path(__file__).parent / "prompts/episode.txt").read_text(encoding="utf-8")
        return runtime.register("correction", {**deepcopy(request), "submission_ref": submission}, "user_ownership_correction",
            scope={"root": str(runtime.store.home), "paths": [*("episodes/" + identifier + ".json" for identifier in records),
                "cognition/reanalysis.json"]}, prompt=prompt)


def _correction_execution(runtime, task):
    with runtime.store.locked():
        saved = runtime.task(task["id"])
        if saved.get("execution_input_version"):
            inputs = _execution(runtime, saved)
        else:
            request = {name: task["inputs"][name] for name in ("session_key", "episode_refs", "assignments", "reason")}
            records = _correction_request(runtime.store, request)
            refs = [ref for record in records.values() for ref in record["source_refs"]]
            inputs = {**task["inputs"], "episode_records": records, "source_refs": [*refs, task["inputs"]["submission_ref"]],
                "sources": [read_source(runtime.store.home, ref) for ref in [*refs, task["inputs"]["submission_ref"]]]}
            saved["execution_input_version"] = runtime.store.put_version(_json(inputs).encode("utf-8"))
        # Retry starts from the same untouched program state, including after publication rollback.
        from .cognition import reset_reanalysis_workspace
        reset_reanalysis_workspace(runtime, saved)
        saved.pop("episode_prepared", None)
        runtime._save(saved)
        return {**task, "inputs": inputs}


def _validate_correction(runtime, task, result):
    runtime._check_input(task)
    if result is None:
        return
    inputs = _execution(runtime, task)
    expected = {item["episode_id"]: item["source_refs"] for item in inputs["assignments"]}
    fields = {"episode_refs", "closed_episode_refs", "revised_episode_refs", "buffered_source_refs", "reason"}
    if (not isinstance(result, dict) or set(result) != fields or result["reason"] != inputs["reason"]
            or result["closed_episode_refs"] or result["buffered_source_refs"]
            or _record_refs(result["episode_refs"]) != set(expected) or _record_refs(result["revised_episode_refs"]) != set(expected)):
        raise ValueError("Correction result must describe the requested revised records")
    files = _files(task)
    if set(files) - (set(task["baseline"]) | {"cognition/reanalysis.json"}):
        raise ValueError("Correction cannot create other records")
    from .cognition import validate_reanalysis_workspace
    validate_reanalysis_workspace(runtime, task)
    for identifier, refs in expected.items():
        record = json.loads(files["episodes/" + identifier + ".json"])
        old = inputs["episode_records"][identifier]
        if (record.get("source_refs") != refs or set(record) != set(old)
                or any(record[name] != old[name] for name in old if name not in {"source_refs", "boundary_basis", "summary"})):
            raise ValueError("Correction changed fields outside the explicit assignment")
        basis = record["boundary_basis"]
        if (not isinstance(basis, dict) or set(basis) != {"reason", "source_refs", "evaluation_versions"}
                or basis["reason"] != inputs["reason"] or basis["evaluation_versions"]
                or not _positions(basis["source_refs"], inputs["session_key"])
                or not set(_positions(basis["source_refs"], inputs["session_key"])).issubset(_positions(refs, inputs["session_key"]))):
            raise ValueError("Correction basis must describe the newly assigned original sources")
        if record["state"] == "closed" and (not isinstance(record.get("summary"), str) or not record["summary"].strip()):
            raise ValueError("Closed revision needs a summary")
    prepared = task.get("episode_prepared")
    if prepared and result != prepared["result"]:
        raise ValueError("Program-prepared correction result changed")
    for field in ("episode_refs", "revised_episode_refs"):
        for ref in result[field]:
            if prepared and ref.get("version") != _hash(files["episodes/" + ref["id"] + ".json"]):
                raise ValueError("Revised record bytes changed after preparation")
            if not prepared and "version" in ref:
                raise ValueError("The program fills revision versions")
