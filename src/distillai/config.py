"""Versioned control configuration; secret-bearing records stay in private config storage."""
from copy import deepcopy
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .storage import atomic_json, ConflictError
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


def _finite(value):
    return type(value) in (int, float) and abs(value) <= sys.float_info.max and math.isfinite(value)


class ConfigError(ValueError):
    def __init__(self, fields):
        super().__init__("Invalid configuration fields")
        self.fields = fields


class Config:
    def __init__(self, store, protected_paths=()):
        self.store = store
        self.protected = (store.home, Path(__file__).resolve().parents[2], *map(Path, protected_paths))
        self.path = store.home / "config.json"
        with store.locked():
            if not self.path.exists():
                self._save({"version": 1, "values": deepcopy(DEFAULTS)})

    def _save(self, record):
        atomic_json(self.store.home / "config" / f"{record['version']}.json", record)
        atomic_json(self.path, record)

    def private(self, version=None):
        with self.store.locked():
            if version is not None and (type(version) is not int or version < 1):
                raise ValueError("Invalid configuration version")
            path = self.path if version is None else self.store.home / "config" / f"{version}.json"
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
        key = values["search"]["api_key"]
        if not isinstance(key, str) or not key.isascii() or any(ord(c) < 33 for c in key):
            fields["search.api_key"] = "Expected an ASCII credential without whitespace"
        integers = (("runtime", "max_model_calls"), ("episode", "switch_buffer_turns"),
                    ("context", "refresh_update_count"), ("expansion", "batch_size"))
        for group, field in integers:
            value = values[group][field]
            if type(value) is not int or value <= 0:
                fields[f"{group}.{field}"] = "Expected a positive integer"
        for group, field in (("runtime", "poll_interval_seconds"), ("expansion", "interval_seconds")):
            value = values[group][field]
            if not _finite(value) or value <= 0:
                fields[f"{group}.{field}"] = "Expected a positive finite number"
        llm = values["llm"]
        if llm["api"] != "chat_completions":
            fields["llm.api"] = "This verified runtime supports Chat Completions"
        for field in ("base_url", "model", "api_key"):
            if not isinstance(llm[field], str) or any(ord(c) < 32 for c in llm[field]):
                fields[f"llm.{field}"] = "Expected a string without control characters"
        if isinstance(llm["api_key"], str) and not llm["api_key"].isascii():
            fields["llm.api_key"] = "HTTP credentials must be ASCII"
        if isinstance(llm["base_url"], str) and llm["base_url"]:
            try:
                url = urlsplit(llm["base_url"])
                if not llm["base_url"].isascii() or any(c.isspace() for c in llm["base_url"]) or url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError("Invalid endpoint")
                url.port
            except ValueError:
                fields["llm.base_url"] = "Expected an HTTP(S) base URL without credentials, query or fragment"
        parameters = llm["parameters"]
        if not isinstance(parameters, dict):
            fields["llm.parameters"] = "Expected an object"
        else:
            for name, value in parameters.items():
                valid = False
                if name == "max_tokens":
                    valid = type(value) is int and value > 0
                elif name in ("temperature", "top_p"):
                    valid = _finite(value) and (
                        0 <= value <= 2 if name == "temperature" else 0 < value <= 1)
                elif name == "thinking":
                    valid = isinstance(llm["model"], str) and llm["model"].startswith("deepseek-") and value == {"type": "disabled"}
                if not valid:
                    fields[f"llm.parameters.{name}"] = "Unsupported parameter or value for this protocol/model"
        paths = values["workspace"]["paths"]
        if not isinstance(paths, list):
            fields["workspace.paths"] = "Expected a list of directory paths"
            return
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
