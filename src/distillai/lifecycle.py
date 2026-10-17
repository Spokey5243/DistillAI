"""Program lifecycle signals, independent of the still-unverified Desktop adapter."""
from datetime import datetime, timedelta
from typing import Annotated, Literal, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config

from .sources import SessionKey, Version, now, queue_path, scan_queue, utc
from .storage import atomic_json


EventKind = Literal["request_started", "response_stopped", "interrupted", "session_ended"]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class LifecycleRecord(TypedDict):
    session_key: SessionKey
    kind: EventKind
    observed_at: str
    sequence: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=0)]
    deadline: str | None
    code: Literal["invalid_source_prefix", "observation_clock_regressed", "source_boundary_regressed",
                  "unconfirmed_response_start", "interruption_timing_unverified"] | None
    previous_version: Version | None


EVENT_KIND = TypeAdapter(EventKind)
LIFECYCLE_RECORD = TypeAdapter(LifecycleRecord)


def _path(runtime, key):
    queue_path(runtime.store.home, key)
    return runtime.store.home / "events" / "lifecycle" / (key + ".json")


def read(runtime, key):
    path = _path(runtime, key)
    if not path.exists():
        return None
    record = LIFECYCLE_RECORD.validate_json(path.read_bytes(), strict=True)
    if record["session_key"] != key:
        raise ValueError("Lifecycle record belongs to another session")
    _time(record["observed_at"])
    if record["deadline"] is not None:
        _time(record["deadline"])
    return record


def _time(value):
    normalized = utc(value)
    if normalized is None:
        raise ValueError("Lifecycle observation needs an aware UTC timestamp")
    return normalized, datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def observe(runtime, key, kind, *, observed_at=None):
    EVENT_KIND.validate_python(kind)
    at, moment = _time(now() if observed_at is None else observed_at)
    with runtime.store.locked():
        path = _path(runtime, key)
        previous = read(runtime, key)
        rows, invalid = scan_queue(runtime.store.home, key)
        code, deadline = None, None
        if invalid is not None:
            code = "invalid_source_prefix"
        elif previous and moment < _time(previous["observed_at"])[1]:
            code = "observation_clock_regressed"
        elif previous and len(rows) < previous["line_end"]:
            code = "source_boundary_regressed"
        elif kind == "response_stopped":
            if previous and previous["kind"] == "request_started" and previous["code"] is None:
                deadline = (moment + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            else:
                code = "unconfirmed_response_start"
        elif kind == "interrupted":
            code = "interruption_timing_unverified"
        elif kind == "session_ended":
            deadline = at
        record = {"session_key": key, "kind": kind, "observed_at": at,
                  "sequence": previous["sequence"] + 1 if previous else 1,
                  "line_end": len(rows), "deadline": deadline, "code": code,
                  "previous_version": runtime.store.put_version(path.read_bytes()) if previous else None}
        path.parent.mkdir(exist_ok=True)
        atomic_json(path, record)
        version = runtime.store.put_version(path.read_bytes())
    runtime.wake()
    return {**record, "version": version}


def closing_signal(runtime, key, *, at=None):
    _, moment = _time(now() if at is None else at)
    with runtime.store.locked():
        record = read(runtime, key)
        if not record or record["code"] or record["deadline"] is None or moment < _time(record["deadline"])[1]:
            return None
        rows, invalid = scan_queue(runtime.store.home, key)
        path = queue_path(runtime.store.home, key)
        if invalid is not None or len(rows) != record["line_end"] or path.exists() and not path.read_bytes().endswith(b"\n"):
            return None  # Late or incomplete material needs a verified adapter decision, never arrival-time splitting.
        return {"session_key": key, "event_version": runtime.store.put_version(_path(runtime, key).read_bytes()),
                "line_end": record["line_end"], "kind": record["kind"], "observed_at": record["observed_at"]}


def check_closing(runtime, task):
    from .runtime import CancelledError
    expected = task["inputs"]["closing"]
    signal = closing_signal(runtime, expected["session_key"])
    if signal != expected:
        raise CancelledError("Closing signal changed or later material needs classification")


def tick(runtime):
    from .episode import register_close
    for path in sorted((runtime.store.home / "events" / "lifecycle").glob("*.json")):
        try:
            register_close(runtime, path.stem)
        except (OSError, ValueError) as error:
            runtime.store.event({"event": "lifecycle_pending", "session_key": path.stem, "code": type(error).__name__})
