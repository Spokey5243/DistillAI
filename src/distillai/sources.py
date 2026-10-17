"""Codex sources use inclusive physical queue lines, never caller-supplied paths."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, with_config
from urllib.parse import urlsplit

from .storage import _relative, _identifier, atomic_json, Store, ConflictError
from .windows import FileHandle, pinned_path


class SourceError(ValueError):
    pass


Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Version = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SessionKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
NonblankText = Annotated[str, Field(pattern=r"\S")]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class RecordRef(TypedDict):
    id: Identifier
    version: Version


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class DraftRecordRef(TypedDict):
    id: Identifier
    version: NotRequired[Version]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class QueueRef(TypedDict):
    connector: Literal["codex"]
    session_key: SessionKey
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=1)]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class VersionedRef(TypedDict):
    source_kind: Literal["external", "user_submission"]
    id: Identifier
    version: Version


SourceRef = QueueRef | VersionedRef
QUEUE_REF = TypeAdapter(QueueRef)
QUEUE_REFS = TypeAdapter(list[QueueRef])
VERSIONED_REF = TypeAdapter(VersionedRef)
SOURCE_REFS = TypeAdapter(list[SourceRef])
DRAFT_RECORD_REFS = TypeAdapter(list[DraftRecordRef])


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class QueueEntry(TypedDict):
    role: Literal["user", "assistant", "tool"]
    text: Annotated[str, Field(min_length=1)]
    at: NotRequired[str]


QUEUE_ENTRY = TypeAdapter(QueueEntry)


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def queue_path(home, key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise SourceError("Invalid session key")
    try:
        name = _relative(key + ".jsonl")
    except ValueError as error:
        raise SourceError("Invalid queue filename") from error
    except RuntimeError as error:
        raise SourceError("Invalid queue filename") from error
    return Path(home) / "codex" / "queue" / name


def entry(data):
    value = json.loads(data)
    try:
        QUEUE_ENTRY.validate_python(value)
    except ValidationError:
        raise SourceError("Invalid queue entry") from None
    if (not value["text"].strip()
            or "at" in value and (utc(value["at"]) is None or utc(value["at"]) != value["at"])):
        raise SourceError("Invalid queue entry")
    return value


def scan_queue(home, key):
    """Return the valid LF-complete prefix and the first invalid physical line."""
    path = queue_path(home, key)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return [], None
    rows = []
    for line in data.split(b"\n")[:-1]:
        try:
            rows.append(entry(line))
        except (ValueError, UnicodeError):
            return rows, len(rows) + 1
    return rows, None


def read_source(home, ref):
    if isinstance(ref, dict) and "source_kind" in ref:
        return _read_versioned(home, ref)
    try:
        QUEUE_REF.validate_python(ref)
    except ValidationError:
        raise SourceError("Invalid source reference") from None
    if ref["line_start"] > ref["line_end"]:
        raise SourceError("Invalid source reference")
    rows, _ = scan_queue(home, ref["session_key"])
    if ref["line_end"] > len(rows):
        raise SourceError("Source range is unavailable")
    selected = rows[ref["line_start"] - 1:ref["line_end"]]
    return {"ref": dict(ref), "rows": selected,
            "text": "\n".join(f'{item["role"]}: {item["text"]}' for item in selected)}


def contains(ref, allowed):
    """Check physical ranges against the union of fixed ranges without expanding line numbers."""
    if isinstance(ref, dict) and "source_kind" in ref:
        try:
            _versioned_ref(ref)
        except ValueError:
            return False
        return ref in allowed
    try:
        QUEUE_REF.validate_python(ref)
    except ValidationError:
        return False
    if ref["line_start"] > ref["line_end"]:
        return False
    covered = ref["line_start"]
    intervals = sorted((item["line_start"], item["line_end"]) for item in allowed
                       if item.get("connector") == "codex" and item.get("session_key") == ref["session_key"])
    for start, end in intervals:
        if start > covered:
            break
        covered = max(covered, end + 1)
        if covered > ref["line_end"]:
            return True
    return False


def _versioned_ref(ref):
    try:
        VERSIONED_REF.validate_python(ref)
    except ValidationError:
        raise SourceError("Invalid source identity or version") from None


def _read_versioned(home, ref):
    _versioned_ref(ref)
    folder = {"external": "external-sources", "user_submission": "user-submissions"}[ref["source_kind"]]
    path = Path(home) / folder / (ref["id"] + ".json")
    try:
        with pinned_path(path) as parent, FileHandle(path, parent=parent) as handle:
            registered = json.loads(handle.read())
        record = json.loads(Store(home).read_version(ref["version"]))
    except (OSError, ValueError):
        raise SourceError("Versioned source is unavailable") from None
    if any(not isinstance(value, dict) or value.get("id") != ref["id"] or value.get("source_kind") != ref["source_kind"] for value in (registered, record)):
        raise SourceError("Source version belongs to another identity or kind")
    if not isinstance(record.get("text"), str) or not record["text"].strip():
        raise SourceError("Source has no readable excerpt")
    if ref["source_kind"] == "external":
        if not isinstance(record.get("url"), str):
            raise SourceError("External source requires an actual URL")
        url = urlsplit(record.get("url", ""))
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or not isinstance(record.get("title"), str) or utc(record.get("read_at")) is None):
            raise SourceError("External source must retain URL, title and actual read time")
    elif (utc(record.get("submitted_at")) is None or not isinstance(record.get("reason"), str)
            or not record["reason"].strip() or not isinstance(record.get("payload"), dict)):
        raise SourceError("User submission must retain its actual input, time and reason")
    return {"ref": dict(ref), "record": record, "text": record["text"],
            "rows": [{"role": "external" if ref["source_kind"] == "external" else "user", "text": record["text"]}]}


def record_submission(store, payload, reason, *, identifier=None):
    if not isinstance(payload, dict) or not payload or not isinstance(reason, str) or not reason.strip():
        raise SourceError("A user submission requires actual input and a reason")
    identifier = _identifier(identifier) if identifier is not None else uuid.uuid4().hex
    with store.locked():
        folder = store.home / "user-submissions"
        folder.mkdir(exist_ok=True)
        path = folder / (identifier + ".json")
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous["payload"] != payload or previous["reason"] != reason:
                raise ConflictError("Submission identity already belongs to different input")
        else:
            text = json.dumps({"input": payload, "reason": reason}, ensure_ascii=False, allow_nan=False)
            atomic_json(path, {"id": identifier, "source_kind": "user_submission", "submitted_at": now(),
                               "reason": reason, "payload": payload, "text": text})
        return {"source_kind": "user_submission", "id": identifier, "version": store.put_version(path.read_bytes())}
