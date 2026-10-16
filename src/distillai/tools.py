"""Read-only task snapshot tools; business modules prepare and validate their snapshots."""
import json


def register_read_tools(registry, inputs, *, on_records=None, on_sources=None, on_missing_source=None):
    names = set()
    records = inputs.get("records", [])
    sources = inputs.get("sources", [])
    if records:
        def query_records(args, **kwargs):
            if not isinstance(args, dict) or not {"id", "name"}.intersection(args) or set(args) - {"id", "name", "version"} or any(
                    not isinstance(value, str) or not value.strip() for value in args.values()):
                return json.dumps({"error": {"code": "invalid_query"}})
            matches = []
            for item in records:
                record = item["record"]
                if "id" in args and item["id"] != args["id"]:
                    continue
                if "version" in args and item["version"] != args["version"]:
                    continue
                if "name" in args and args["name"].casefold() not in {
                        str(name).casefold() for name in [record.get("name", ""), *record.get("aliases", [])]}:
                    continue
                matches.append(item)
            if on_records is not None:
                on_records([{name: item[name] for name in ("id", "version", "record_kind")} for item in matches])
            return json.dumps({"records": matches}, ensure_ascii=False)

        registry.register(name="query_records", toolset="distillai_read", handler=query_records,
            schema={"name": "query_records", "description": "Read frozen records by exact ID or name/alias.",
                    "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "version": {"type": "string"}},
                                   "anyOf": [{"required": ["id"]}, {"required": ["name"]}], "additionalProperties": False}},
            check_fn=lambda: True)
        names.add("query_records")
    if sources:
        def read_source(args, **kwargs):
            if not isinstance(args, dict) or set(args) != {"ref"}:
                return json.dumps({"error": {"code": "invalid_source_query"}})
            matches = [item for item in sources if item["ref"] == args.get("ref")]
            if not matches and on_missing_source is not None:
                matches = [on_missing_source(args)]
            if matches and on_sources is not None:
                on_sources([item["ref"] for item in matches])
            return json.dumps({"sources": matches} if matches else {"error": {"code": "source_not_in_task_snapshot"}}, ensure_ascii=False)

        registry.register(name="read_source", toolset="distillai_read", handler=read_source,
            schema={"name": "read_source", "description": "Read an exact source reference frozen for this task.",
                    "parameters": {"type": "object", "properties": {"ref": {"type": "object"}},
                                   "required": ["ref"], "additionalProperties": False}},
            check_fn=lambda: True)
        names.add("read_source")
    return names


def register_episode_tools(registry, evaluate, revise=None):
    def handler(args, **kwargs):
        return json.dumps(evaluate(args), ensure_ascii=False)

    registry.register(name="evaluate_episode_boundary", toolset="distillai_episode", handler=handler,
        schema={"name": "evaluate_episode_boundary", "description": "Validate fixed episode/turn sources and original quotes; compute K/S. Does not publish files or consume a generation.",
                "parameters": {"type": "object", "properties": {
                    "episode_ref": {"type": "object"}, "episode_keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "episode_source_refs": {"type": "array", "items": {"type": "object"}},
                    "episode_basis": {"type": "array", "items": {"type": "object"}},
                    "candidates": {"type": "array", "items": {"type": "object", "properties": {
                        "source_refs": {"type": "array", "items": {"type": "object"}}, "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                        "C": {"type": "integer", "minimum": 0, "maximum": 4}, "basis": {"type": "array", "items": {"type": "object"}},
                        "reason": {"type": "string"}, "group": {"type": "string"}},
                        "required": ["source_refs", "keywords", "C", "basis", "reason", "group"], "additionalProperties": False}}},
                    "required": ["episode_ref", "episode_keywords", "episode_source_refs", "episode_basis", "candidates"], "additionalProperties": False}},
        check_fn=lambda: True)
    names = {"evaluate_episode_boundary"}
    if revise is not None:
        registry.register(name="evaluate_episode_revision", toolset="distillai_episode",
            handler=lambda args, **kwargs: json.dumps(revise(args), ensure_ascii=False),
            schema={"name": "evaluate_episode_revision", "description": "Check directly affected historical assignments against fixed record versions and actual new-source quotes. Does not judge semantic correctness or publish records.",
                "parameters": {"type": "object", "properties": {"session_key": {"type": "string"},
                    "episode_refs": {"type": "array", "items": {"type": "object"}}, "assignments": {"type": "array", "items": {"type": "object"}},
                    "reason": {"type": "string"}, "basis": {"type": "array", "items": {"type": "object"}}},
                    "required": ["session_key", "episode_refs", "assignments", "reason", "basis"], "additionalProperties": False}}, check_fn=lambda: True)
        names.add("evaluate_episode_revision")
    return names


def register_knowledge_tools(registry, allocate):
    registry.register(name="new_record_id", toolset="distillai_knowledge",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate a new stable record ID for this maintenance task; reuse existing IDs for existing concepts or relations.",
                "parameters": {"type": "object", "properties": {"record_kind": {"type": "string", "enum": ["knowledge", "relation"]}},
                               "required": ["record_kind"], "additionalProperties": False}}, check_fn=lambda: True)
    return {"new_record_id"}


def register_cognition_tools(registry, allocate):
    registry.register(name="new_record_id", toolset="distillai_cognition",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate a hypothesis ID, or get the reusable observation ID for original user source_refs. Assistant context does not create another performance.",
                "parameters": {"type": "object", "properties": {"record_kind": {"type": "string", "enum": ["observation", "hypothesis"]},
                    "source_refs": {"type": "array", "items": {"type": "object"}}},
                    "required": ["record_kind"], "additionalProperties": False}}, check_fn=lambda: True)
    return {"new_record_id"}


def register_context_tools(registry, allocate):
    registry.register(name="new_record_id", toolset="distillai_context",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate an ID only for a new injection candidate. Reuse existing candidate IDs; start new revision at zero and retain existing revision for the program to update.",
                "parameters": {"type": "object", "properties": {"record_kind": {"type": "string", "enum": ["candidate"]}},
                               "required": ["record_kind"], "additionalProperties": False}}, check_fn=lambda: True)
    return {"new_record_id"}


def register_expansion_tools(registry, request):
    for name, field, description in (("web_search", "query", "Find candidate sources. Search snippets are not read evidence."),
                                     ("fetch_page", "url", "Read a public page excerpt and retain its actual external source reference.")):
        registry.register(name=name, toolset="distillai_expansion",
            handler=lambda args, tool=name, **kwargs: json.dumps(request(tool, args), ensure_ascii=False),
            schema={"name": name, "description": description,
                    "parameters": {"type": "object", "properties": {field: {"type": "string"}},
                                   "required": [field], "additionalProperties": False}}, check_fn=lambda: True,
            override=True)  # Each task has its own registry; replace Hermes' built-in web_search with the controller route.
    return {"web_search", "fetch_page"}
