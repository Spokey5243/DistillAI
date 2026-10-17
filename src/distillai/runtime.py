"""Durable task scheduling, generation accounting and publication lifecycle."""
from copy import deepcopy
from contextlib import contextmanager, ExitStack
import json
import re
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Annotated, Any, Literal, NotRequired, TypedDict, get_args

from pydantic import ConfigDict, Field, TypeAdapter, with_config

from .storage import ConflictError, _identifier, _hash, _relative
from .windows import canonical_directory, FileHandle, pinned_path
from .sources import Identifier


TaskKind = Literal["episode", "knowledge", "cognition", "expansion", "context", "query", "screening", "correction"]
KINDS = set(get_args(TaskKind))
TERMINAL = {"succeeded", "failed", "cancelled", "recovery_conflict"}


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class PublicationScope(TypedDict):
    root: str
    paths: NotRequired[Annotated[list[str], Field(min_length=1)] | None]


@with_config(ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True))
class RegisterArgs(TypedDict):
    kind: TaskKind
    inputs: dict[str, Any]
    trigger: str
    scope: NotRequired[PublicationScope | None]
    dependencies: NotRequired[list[Identifier]]


PUBLICATION_SCOPE = TypeAdapter(PublicationScope)


class BudgetError(RuntimeError):
    pass


class CancelledError(RuntimeError):
    pass


class Runtime:
    def __init__(self, store, config, execute, validate, *, after_commit=None, prepare_result=None):
        self.store, self.config = store, config
        self.execute, self.validate = execute, validate
        self.after_commit = after_commit
        self.prepare_result = prepare_result
        self._active = {}
        self._jobs = {}
        self._accepting = True
        self._wake = threading.Event()
        self._source_errors = {}
        self.on_wake = None

    def wake(self):
        self._wake.set()
        if self.on_wake is not None:
            self.on_wake()

    def _save(self, task):
        self.store.save_task(task)

    def task(self, task_id):
        return self.store.read_task(task_id)

    def tasks(self):
        return self.store.state.tasks()

    @staticmethod
    def _scope(scope):
        if scope is None:
            return None
        PUBLICATION_SCOPE.validate_python(scope)
        if not Path(scope["root"]).is_absolute():
            raise ValueError("Publication root must be absolute")
        try:
            root = canonical_directory(scope["root"])
        except OSError as exc:
            raise ValueError("Publication root is unavailable or unsupported") from exc
        paths = scope.get("paths")
        if paths is not None:
            paths = sorted({_relative(path).as_posix() for path in paths})
        return {"root": str(root), "paths": paths}

    @staticmethod
    def _dedup(kind, inputs, trigger, scope):
        return _hash(json.dumps([kind, inputs, trigger, scope], sort_keys=True,
                               ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def register(self, kind, inputs, trigger, *, scope=None, dependencies=(), prompt=""):
        if kind not in KINDS or not isinstance(inputs, dict) or not isinstance(trigger, str):
            raise ValueError("Invalid task kind, fixed input or trigger")
        if kind in {"query", "screening"} and scope is not None:
            raise ValueError("Read-only tasks have no publication scope")
        scope = self._scope(scope)
        if kind != "screening":
            prompt = (Path(__file__).parent / "prompts" / "common.txt").read_text(encoding="utf-8") + "\n" + prompt
        dedup = self._dedup(kind, inputs, trigger, scope)
        with self.store.locked():
            if not self._accepting:
                raise RuntimeError("Runtime is stopping")
            tasks = self.tasks()
            for existing in tasks:
                if existing["dedup"] == dedup or dedup in existing.get("dedup_aliases", []):
                    return existing
            for dependency in dependencies:
                self.task(_identifier(dependency))
            task = {"id": uuid.uuid4().hex, "kind": kind, "inputs": deepcopy(inputs),
                    "input_version": self.store.put_version(json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode("utf-8")),
                    "trigger": trigger, "scope": scope, "dedup": dedup,
                    "dedup_aliases": [], "started": False,
                    "order": max((t["order"] for t in tasks), default=0) + 1,
                    "dependencies": list(dependencies), "status": "queued", "model_calls": 0,
                    "config": self.config.snapshot(), "authorized": True,
                    "prompt_version": self.store.put_version(prompt.encode("utf-8")),
                    "commit_id": None, "result_version": None, "post_registered": False,
                    "error": None, "cancel_reason": None}
            self._authorize_scope(task)
            self._save(task)
        self.wake()
        return task

    def register_increment(self, ref, *, scope=None, prompt="", trigger="material"):
        if not isinstance(ref, dict) or set(ref) != {"connector", "session_key", "line_start", "line_end"}:
            raise ValueError("Invalid source range")
        if ref["connector"] != "codex" or not isinstance(ref["session_key"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", ref["session_key"]):
            raise ValueError("Invalid source session")
        if any(type(ref[name]) is not int for name in ("line_start", "line_end")) or not 1 <= ref["line_start"] <= ref["line_end"]:
            raise ValueError("Invalid ordered source range")
        scope = self._scope(scope)
        incoming = {"source_refs": [deepcopy(ref)]}
        key = self._dedup("episode", incoming, trigger, scope)
        with self.store.locked():
            if not self._accepting:
                raise RuntimeError("Runtime is stopping")
            for task in sorted(self.tasks(), key=lambda value: value["order"]):
                if task["dedup"] == key or key in task.get("dedup_aliases", []):
                    return task
                if task["kind"] != "episode" or task["status"] != "queued" or task.get("started") or task["scope"] != scope or task["trigger"] != trigger:
                    continue
                refs = task["inputs"].get("source_refs", [])
                if set(task["inputs"]) != {"source_refs"} or len(refs) != 1:
                    continue
                old = refs[0]
                if (old["connector"], old["session_key"]) != (ref["connector"], ref["session_key"]) or not old["line_start"] <= ref["line_start"] <= old["line_end"] + 1:
                    continue
                self._authorize_scope(task)
                previous = task["input_version"]
                task["dedup_aliases"] = list(dict.fromkeys([*task.get("dedup_aliases", []), task["dedup"], key]))
                task["inputs"]["source_refs"][0]["line_end"] = max(old["line_end"], ref["line_end"])
                task["input_version"] = self.store.put_version(json.dumps(task["inputs"], ensure_ascii=False).encode("utf-8"))
                task["dedup"] = self._dedup("episode", task["inputs"], trigger, scope)
                self._save(task)
                self.store.event({"event": "queued_increment_merged", "task_id": task["id"],
                                  "before": previous, "after": task["input_version"]})
                self.wake()
                return task
            return self.register("episode", incoming, trigger, scope=scope, prompt=prompt)

    def discover_materials(self, register=None):
        from .sources import scan_queue
        with self.store.locked():
            for path in sorted((self.store.home / "codex" / "queue").glob("*.jsonl")):
                key = path.stem
                try:
                    rows, invalid = scan_queue(self.store.home, key)
                    if invalid is not None and self._source_errors.get(key) != invalid:
                        self.store.event({"event": "invalid_material_line", "session_key": key, "line": invalid})
                    if invalid is None:
                        self._source_errors.pop(key, None)
                    else:
                        self._source_errors[key] = invalid
                    registered = sorted((ref["line_start"], ref["line_end"])
                        for task in self.tasks() if task["kind"] == "episode" and task["trigger"] == "material"
                        for ref in task["inputs"].get("source_refs", [])
                        if ref.get("connector") == "codex" and ref.get("session_key") == key)
                    end = 0
                    for start, stop in registered:
                        if start > end + 1:
                            break
                        end = max(end, stop)
                    if end < len(rows):
                        (register or self.register_increment)({"connector": "codex", "session_key": key,
                                                              "line_start": end + 1, "line_end": len(rows)})
                except (OSError, ValueError) as error:
                    code = type(error).__name__
                    if self._source_errors.get(key) != code:
                        self.store.event({"event": "material_scan_failed", "session_key": key, "code": code})
                        self._source_errors[key] = code

    def _authorize_scope(self, task):
        if not task["authorized"]:
            raise CancelledError("Task authorization was revoked")
        scope = task.get("scope")
        if scope is None:
            return
        root = Path(scope["root"])
        if root == self.store.home:
            allowed = scope.get("paths")
            business = {"episodes", "buffers", "knowledge", "relations", "hypotheses", "expansions", "contexts", "cognition"}
            if not isinstance(allowed, list) or not allowed or any(
                    not isinstance(name, str) or name.split("/")[0] not in business for name in allowed):
                raise CancelledError("Data-root scope is not a selected business scope")
            return
        paths = self.config.private()["values"]["workspace"]["paths"]
        if not any(root == Path(path) or Path(path) in root.parents for path in paths):
            raise CancelledError("Workspace is no longer authorized")

    def _check_input(self, task):
        if task["kind"] == "episode" and task["trigger"] == "closing":
            from .lifecycle import check_closing
            check_closing(self, task)
        if task["kind"] not in {"knowledge", "cognition", "context", "expansion", "correction"}:
            return
        if task["kind"] == "knowledge" and task["inputs"].get("user_edit"):
            edit = task["inputs"]["user_edit"]
            directory = "knowledge" if edit["record_kind"] == "knowledge" else "relations"
            path = self.store.home / directory / (_identifier(edit["record_id"]) + ".json")
            if not path.exists() or _hash(path.read_bytes()) != edit["expected_version"]:
                raise CancelledError("User edit input version was superseded")
        if task["kind"] == "cognition" and task["inputs"].get("user_correction"):
            edit = task["inputs"]["user_correction"]
            directory = "knowledge" if edit["record_kind"] == "knowledge" else "relations"
            path = self.store.home / directory / (_identifier(edit["record_id"]) + ".json")
            if not path.exists() or _hash(path.read_bytes()) != edit["expected_version"]:
                raise CancelledError("Cognition correction input version was superseded")
        for ref in task["inputs"].get("episode_refs", []):
            path = self.store.home / "episodes" / (_identifier(ref["id"]) + ".json")
            if not path.exists() or _hash(path.read_bytes()) != ref["version"]:
                raise CancelledError("Fixed episode input was superseded")
        if task["kind"] == "expansion":
            for ref in task["inputs"].get("knowledge_refs", []):
                path = self.store.home / "knowledge" / (_identifier(ref["id"]) + ".json")
                if not path.exists() or _hash(path.read_bytes()) != ref["version"]:
                    raise CancelledError("Fixed exploration input was superseded")

    @contextmanager
    def _input_guard(self, task):
        with ExitStack() as held:
            if task["kind"] == "episode" and task["trigger"] == "closing":
                from .sources import queue_path
                path = queue_path(self.store.home, task["inputs"]["closing"]["session_key"])
                parent = held.enter_context(pinned_path(path))
                held.enter_context(FileHandle(path, parent=parent))
            if task["kind"] in {"knowledge", "cognition", "context"}:
                for ref in task["inputs"].get("episode_refs", []):
                    path = self.store.home / "episodes" / (_identifier(ref["id"]) + ".json")
                    parent = held.enter_context(pinned_path(path))
                    handle = held.enter_context(FileHandle(path, parent=parent))
                    if _hash(handle.read()) != ref["version"]:
                        raise CancelledError("Fixed episode input was superseded")
            if task["kind"] == "expansion":
                for ref in task["inputs"].get("knowledge_refs", []):
                    path = self.store.home / "knowledge" / (_identifier(ref["id"]) + ".json")
                    parent = held.enter_context(pinned_path(path))
                    handle = held.enter_context(FileHandle(path, parent=parent))
                    if _hash(handle.read()) != ref["version"]:
                        raise CancelledError("Fixed exploration input was superseded")
            yield

    def _live(self, task_id):
        if self.store.state.failed:
            raise CancelledError("Control database recovery is required")
        task = self.task(task_id)
        if task["status"] not in {"running", "validating"} or task["cancel_reason"]:
            raise CancelledError("Task is no longer active")
        self._authorize_scope(task)
        self._check_input(task)
        return task

    def reserve_generation(self, task_id, *, attempt_id=None, request_version=None):
        with self.store.locked():
            task = self._live(task_id)
            if task["status"] != "running":
                raise CancelledError("Model execution has finished")
            limit = task["config"]["values"]["runtime"]["max_model_calls"]
            if task["model_calls"] >= limit:
                task["budget_exhausted"] = True
                self._save(task)
                raise BudgetError("Task generation budget exhausted")
            attempt_id = _identifier(attempt_id) if attempt_id is not None else uuid.uuid4().hex
            attempts = task.setdefault("generation_attempts", {})
            if attempt_id in attempts:
                raise ValueError("Generation attempt was already reserved")
            attempts[attempt_id] = {"state": "counted", "request_version": request_version}
            task["model_calls"] += 1
            self._save(task)
            return task["model_calls"]

    def release_unissued_generation(self, task_id, attempt_id):
        """Only the control transport may report a failure known to precede any HTTP request."""
        with self.store.locked():
            task = self.task(task_id)
            attempts = task.get("generation_attempts", {})
            attempt = attempts.get(_identifier(attempt_id))
            if attempt is not None and attempt["state"] == "counted":
                attempt["state"] = "not_sent"
                task["model_calls"] -= 1
                self._save(task)



    def attach_job(self, task_id, job):
        with self.store.locked():
            self._live(task_id)
            if task_id in self._jobs:
                raise RuntimeError("Task already has an execution tree")
            self._jobs[task_id] = job

    def _stop_tree(self, task_id):
        with self.store.locked():
            job = self._jobs.get(task_id)
        if job is not None:
            job.close()
            with self.store.locked():
                self._jobs.pop(task_id, None)

    def dispatch(self):
        started = []
        with self.store.locked():
            if not self._accepting or self.store.state.failed:
                return
            tasks = self.tasks()
            conflicts = [task["scope"] for task in tasks if task["status"] == "recovery_conflict" and task["scope"]]
            candidates = sorted((task for task in tasks if task["status"] == "queued"),
                                key=lambda task: (0 if task["kind"] == "screening" else 1 if task["kind"] == "query" else 2,
                                                  task["order"]))
            for task in candidates:
                if task["scope"] and any(self._overlap(task["scope"], scope) for scope in conflicts):
                    continue
                slot = "screening" if task["kind"] == "screening" else "ordinary"
                if any(active[0] == slot for active in self._active.values()):
                    continue
                if any(self.task(dependency)["status"] != "succeeded" for dependency in task["dependencies"]):
                    continue
                try:
                    self._authorize_scope(task)
                    self._check_input(task)
                    self.validate(task, None)
                except CancelledError:
                    task["status"] = "cancelled"
                    task["cancel_reason"] = "input_or_permission_changed"
                    self._save(task)
                    continue
                except Exception as exc:
                    task["status"] = "failed"
                    task["error"] = {"code": type(exc).__name__}
                    self._save(task)
                    continue
                task["status"] = "running"
                task["started"] = True
                self._save(task)
                thread = threading.Thread(target=self._run, args=(task["id"],), daemon=True)
                self._active[task["id"]] = (slot, thread)
                started.append(thread)
        for thread in started:
            thread.start()

    @staticmethod
    def _overlap(first, second):
        def targets(scope):
            root = Path(scope["root"])
            return [root] if scope.get("paths") is None else [root / _relative(path) for path in scope["paths"]]
        return any(a == b or a in b.parents or b in a.parents for a in targets(first) for b in targets(second))

    def _run(self, task_id):
        release = False
        try:
            with self.store.locked():
                task = self._live(task_id)
                if task.get("scope") and "workspace" not in task:
                    scope = task["scope"]
                    task = self.store.create_workspace(scope["root"], allowed_paths=scope["paths"], task_id=task_id)
            result = self.execute(deepcopy(task), self)
            self._stop_tree(task_id)
            release = True
            with self.store.locked():
                task = self._live(task_id)
                self.validate(task, result)
                if self.prepare_result is not None:
                    result = self.prepare_result(deepcopy(task), result)
                    task = self._live(task_id)
                    self.validate(task, result)
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
                task["result_version"] = self.store.put_version(encoded)
                task["status"] = "validating"
                self._save(task)
                if task["scope"]:
                    commit = self.store.prepare(task_id)
                    task["commit_id"] = commit["id"]
                    self._save(task)
                    with self._input_guard(task):
                        self.store.publish(commit["id"], lambda: self._validate_publication(task_id, result))
                self._complete(task)
        except Exception as exc:
            try:
                self._stop_tree(task_id)
                release = True
                with self.store.locked():
                    task = self.task(task_id)
                    committed = task["commit_id"] and self.store.read_commit(task["commit_id"])["status"] == "committed"
                    if committed or task["status"] == "validating" and task["result_version"] and not task["scope"]:
                        task["error"] = {"code": "post_registration_pending"}
                    else:
                        state = self.store.recover(task["commit_id"])["status"] if task["commit_id"] else "rolled_back"
                        task["status"] = "recovery_conflict" if state == "recovery_conflict" else (
                            "cancelled" if isinstance(exc, CancelledError) or task["cancel_reason"] else "failed")
                        task["error"] = {"code": type(exc).__name__}
                        if getattr(exc, "detail", None) is not None:
                            task["error"]["detail"] = exc.detail
                        if isinstance(exc, CancelledError) and not task["cancel_reason"]:
                            task["cancel_reason"] = str(exc)
                    self._save(task)
            except Exception as stop_error:
                if isinstance(exc, sqlite3.Error) or isinstance(stop_error, sqlite3.Error):
                    self.store.state.failed = True
                    self._accepting = False
                else:
                    with self.store.locked():
                        task = self.task(task_id)
                        task["status"] = "recovering"
                        task["error"] = {"code": type(stop_error).__name__}
                        self._save(task)
        finally:
            if release:
                with self.store.locked():
                    try:
                        task = self.task(task_id)
                        if not self.store.state.failed:
                            self._save(task)
                    except sqlite3.Error:
                        self.store.state.failed = True
                        self._accepting = False
                    finally:
                        self._active.pop(task_id, None)
            self.wake()

    def _validate_publication(self, task_id, result):
        task = self._live(task_id)
        self.validate(task, result)

    def _complete(self, task):
        if not task["post_registered"]:
            if self.after_commit is not None:
                self.after_commit(deepcopy(task))
            task["post_registered"] = True
        task["status"] = "succeeded"
        task["error"] = None
        self._save(task)

    def _complete_pending(self, task):
        try:
            self._complete(task)
        except Exception as error:
            task["status"] = "validating"
            task["error"] = {"code": "post_registration_pending", "cause": type(error).__name__}
            self._save(task)

    def finish_post_commits(self):
        with self.store.locked():
            for task in self.tasks():
                if task["status"] != "validating" or task["id"] in self._active:
                    continue
                if task["commit_id"] and self.store.read_commit(task["commit_id"])["status"] == "committed" or not task["scope"] and task["result_version"]:
                    self._complete_pending(task)

    def recover_tasks(self):
        with self.store.locked():
            for task in self.tasks():
                if task["status"] not in {"running", "validating", "recovering"}:
                    continue
                if task["id"] in self._active:
                    raise RuntimeError("Cannot recover an active execution tree")
                if task["commit_id"]:
                    commit = self.store.recover(task["commit_id"])
                    if commit["status"] == "committed":
                        self._complete_pending(task)
                        continue
                    task["status"] = "recovery_conflict" if commit["status"] == "recovery_conflict" else "failed"
                elif task["status"] == "validating" and task["result_version"]:
                    self._complete_pending(task)
                    continue
                else:
                    task["status"] = "cancelled" if task["cancel_reason"] else "failed"
                task["error"] = {"code": "interrupted"}
                self._save(task)

    def retry(self, task_id):
        with self.store.locked():
            task = self.task(task_id)
            if task["status"] != "failed" or task_id in self._active:
                raise ConflictError("Only a stopped failed task may retry; completed tasks require a new trigger")
            self._authorize_scope(task)
            self._check_input(task)
            task["status"] = "queued"
            task["error"] = None
            self._save(task)
        self.wake()

    def cancel(self, task_id, reason):
        with self.store.locked():
            task = self.task(task_id)
            if task["status"] in TERMINAL:
                return task
            if task["commit_id"] and self.store.read_commit(task["commit_id"])["status"] == "committed":
                return task  # Finish committed post-registration rather than undoing a saved business result.
            task["cancel_reason"] = str(reason)
            task["authorized"] = False
            task["status"] = "cancelled" if task["status"] == "queued" else "recovering"
            self._save(task)
        self._stop_tree(task_id)
        with self.store.locked():
            active = self._active.get(task_id)
            if active is not None and not active[1].is_alive():
                task = self.task(task_id)
                state = self.store.recover(task["commit_id"])["status"] if task["commit_id"] else "rolled_back"
                task["status"] = "recovery_conflict" if state == "recovery_conflict" else "cancelled"
                self._save(task)
                self._active.pop(task_id, None)
        self.wake()
        return self.task(task_id)

    def update_config(self, expected_version, patch):
        with self.store.locked():
            updated = self.config.update(expected_version, patch)
            revoke = []
            for task in self.tasks():
                if task["status"] in TERMINAL:
                    continue
                try:
                    self._authorize_scope(task)
                except CancelledError:
                    task["authorized"] = False
                    self._save(task)
                    revoke.append(task["id"])
        for task_id in revoke:
            self.cancel(task_id, "workspace_permission_revoked")
        self.wake()
        return updated

    def wait(self, task_id, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            with self.store.locked():
                task = self.task(task_id)
                if task_id not in self._active:
                    return task
            if time.monotonic() >= deadline:
                raise TimeoutError("Task is still running")
            self._wake.wait(.02)
            self._wake.clear()

    def close(self):
        with self.store.locked():
            self._accepting = False
            active = list(self._active)
        for task_id in active:
            if self.store.state.failed:
                self._stop_tree(task_id)
            else:
                self.cancel(task_id, "runtime_stopping")
        for task_id in active:
            if self.store.state.failed:
                running = self._active.get(task_id)
                if running is not None:
                    running[1].join(15)
                    if running[1].is_alive():
                        raise TimeoutError("Control cleanup has not stopped")
            else:
                self.wait(task_id)
