"""SQLite authority for task, generation, publication and configuration control state."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import uuid
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, TypeAdapter, with_config

from .config import ConfigValues, PositiveInt
from .sources import Identifier, NonblankText, SourceRef, Version
from .storage import _relative
from .cognition import CognitionResult
from .context import AuditedRecord, ContextResult, SelectionResult
from .episode import EpisodeResult
from .expansion import ExpansionResult, WebCall
from .knowledge import MaintenanceResult


TaskKind = Literal["episode", "knowledge", "cognition", "expansion", "context", "query", "screening", "correction"]
NonnegativeInt = Annotated[int, Field(ge=0)]
FileIdentity = Annotated[list[NonnegativeInt], Field(min_length=3, max_length=3)]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class PublicationScope(TypedDict):
    root: str
    paths: NotRequired[Annotated[list[str], Field(min_length=1)] | None]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class FileInfo(TypedDict):
    identity: FileIdentity
    attributes: NonnegativeInt
    links: NonnegativeInt
    created: NonnegativeInt
    modified: NonnegativeInt
    size: NonnegativeInt


class FileVersion(FileInfo):
    version: Version


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class WorkspaceRecord(TypedDict):
    id: Identifier
    source: NonblankText
    workspace: NonblankText
    allowed_paths: list[str] | None
    baseline: dict[str, FileVersion]
    directories: dict[str, FileInfo]
    workspace_attributes: dict[str, NonnegativeInt]
    workspace_directory_attributes: dict[str, NonnegativeInt]
    commit_id: NotRequired[Identifier | None]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class ConfigSnapshot(TypedDict):
    version: PositiveInt
    values: ConfigValues
    api_key_configured: bool
    search_key_configured: NotRequired[bool]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class GenerationAttempt(TypedDict):
    state: Literal["counted", "not_sent"]
    request_version: Version | None


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class TaskError(TypedDict):
    code: NonblankText
    cause: NotRequired[NonblankText]
    detail: NotRequired[dict[str, Any]]


class WebCallRecord(WebCall):
    result_version: Version
    access_mode: Literal["keyed", "keyless"]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class PreparedEpisode(TypedDict):
    result: EpisodeResult
    processed_line: NotRequired[NonnegativeInt]
    material_updates: NotRequired[NonnegativeInt]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class TaskRecord(TypedDict):
    id: Identifier
    kind: TaskKind
    inputs: dict[str, Any]
    input_version: Version
    trigger: str
    scope: PublicationScope | None
    dedup: Version
    dedup_aliases: list[Version]
    started: bool
    order: PositiveInt
    dependencies: list[Identifier]
    status: Literal["queued", "running", "validating", "recovering", "recovery_conflict", "succeeded", "failed", "cancelled"]
    model_calls: NonnegativeInt
    config: ConfigSnapshot
    authorized: bool
    prompt_version: Version
    commit_id: Identifier | None
    result_version: Version | None
    post_registered: bool
    error: TaskError | None
    cancel_reason: str | None
    source: NotRequired[NonblankText]
    workspace: NotRequired[NonblankText]
    allowed_paths: NotRequired[list[str] | None]
    baseline: NotRequired[dict[str, FileVersion]]
    directories: NotRequired[dict[str, FileInfo]]
    workspace_attributes: NotRequired[dict[str, NonnegativeInt]]
    workspace_directory_attributes: NotRequired[dict[str, NonnegativeInt]]
    generation_attempts: NotRequired[dict[Identifier, GenerationAttempt]]
    budget_exhausted: NotRequired[bool]
    execution_input_version: NotRequired[Version]
    model_output_version: NotRequired[Version]
    boundary_evaluations: NotRequired[list[Version]]
    episode_source_reads: NotRequired[dict[str, Version]]
    episode_revision_version: NotRequired[Version]
    allocated_record_ids: NotRequired[dict[Identifier, Literal["knowledge", "relation", "observation", "hypothesis"]]]
    allocated_observation_sources: NotRequired[dict[Version, Identifier]]
    allocated_candidate_ids: NotRequired[list[Identifier]]
    external_source_refs: NotRequired[list[SourceRef]]
    web_calls: NotRequired[list[WebCallRecord]]
    read_record_refs: NotRequired[list[AuditedRecord]]
    read_source_refs: NotRequired[list[SourceRef]]
    query_read_performed: NotRequired[bool]
    query_prepared: NotRequired[bool]
    reanalysis_prepared_version: NotRequired[Version]
    reanalysis_resolved_ids: NotRequired[list[Identifier]]
    episode_prepared: NotRequired[PreparedEpisode]
    knowledge_prepared: NotRequired[MaintenanceResult]
    cognition_prepared: NotRequired[CognitionResult]
    expansion_prepared: NotRequired[ExpansionResult]
    context_prepared: NotRequired[ContextResult]
    selection_prepared: NotRequired[SelectionResult]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class DirectoryChange(TypedDict):
    path: NonblankText
    kind: Literal["directory"]
    state: Literal["pending", "applying", "applied", "restored"]
    identity: FileIdentity | None


class FileChange(DirectoryChange):
    kind: Literal["file"]
    before: Version | None
    after: Version | None
    baseline: FileVersion | None
    backup: Annotated[str, Field(pattern=r"^\.distillai-[0-9a-f]{32}-[0-9]+\.deleted$")] | None


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class RecoveryConflict(TypedDict):
    path: NonblankText
    error: NonblankText


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class CommitRecord(TypedDict):
    id: Identifier
    task_id: Identifier
    source: NonblankText
    status: Literal["prepared", "committed", "rolled_back", "recovery_conflict"]
    items: list[DirectoryChange | FileChange]
    conflicts: NotRequired[list[RecoveryConflict]]


TASK_RECORD = TypeAdapter(TaskRecord)
WORKSPACE_RECORD = TypeAdapter(WorkspaceRecord)
COMMIT_RECORD = TypeAdapter(CommitRecord)
JSON_OBJECT = TypeAdapter(dict[str, Any], config=ConfigDict(strict=True, hide_input_in_errors=True))


def _task_record(record):
    (TASK_RECORD if "kind" in record else WORKSPACE_RECORD).validate_python(record)
    return record


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class State:
    def __init__(self, home):
        self.path = Path(home) / "state.sqlite3"
        self.failed = False
        if not self.path.exists():
            legacy = (Path(home) / "config.json").exists() or any(
                next((Path(home) / directory).glob("*.json"), None) is not None
                for directory in ("tasks", "commits"))
            if legacy:
                raise ValueError("Legacy control state requires explicit offline migration")
            initialized = any(path.stem.isdecimal() for path in (Path(home) / "config").glob("*.json")) or any(
                next((Path(home) / directory).glob("*"), None) is not None for directory in ("versions", "workspaces"))
            if initialized:
                raise ValueError("Control database is missing from an initialized data root")
            temporary = self.path.with_name(".state-init-" + uuid.uuid4().hex)
            connection = sqlite3.connect(temporary, isolation_level=None)
            try:
                connection.executescript("""
                    PRAGMA synchronous=FULL;
                    BEGIN IMMEDIATE;
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY, kind TEXT, status TEXT, task_order INTEGER,
                        model_calls INTEGER NOT NULL CHECK(model_calls >= 0), record TEXT NOT NULL);
                    CREATE TABLE task_keys (
                        key TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), position INTEGER NOT NULL);
                    CREATE TABLE dependencies (
                        task_id TEXT NOT NULL REFERENCES tasks(id),
                        dependency_id TEXT NOT NULL REFERENCES tasks(id) DEFERRABLE INITIALLY DEFERRED,
                        position INTEGER NOT NULL, PRIMARY KEY(task_id, dependency_id));
                    CREATE TABLE attempts (
                        task_id TEXT NOT NULL REFERENCES tasks(id), attempt_id TEXT NOT NULL,
                        record TEXT NOT NULL, PRIMARY KEY(task_id, attempt_id));
                    CREATE TABLE commits (
                        id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                        status TEXT NOT NULL, record TEXT NOT NULL);
                    CREATE TABLE config (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL);
                    CREATE TABLE migration (singleton INTEGER PRIMARY KEY CHECK(singleton=1), manifest TEXT NOT NULL);
                    PRAGMA user_version=1;
                    COMMIT;
                """)
                connection.close()
                os.rename(temporary, self.path)
            finally:
                connection.close()
                temporary.unlink(missing_ok=True)
        with self.transaction(write=False) as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported control database schema version")

    @contextmanager
    def transaction(self, *, write=True):
        connection = None
        try:
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                         timeout=5, isolation_level=None)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except BaseException as error:
            if isinstance(error, sqlite3.Error):
                self.failed = True
            if connection is not None and connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    self.failed = True
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    self.failed = True
                    raise

    def save_task(self, task, *, connection=None):
        if connection is None:
            with self.transaction() as connection:
                return self.save_task(task, connection=connection)
        _task_record(task)
        separate = {"id", "kind", "status", "order", "model_calls", "dedup", "dedup_aliases", "dependencies", "generation_attempts"}
        record = {key: value for key, value in task.items() if key not in separate}
        connection.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            kind=excluded.kind,status=excluded.status,task_order=excluded.task_order,
            model_calls=excluded.model_calls,record=excluded.record""",
            (task["id"], task.get("kind"), task.get("status"), task.get("order"), task.get("model_calls", 0), _json(record)))
        for table in ("task_keys", "dependencies", "attempts"):
            connection.execute(f"DELETE FROM {table} WHERE task_id=?", (task["id"],))
        if task.get("dedup"):
            keys = list(dict.fromkeys([task["dedup"], *task.get("dedup_aliases", [])]))
            connection.executemany("INSERT INTO task_keys VALUES(?,?,?)", ((key, task["id"], index) for index, key in enumerate(keys)))
        connection.executemany("INSERT INTO dependencies VALUES(?,?,?)",
            ((task["id"], dependency, index) for index, dependency in enumerate(task.get("dependencies", []))))
        connection.executemany("INSERT INTO attempts VALUES(?,?,?)",
            ((task["id"], attempt, _json(record)) for attempt, record in task.get("generation_attempts", {}).items()))

    @staticmethod
    def _task(connection, identifier):
        row = connection.execute("SELECT kind,status,task_order,model_calls,record FROM tasks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise FileNotFoundError("Task not found")
        record = {**JSON_OBJECT.validate_json(row[4]), "id": identifier}
        if row[0] is not None:
            keys = [key[0] for key in connection.execute("SELECT key FROM task_keys WHERE task_id=? ORDER BY position", (identifier,))]
            record.update(kind=row[0], status=row[1], order=row[2], model_calls=row[3],
                dedup=keys[0] if keys else None, dedup_aliases=keys[1:],
                dependencies=[item[0] for item in connection.execute("SELECT dependency_id FROM dependencies WHERE task_id=? ORDER BY position", (identifier,))])
            attempts = {key: JSON_OBJECT.validate_json(value) for key, value in connection.execute("SELECT attempt_id,record FROM attempts WHERE task_id=? ORDER BY rowid", (identifier,))}
            if attempts:
                record["generation_attempts"] = attempts
        return _task_record(record)

    def read_task(self, identifier):
        with self.transaction(write=False) as connection:
            return self._task(connection, identifier)

    def tasks(self):
        with self.transaction(write=False) as connection:
            return [self._task(connection, row[0]) for row in connection.execute("SELECT id FROM tasks WHERE kind IS NOT NULL ORDER BY id").fetchall()]

    def save_commit(self, record, *, connection=None):
        if connection is None:
            with self.transaction() as connection:
                return self.save_commit(record, connection=connection)
        COMMIT_RECORD.validate_python(record)
        for item in record["items"]:
            _relative(item["path"])
        connection.execute("""INSERT INTO commits VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            task_id=excluded.task_id,status=excluded.status,record=excluded.record""",
            (record["id"], record["task_id"], record["status"], _json({key: value for key, value in record.items() if key not in {"id", "task_id", "status"}})))

    def read_commit(self, identifier):
        with self.transaction(write=False) as connection:
            row = connection.execute("SELECT task_id,status,record FROM commits WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise FileNotFoundError("Commit not found")
            record = {**JSON_OBJECT.validate_json(row[2]), "id": identifier, "task_id": row[0], "status": row[1]}
            COMMIT_RECORD.validate_python(record)
            for item in record["items"]:
                _relative(item["path"])
            return record

    def current_config(self):
        with self.transaction(write=False) as connection:
            row = connection.execute("SELECT version FROM config WHERE singleton=1").fetchone()
            return row[0] if row else None

    def set_config(self, version, *, expected=None, connection=None):
        if connection is None:
            with self.transaction() as connection:
                return self.set_config(version, expected=expected, connection=connection)
        if expected is None:
            connection.execute("INSERT INTO config VALUES(1,?)", (version,))
        elif connection.execute("UPDATE config SET version=? WHERE singleton=1 AND version=?", (version, expected)).rowcount != 1:
            raise ValueError("Current configuration changed")
