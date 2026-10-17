"""Versioned control configuration; secret-bearing records stay in private config storage."""
from copy import deepcopy
import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config

from .storage import ConflictError
from .windows import canonical_directory


DEFAULTS = {
    "llm": {"api": "chat_completions", "base_url": "", "model": "", "api_key": "", "parameters": {}},
    "runtime": {"max_model_calls": 16, "poll_interval_seconds": 1},
    "episode": {"switch_buffer_turns": 3},
    "context": {"refresh_update_count": 3},
    "expansion": {"interval_seconds": 3600, "batch_size": 10},
    "search": {"api_key": ""},
    "workspace": {"paths": []},
}


PositiveInt = Annotated[int, Field(gt=0)]
PositiveNumber = Annotated[int | float, Field(gt=0, le=sys.float_info.max)]
SafeText = Annotated[str, Field(pattern=r"^[^\x00-\x1f]*$")]


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Thinking(TypedDict):
    type: Literal["disabled"]


@with_config(ConfigDict(strict=True, extra="forbid"))
class ModelParameters(TypedDict, total=False):
    max_tokens: PositiveInt
    temperature: Annotated[int | float, Field(ge=0, le=2)]
    top_p: Annotated[int | float, Field(gt=0, le=1)]
    thinking: _Thinking


@with_config(ConfigDict(strict=True, extra="forbid"))
class _LLM(TypedDict):
    api: Literal["chat_completions"]
    base_url: SafeText
    model: SafeText
    api_key: Annotated[str, Field(pattern=r"^[ -~]*$")]
    parameters: ModelParameters


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Runtime(TypedDict):
    max_model_calls: PositiveInt
    poll_interval_seconds: PositiveNumber


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Episode(TypedDict):
    switch_buffer_turns: PositiveInt


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Context(TypedDict):
    refresh_update_count: PositiveInt


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Expansion(TypedDict):
    interval_seconds: PositiveNumber
    batch_size: PositiveInt


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Search(TypedDict):
    api_key: Annotated[str, Field(pattern=r"^[!-~]*$")]


@with_config(ConfigDict(strict=True, extra="forbid"))
class _Workspace(TypedDict):
    paths: list[str]


@with_config(ConfigDict(strict=True, extra="forbid"))
class ConfigValues(TypedDict):
    llm: _LLM
    runtime: _Runtime
    episode: _Episode
    context: _Context
    expansion: _Expansion
    search: _Search
    workspace: _Workspace


CONFIG_VALUES = TypeAdapter(ConfigValues)


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class UpdateArgs(TypedDict):
    # Config.update owns conflict status and detailed errors for partial patches.
    expected_version: Any
    values: Any


class ConfigError(ValueError):
    def __init__(self, fields):
        super().__init__("Invalid configuration fields")
        self.fields = fields


class Config:
    def __init__(self, store, protected_paths=()):
        self.store = store
        self.protected = (store.home, Path(__file__).resolve().parents[2], *map(Path, protected_paths),
            *store.home.parent.glob(store.home.name + ".migration-backup-*"),
            *store.home.parent.glob(store.home.name + ".rollback-retired-*"))
        with store.locked():
            if store.state.current_config() is None:
                self._save({"version": 1, "values": deepcopy(DEFAULTS)})

    def _save(self, record):
        current = self.store.state.current_config()
        version = record["version"]
        while (self.store.home / "config" / f"{version}.json").exists():
            version += 1
        record["version"] = version
        path = self.store.home / "config" / f"{version}.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            import os
            os.fsync(stream.fileno())
        self.store.state.set_config(version, expected=current)

    def private(self, version=None):
        with self.store.locked():
            if version is not None and (type(version) is not int or version < 1):
                raise ValueError("Invalid configuration version")
            version = self.store.state.current_config() if version is None else version
            path = self.store.home / "config" / f"{version}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["values"].setdefault("search", deepcopy(DEFAULTS["search"]))
            return record

    @staticmethod
    def _redact(record):
        result = deepcopy(record)
        result["api_key_configured"] = bool(result["values"]["llm"]["api_key"])
        result["values"]["llm"]["api_key"] = ""
        result["search_key_configured"] = bool(result["values"]["search"]["api_key"])
        result["values"]["search"]["api_key"] = ""
        return result

    def read(self):
        return self._redact(self.private())

    def snapshot(self):
        return self.read()

    def update(self, expected_version, patch):
        with self.store.locked():
            current = self.private()
            if type(expected_version) is not int or expected_version != current["version"]:
                raise ConflictError("Configuration version changed")
            fields = {}
            values = deepcopy(current["values"])
            if not isinstance(patch, dict):
                raise ConfigError({"values": "Expected an object"})
            for group, changed in patch.items():
                if group not in DEFAULTS or not isinstance(changed, dict):
                    fields[str(group)] = "Unknown group or invalid object"
                    continue
                for field, value in changed.items():
                    name = f"{group}.{field}"
                    if field not in DEFAULTS[group]:
                        fields[name] = "Unknown field"
                    elif name in {"llm.api_key", "search.api_key"} and value == "":
                        continue  # A blank redacted display must not erase the control credential.
                    elif name in {"llm.api_key", "search.api_key"} and value is None:
                        values[group][field] = ""
                    else:
                        values[group][field] = deepcopy(value)
            self._validate(values, fields)
            if fields:
                raise ConfigError(fields)
            record = {"version": current["version"] + 1, "values": values}
            self._save(record)
            return self._redact(record)

    def _validate(self, values, fields):
        try:
            CONFIG_VALUES.validate_python(values)
        except ValidationError as error:
            for item in error.errors(include_url=False, include_input=False):
                parts = [str(part) for part in item["loc"] if part not in {"int", "float"}]
                fields[".".join(parts)] = item["msg"]
            return
        llm = values["llm"]
        if isinstance(llm["base_url"], str) and llm["base_url"]:
            try:
                url = urlsplit(llm["base_url"])
                if not llm["base_url"].isascii() or any(c.isspace() for c in llm["base_url"]) or url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError("Invalid endpoint")
                url.port
            except ValueError:
                fields["llm.base_url"] = "Expected an HTTP(S) base URL without credentials, query or fragment"
        if "thinking" in llm["parameters"] and not llm["model"].startswith("deepseek-"):
            fields["llm.parameters.thinking"] = "Unsupported parameter for this model"
        paths = values["workspace"]["paths"]
        normalized = []
        for index, value in enumerate(paths):
            name = f"workspace.paths.{index}"
            if not isinstance(value, str) or not Path(value).is_absolute():
                fields[name] = "Expected an absolute directory path"
                continue
            try:
                path = canonical_directory(value)
            except OSError:
                fields[name] = "Directory is unavailable or has an unsupported reparse path"
                continue
            if any(path == p or path in p.parents or p in path.parents for p in self.protected):
                fields[name] = "Path overlaps program or private runtime state"
                continue
            if str(path) not in normalized:
                normalized.append(str(path))
        values["workspace"]["paths"] = normalized
