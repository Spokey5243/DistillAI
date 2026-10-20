"""Offline, verified conversion of legacy JSON control state to SQLite."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

import portalocker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from distillai.state import State
from distillai.startup import _lease, live_instance


def manifest(home):
    result = {}
    for path in sorted(home.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Migration refuses linked runtime data")
        if not path.is_file() or path.name in {".lock", ".instance.lock", "state.sqlite3", "state.sqlite3-journal", "state.sqlite3-wal", "state.sqlite3-shm"}:
            continue
        result[path.relative_to(home).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_database(state):
    with state.transaction(write=False) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Control database integrity check failed")


def migrate(home, *, writers_stopped):
    home = Path(home).resolve(strict=True)
    if not writers_stopped:
        raise ValueError("Stop all capture entry points and wait for in-flight Hooks; confirm writers stopped explicitly")
    if live_instance(home) is not None:
        raise ValueError("Stop the backend and all task trees before migration")
    with _lease(home) as owned, ExitStack() as held:
        if not owned:
            raise ValueError("A backend still owns this data root")
        held.enter_context(portalocker.Lock(home / ".lock", mode="a+b", timeout=0))
        existing = home / "state.sqlite3"
        before = manifest(home)
        if existing.exists():
            state = State(home)
            with state.transaction(write=False) as connection:
                row = connection.execute("SELECT manifest FROM migration WHERE singleton=1").fetchone()
                recorded = json.loads(row[0]) if row else None
            if recorded is None or recorded["files"] != before:
                raise ValueError("Existing database is not this unchanged completed migration; refusing overwrite")
            verify_database(state)
            return {"already_migrated": True, "backup": recorded["backup"]}
        tasks = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((home / "tasks").glob("*.json"))]
        commits = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((home / "commits").glob("*.json"))]
        if any(record["status"] not in {"committed", "rolled_back"} for record in commits):
            raise ValueError("Recover unresolved publication with the old program before migration")
        if any(task.get("status") in {"running", "recovering", "validating"} for task in tasks):
            raise ValueError("Recover interrupted tasks and confirm every task tree has stopped before migration")
        current = json.loads((home / "config.json").read_text(encoding="utf-8"))
        for task in tasks:
            for key in ("input_version", "prompt_version", "execution_input_version", "result_version", "model_output_version"):
                digest = task.get(key)
                if digest and (len(digest) != 64 or hashlib.sha256((home / "versions" / digest).read_bytes()).hexdigest() != digest):
                    raise ValueError("Task content reference is missing or damaged")
        history = json.loads((home / "config" / f"{current['version']}.json").read_text(encoding="utf-8"))
        if history != current:
            raise ValueError("Current private configuration disagrees with its immutable version")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = home.with_name(home.name + ".migration-backup-" + stamp + "-" + uuid.uuid4().hex[:8])
        shutil.copytree(home, backup, ignore=shutil.ignore_patterns(".lock", ".instance.lock"))
        if manifest(backup) != before or manifest(home) != before:
            raise ValueError("Data changed during backup; keep all writers stopped and inspect the retained backup")
        record = {"files": before, "backup": str(backup), "created_at": stamp}
        with tempfile.TemporaryDirectory(prefix="." + home.name + "-migration-", dir=home.parent) as temporary:
            state = State(temporary)
            with state.transaction() as connection:
                for task in tasks:
                    state.save_task(task, connection=connection)
                for commit in commits:
                    state.save_commit(commit, connection=connection)
                state.set_config(current["version"], connection=connection)
                connection.execute("INSERT INTO migration VALUES(1,?)", (json.dumps(record, ensure_ascii=False),))
            verify_database(state)
            for task in tasks:
                saved = state.read_task(task["id"])
                if any(saved.get(field) != task.get(field) for field in ("id", "order", "model_calls", "status", "generation_attempts", "input_version", "result_version")):
                    raise ValueError("Migrated task state does not match its source")
            if manifest(home) != before:
                raise ValueError("A writer changed runtime data before installation; migration aborted")
            # rename refuses an unexpected destination on Windows.
            os.rename(state.path, existing)
        receipt = {"home": str(home), "backup": str(backup), "files": before,
                   "database_hash": hashlib.sha256(existing.read_bytes()).hexdigest()}
        backup.with_name(backup.name + ".receipt.json").write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
        return {"already_migrated": False, "tasks": len(tasks), "commits": len(commits), "backup": str(backup)}


def rollback(home, backup, *, writers_stopped):
    home, backup = Path(home).resolve(strict=True), Path(backup).resolve(strict=True)
    if not writers_stopped or live_instance(home) is not None:
        raise ValueError("Stop all writers and task trees before rollback")
    if home == backup or home in backup.parents or backup in home.parents:
        raise ValueError("Rollback backup and data root must be separate directories")
    receipt = json.loads(backup.with_name(backup.name + ".receipt.json").read_text(encoding="utf-8"))
    if receipt["home"] != str(home) or receipt["backup"] != str(backup):
        raise ValueError("Rollback receipt belongs to another data root")
    with _lease(home) as owned, portalocker.Lock(home / ".lock", mode="a+b", timeout=0):
        if not owned:
            raise ValueError("The backend is still running")
        if manifest(home) != receipt["files"] or manifest(backup) != receipt["files"]:
            raise ValueError("Runtime content or capture queue changed; refusing stale backup rollback")
        database = home / "state.sqlite3"
        if hashlib.sha256(database.read_bytes()).hexdigest() != receipt["database_hash"] or any(
                (home / ("state.sqlite3" + suffix)).exists() for suffix in ("-journal", "-wal", "-shm")):
            raise ValueError("Control database has changed; refusing stale backup rollback")
        # Keep all evidence; swapping the stopped root happens only after releasing its lock handles.
        retired = home.with_name(home.name + ".rollback-retired-" + uuid.uuid4().hex)
    if manifest(home) != receipt["files"] or hashlib.sha256(database.read_bytes()).hexdigest() != receipt["database_hash"]:
        raise ValueError("Runtime data changed before rollback; keep capture disabled")
    with tempfile.TemporaryDirectory(prefix="." + home.name + "-restore-", dir=home.parent) as temporary:
        restored = Path(temporary) / home.name
        shutil.copytree(backup, restored)
        if manifest(restored) != receipt["files"]:
            raise ValueError("Restored backup verification failed")
        home.rename(retired)
        try:
            restored.rename(home)
        except BaseException:
            retired.rename(home)
            raise
    return {"rolled_back": True, "retained_migrated_root": str(retired)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--confirm-writers-stopped", action="store_true",
                        help="All capture entry points, in-flight Hooks, backend and task trees have stopped")
    parser.add_argument("--rollback-backup", help="Restore this migration backup only when no new writes occurred")
    args = parser.parse_args()
    result = (rollback(args.home, args.rollback_backup, writers_stopped=args.confirm_writers_stopped)
              if args.rollback_backup else migrate(args.home, writers_stopped=args.confirm_writers_stopped))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
