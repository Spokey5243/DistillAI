"""Read-only task snapshot tools; business modules prepare and validate their snapshots."""
import json
from functools import wraps
from typing import TypedDict

from pydantic import ConfigDict, TypeAdapter, ValidationError, with_config

from .sources import NonblankText, SourceRef


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True,
    json_schema_extra={"anyOf": [{"required": ["id"]}, {"required": ["name"]}]}))
class QueryRecordsArgs(TypedDict, total=False):
    id: NonblankText
    name: NonblankText
    version: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ReadSourceArgs(TypedDict):
    ref: SourceRef


QUERY_RECORDS_ARGS = TypeAdapter(QueryRecordsArgs)
READ_SOURCE_ARGS = TypeAdapter(ReadSourceArgs)


def guard_upstream_tools(registry, definitions, names):
    from jsonschema.validators import validator_for
    for tool in definitions:
        definition = tool["function"]
        name = definition["name"]
        if name not in names:
            continue
        schema = definition["parameters"]
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(schema)
        entry = registry.get_entry(name)
        handler = entry.handler

        @wraps(handler)
        def checked(arguments, _handler=handler, _validator=validator, **kwargs):
            if not _validator.is_valid(arguments):
                return json.dumps({"error": {"code": "invalid_tool_arguments"}})
            return _handler(arguments, **kwargs)

        entry.handler = checked


def register_read_tools(registry, inputs, *, on_records=None, on_sources=None, on_missing_source=None):
    names = set()
    records = inputs.get("records", [])
    sources = inputs.get("sources", [])
    if records:
        def query_records(args, **kwargs):
            try:
                QUERY_RECORDS_ARGS.validate_python(args)
            except ValidationError:
                return json.dumps({"error": {"code": "invalid_query"}})
            if not {"id", "name"}.intersection(args):
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
                    "parameters": QUERY_RECORDS_ARGS.json_schema()},
            check_fn=lambda: True)
        names.add("query_records")
    if sources:
        def read_source(args, **kwargs):
            try:
                READ_SOURCE_ARGS.validate_python(args)
            except ValidationError as error:
                code = "invalid_source_query" if any(len(item["loc"]) <= 1 for item in error.errors(include_input=False)) else "source_not_in_task_snapshot"
                return json.dumps({"error": {"code": code}})
            matches = [item for item in sources if item["ref"] == args.get("ref")]
            if not matches and on_missing_source is not None:
                matches = [on_missing_source(args)]
            if matches and on_sources is not None:
                on_sources([item["ref"] for item in matches])
            return json.dumps({"sources": matches} if matches else {"error": {"code": "source_not_in_task_snapshot"}}, ensure_ascii=False)

        registry.register(name="read_source", toolset="distillai_read", handler=read_source,
            schema={"name": "read_source", "description": "Read an exact source reference frozen for this task.",
                    "parameters": READ_SOURCE_ARGS.json_schema()},
            check_fn=lambda: True)
        names.add("read_source")
    return names


def register_episode_tools(registry, evaluate, revise=None):
    from .episode import BOUNDARY_ARGS, REVISION_ARGS
    def handler(args, **kwargs):
        return json.dumps(evaluate(args), ensure_ascii=False)

    registry.register(name="evaluate_episode_boundary", toolset="distillai_episode", handler=handler,
        schema={"name": "evaluate_episode_boundary", "description": "Validate fixed episode/turn sources and original quotes; compute K/S. Does not publish files or consume a generation.",
                "parameters": BOUNDARY_ARGS.json_schema()},
        check_fn=lambda: True)
    names = {"evaluate_episode_boundary"}
    if revise is not None:
        registry.register(name="evaluate_episode_revision", toolset="distillai_episode",
            handler=lambda args, **kwargs: json.dumps(revise(args), ensure_ascii=False),
            schema={"name": "evaluate_episode_revision", "description": "Check directly affected historical assignments against fixed record versions and actual new-source quotes. Does not judge semantic correctness or publish records.",
                "parameters": REVISION_ARGS.json_schema()}, check_fn=lambda: True)
        names.add("evaluate_episode_revision")
    return names


def register_knowledge_tools(registry, allocate):
    from .knowledge import ALLOCATION_ARGS
    registry.register(name="new_record_id", toolset="distillai_knowledge",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate a new stable record ID for this maintenance task; reuse existing IDs for existing concepts or relations.",
                "parameters": ALLOCATION_ARGS.json_schema()}, check_fn=lambda: True)
    return {"new_record_id"}


def register_cognition_tools(registry, allocate):
    from .cognition import ALLOCATION_ARGS
    registry.register(name="new_record_id", toolset="distillai_cognition",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate a hypothesis ID, or get the reusable observation ID for original user source_refs. Assistant context does not create another performance.",
                "parameters": ALLOCATION_ARGS.json_schema()}, check_fn=lambda: True)
    return {"new_record_id"}


def register_context_tools(registry, allocate):
    from .context import ALLOCATION_ARGS
    registry.register(name="new_record_id", toolset="distillai_context",
        handler=lambda args, **kwargs: json.dumps(allocate(args)),
        schema={"name": "new_record_id", "description": "Allocate an ID only for a new injection candidate. Reuse existing candidate IDs; start new revision at zero and retain existing revision for the program to update.",
                "parameters": ALLOCATION_ARGS.json_schema()}, check_fn=lambda: True)
    return {"new_record_id"}


def register_expansion_tools(registry, request):
    from .expansion import SEARCH_ARGS, FETCH_ARGS
    for name, adapter, description in (("web_search", SEARCH_ARGS, "Find candidate sources. Search snippets are not read evidence."),
                                     ("fetch_page", FETCH_ARGS, "Read a public page excerpt and retain its actual external source reference.")):
        registry.register(name=name, toolset="distillai_expansion",
            handler=lambda args, tool=name, **kwargs: json.dumps(request(tool, args), ensure_ascii=False),
            schema={"name": name, "description": description,
                    "parameters": adapter.json_schema()}, check_fn=lambda: True,
            override=True)  # Each task has its own registry; replace Hermes' built-in web_search with the controller route.
    return {"web_search", "fetch_page"}
