"""Immutable byte versions, independent task copies and recoverable publication."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import msvcrt
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import threading
import uuid

from .windows import canonical_directory, FileHandle, pinned_path


class ConflictError(RuntimeError):
    """The current source or publication cannot safely be overwritten."""


def _identifier(value, length=32):
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError("Invalid persistent identifier")
    return value


def _relative(value):
    parts = PurePosixPath(value).parts
    if not parts or PurePosixPath(value).is_absolute() or "\\" in value:
        raise ConflictError("Invalid relative publication path")
    for part in parts:
        if part in (".", "..") or part.endswith((".", " ")) or any(ord(c) < 32 or c in ':<>"|?*' for c in part):
            raise ConflictError("Invalid Windows publication path")
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            raise ConflictError("Device paths cannot be published")
    return Path(*parts)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _in_scope(relative, allowed, *, ancestor=False):
    return allowed is None or any(relative == name or relative.startswith(name + "/")
                                  or ancestor and name.startswith(relative + "/") for name in allowed)


def atomic_json(path, record):
    """Caller holds the data-root lock across read/validate/write."""
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=".save-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Store:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("DISTILLAI_HOME", Path.home() / ".distillAI")).resolve()
        for name in ("config", "tasks", "versions", "commits", "workspaces", "events"):
            (self.home / name).mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    @contextmanager
    def locked(self):
        with self._thread_lock:
            if getattr(self._local, "held", False):
                yield
                return
            with (self.home / ".lock").open("a+b") as stream:
                stream.seek(0, os.SEEK_END)
                if not stream.tell():
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                self._local.held = True
                try:
                    yield
                finally:
                    self._local.held = False
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def event(self, record):
        with self.locked(), (self.home / "events" / "program.jsonl").open("ab") as stream:
            stream.write((json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    def put_version(self, data):
        digest = _hash(data)
        path = self.home / "versions" / digest
        with self.locked():
            if path.exists():
                self.read_version(digest)
            else:
                descriptor, name = tempfile.mkstemp(prefix=".version-", dir=path.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.rename(name, path)
                finally:
                    Path(name).unlink(missing_ok=True)
        return digest

    def read_version(self, digest):
        data = (self.home / "versions" / _identifier(digest, 64)).read_bytes()
        if _hash(data) != digest:
            raise ConflictError("Immutable content version is damaged")
        return data

    def _record_path(self, kind, identifier):
        return self.home / kind / (_identifier(identifier) + ".json")

    def read_task(self, identifier):
        return json.loads(self._record_path("tasks", identifier).read_text(encoding="utf-8"))

    def read_commit(self, identifier):
        return json.loads(self._record_path("commits", identifier).read_text(encoding="utf-8"))

    def _save_commit(self, record):
        atomic_json(self._record_path("commits", record["id"]), record)

    def _scan(self, root, copy_to=None, allowed=None):
        files, directories = {}, {}
        with ExitStack() as stack:
            root_handle = stack.enter_context(pinned_path(root / ".scan"))
            directories[""] = root_handle.info()
            pending = [(root, root_handle)]
            while pending:
                directory, parent = pending.pop()
                for path in sorted(directory.iterdir()):
                    relative = path.relative_to(root).as_posix()
                    if not _in_scope(relative, allowed, ancestor=True):
                        continue
                    _relative(relative)
                    if path.is_dir():
                        handle = stack.enter_context(FileHandle(path, directory=True, parent=parent))
                        directories[relative] = handle.info()
                        pending.append((path, handle))
                        if copy_to is not None:
                            (copy_to / relative).mkdir()
                    else:
                        handle = stack.enter_context(FileHandle(path, parent=parent))
                        before = handle.info()
                        content = handle.read()
                        handle.check_streams()
                        after = handle.info()
                        if before != after:
                            raise ConflictError("Source changed during snapshot")
                        files[relative] = {**before, "version": self.put_version(content)}
                        if copy_to is not None:
                            with (copy_to / relative).open("xb") as output:
                                output.write(content)
                                output.flush()
                                os.fsync(output.fileno())
            # All discovered file and directory handles remain held until the copy is complete.
        return files, directories

    def create_workspace(self, source, *, allowed_paths=None, task_id=None):
        try:
            source = canonical_directory(source)
        except OSError as exc:
            raise ConflictError("Source directory cannot be identified safely") from exc
        private = [self.home / name for name in ("config", "tasks", "versions", "commits", "workspaces", "events")]
        if source in self.home.parents or any(p == source or p in source.parents for p in private):
            raise ConflictError("Task source overlaps private runtime state")
        if allowed_paths is not None:
            if not isinstance(allowed_paths, list) or not allowed_paths:
                raise ConflictError("A selected scope needs explicit relative paths")
            allowed_paths = [_relative(name).as_posix() for name in allowed_paths]
        if source == self.home:
            if allowed_paths is None or any(name.split("/")[0] in
                    {"config", "config.json", "tasks", "versions", "commits", "workspaces", "events", ".lock", "codex", "hermes"}
                    for name in allowed_paths):
                raise ConflictError("The data root is not a whole-root task authorization")
        task_id = _identifier(task_id) if task_id is not None else uuid.uuid4().hex
        workspace = self.home / "workspaces" / task_id
        with self.locked():
            workspace.mkdir()
            try:
                files, directories = self._scan(source, workspace, allowed_paths)
                work_files, work_directories = self._scan(workspace)
            except OSError as exc:
                raise ConflictError(str(exc)) from exc
            previous = self.read_task(task_id) if self._record_path("tasks", task_id).exists() else {}
            task = {**previous, "id": task_id, "source": str(source), "workspace": str(workspace),
                    "allowed_paths": allowed_paths,
                    "baseline": files, "directories": directories,
                    "workspace_attributes": {name: info["attributes"] for name, info in work_files.items()},
                    "workspace_directory_attributes": {name: info["attributes"] for name, info in work_directories.items()}}
            atomic_json(self._record_path("tasks", task_id), task)
        return task

    def prepare(self, task_id):
        with self.locked():
            task = self.read_task(task_id)
            try:
                files, directories = self._scan(Path(task["workspace"]))
            except OSError as exc:
                raise ConflictError(str(exc)) from exc
            if not set(task["directories"]).issubset(directories):
                raise ConflictError("Removing existing directory structure is not a file change")
            if any(not _in_scope(name, task["allowed_paths"]) for name in files) or any(
                    name and not _in_scope(name, task["allowed_paths"], ancestor=True) for name in directories):
                raise ConflictError("Workspace changes exceed the frozen business scope")
            for name, info in directories.items():
                expected = task["workspace_directory_attributes"].get(name, 0x10)
                if info["attributes"] != expected:
                    raise ConflictError("Workspace directory metadata changes cannot be published")
            for name, info in files.items():
                expected = task["workspace_attributes"].get(name, 0x20)
                if (info["attributes"] & ~0x80) != (expected & ~0x80):
                    raise ConflictError("Workspace metadata changes cannot be published")
            commit_id = uuid.uuid4().hex
            items = [{"path": name, "kind": "directory", "state": "pending", "identity": None}
                     for name in sorted(set(directories) - set(task["directories"]), key=lambda n: (n.count("/"), n))]
            for name in sorted(set(files) | set(task["baseline"])):
                before = task["baseline"].get(name)
                after = files.get(name)
                if before is not None and after is not None and before["version"] == after["version"]:
                    continue
                if name in task["directories"] or name in directories and before is not None:
                    raise ConflictError("File/directory type changes cannot be published")
                items.append({"path": name, "kind": "file", "state": "pending",
                              "before": before["version"] if before else None,
                              "after": after["version"] if after else None,
                              "baseline": before, "identity": None,
                              "backup": f".distillai-{commit_id}-{len(items)}.deleted" if before and not after else None})
            record = {"id": commit_id, "task_id": task_id, "source": task["source"],
                      "status": "prepared", "items": items}
            self._save_commit(record)
            return record

    def publish(self, commit_id, validate):
        """validate checks live business authorization and input revision under the commit lock."""
        with self.locked():
            record = self.read_commit(commit_id)
            if record["status"] != "prepared" or any(i["state"] != "pending" for i in record["items"]):
                raise ConflictError("Recover an interrupted commit before publishing again")
            validate()
            source = Path(record["source"])
            try:
                with ExitStack() as stack:
                    # Hold the original snapshot through validation and publication; never rewrite unchanged files.
                    task = self.read_task(record["task_id"])
                    root_handle = stack.enter_context(pinned_path(source / ".publish"))
                    directories = {"": root_handle}
                    for name, baseline in sorted(task["directories"].items()):
                        if name:
                            parent_name = str(PurePosixPath(name).parent)
                            parent = directories["" if parent_name == "." else parent_name]
                            handle = stack.enter_context(FileHandle(source / _relative(name), directory=True, parent=parent))
                            directories[name] = handle
                        else:
                            handle = root_handle
                        if handle.info()["identity"] != baseline["identity"]:
                            raise ConflictError("Source directory was replaced")
                    handles = {}
                    writes = {item["path"]: item for item in record["items"] if item["kind"] == "file"}
                    for name, baseline in task["baseline"].items():
                        item = writes.get(name)
                        handle = stack.enter_context(FileHandle(source / _relative(name), writable=item is not None,
                            delete=item is not None and item["after"] is None,
                            parent=directories[self._parent_name(name)]))
                        info = handle.info()
                        if any(info[key] != baseline[key] for key in ("identity", "attributes", "created", "modified")):
                            raise ConflictError("Source metadata or identity changed")
                        if _hash(handle.read()) != baseline["version"]:
                            raise ConflictError("Fixed source content changed")
                        handles[name] = handle
                    validate()
                    for index, item in enumerate(record["items"]):
                        target = source / _relative(item["path"])
                        parent = directories[self._parent_name(item["path"])]
                        if any(h.info()["attributes"] & 0x400 for h in directories.values()):
                            raise ConflictError("Directory became a reparse point")
                        item["state"] = "applying"
                        self._save_commit(record)
                        if item["kind"] == "directory":
                            handle = stack.enter_context(FileHandle(target, directory=True, create=True, parent=parent))
                            directories[item["path"]] = handle
                        elif item["before"] is None:
                            handle = stack.enter_context(FileHandle(target, writable=True, create=True, delete=True, parent=parent))
                        else:
                            handle = handles[item["path"]]
                        item["identity"] = handle.info()["identity"]
                        self._save_commit(record)
                        if item["kind"] == "file":
                            if item["after"] is None:
                                handle._rename_relative(target.with_name(item["backup"]), parent)
                            else:
                                handle.write(self.read_version(item["after"]))
                            handle.check_streams()
                            if handle.info()["links"] != 1:
                                raise ConflictError("File acquired another link during publication")
                        item["state"] = "applied"
                        self._save_commit(record)
                    if any(h.info()["attributes"] & 0x400 for h in directories.values()):
                        raise ConflictError("Directory became a reparse point")
                    record["status"] = "committed"
                    self._save_commit(record)
            except (OSError, ConflictError) as exc:
                recovered = self.recover(commit_id)
                raise ConflictError(f"Publication failed ({recovered['status']}): {exc}") from exc
            self._cleanup_backups(record)
            return record

    @staticmethod
    def _parent_name(name):
        parent = str(PurePosixPath(name).parent)
        return "" if parent == "." else parent

    def _cleanup_backups(self, record):
        for item in record["items"]:
            if item.get("backup"):
                target = Path(record["source"]) / _relative(item["path"])
                backup = target.with_name(item["backup"])
                try:
                    with pinned_path(backup) as parent, FileHandle(backup, delete=True, parent=parent) as handle:
                        if handle.info()["identity"] != item["identity"] or _hash(handle.read()) != item["before"]:
                            raise ConflictError("Deletion backup was changed")
                        handle.remove()
                except FileNotFoundError:
                    continue
                except (OSError, ConflictError) as exc:
                    self.event({"commit_id": record["id"], "event": "cleanup_conflict", "path": item["path"],
                                "error": type(exc).__name__})

    def recover(self, commit_id):
        with self.locked():
            record = self.read_commit(commit_id)
            if record["status"] == "committed":
                self._cleanup_backups(record)
                return record
            if record["status"] == "rolled_back":
                return record
            conflicts = []
            for item in reversed(record["items"]):
                if item["state"] in ("pending", "restored"):
                    continue
                target = Path(record["source"]) / _relative(item["path"])
                try:
                    with pinned_path(target) as parent:
                        task = self.read_task(record["task_id"])
                        parent_name = self._parent_name(item["path"])
                        if parent_name in task["directories"]:
                            expected = task["directories"][parent_name]["identity"]
                        else:
                            expected = next(i["identity"] for i in record["items"] if i["path"] == parent_name)
                        if parent.info()["identity"] != expected:
                            raise ConflictError("Recovery parent directory was replaced")
                        if item["kind"] == "directory":
                            self._restore_directory(item, target, parent)
                        else:
                            self._restore_file(item, target, parent)
                    item["state"] = "restored"
                    self._save_commit(record)
                except (OSError, ConflictError) as exc:
                    conflicts.append({"path": item["path"], "error": type(exc).__name__})
            record["status"] = "recovery_conflict" if conflicts else "rolled_back"
            record["conflicts"] = conflicts
            self._save_commit(record)
            return record

    def _restore_directory(self, item, target, parent):
        if not target.exists():
            return
        if item["identity"] is None:
            raise ConflictError("Directory creation outcome is unknown")
        with FileHandle(target, directory=True, delete=True, parent=parent) as handle:
            if handle.info()["identity"] != item["identity"]:
                raise ConflictError("Directory was replaced")
            handle.remove()  # Windows rejects nonempty directories, preserving user files.

    def _restore_file(self, item, target, parent):
        if item["after"] is None:
            backup = target.with_name(item["backup"])
            if not backup.exists():
                with FileHandle(target, parent=parent) as handle:
                    if handle.info()["identity"] != item["baseline"]["identity"] or _hash(handle.read()) != item["before"]:
                        raise ConflictError("Deleted file outcome is unknown")
                return
            with FileHandle(backup, delete=True, parent=parent) as handle:
                if handle.info()["identity"] != item["identity"] or _hash(handle.read()) != item["before"]:
                    raise ConflictError("Deletion backup was modified")
                handle._rename_relative(target, parent)
            return
        if not target.exists() and item["before"] is None:
            return
        with FileHandle(target, writable=True, delete=item["before"] is None, parent=parent) as handle:
            current = _hash(handle.read())
            if item["before"] is not None and current == item["before"] and handle.info()["identity"] == item["baseline"]["identity"]:
                return
            if current != item["after"] or handle.info()["identity"] != item["identity"]:
                raise ConflictError("Current file is not the version published by this commit")
            if item["before"] is None:
                handle.remove()
            else:
                handle.write(self.read_version(item["before"]))
                handle.restore_modified(item["baseline"]["modified"])
