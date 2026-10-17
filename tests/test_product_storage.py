"""Publication must preserve user edits and retain recoverable byte versions."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from distillai.storage import ConflictError, Store, _relative


@unittest.skipUnless(os.name == "nt", "Publication requires Windows handles")
class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.store = Store(self.root / "data")

    def task(self, files):
        for name, content in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        task = self.store.create_workspace(self.source)
        return task["id"], Path(task["workspace"])

    def publish(self, task_id):
        commit = self.store.prepare(task_id)
        return self.store.publish(commit["id"], lambda: None)

    def test_add_modify_delete_rename_and_unchanged(self):
        task_id, work = self.task({"edit.txt": b"old", "delete.txt": b"remove",
                                   "rename.txt": b"move", "same.txt": b"same"})
        identity = (self.source / "same.txt").stat().st_ino
        modified = (self.source / "edit.txt").stat().st_ino
        (work / "edit.txt").write_bytes(b"new")
        (work / "delete.txt").unlink()
        (work / "rename.txt").rename(work / "renamed.txt")
        (work / "add.txt").write_bytes(b"added")
        commit = self.publish(task_id)
        self.assertEqual(commit["status"], "committed")
        self.assertEqual({p.name: p.read_bytes() for p in self.source.iterdir()},
                         {"edit.txt": b"new", "same.txt": b"same", "renamed.txt": b"move", "add.txt": b"added"})
        self.assertEqual((self.source / "same.txt").stat().st_ino, identity)
        self.assertEqual((self.source / "edit.txt").stat().st_ino, modified)
        item = next(item for item in commit["items"] if item["path"] == "edit.txt")
        self.assertEqual(self.store.read_version(item["before"]), b"old")
        self.assertEqual(self.store.read_version(item["after"]), b"new")

    def test_copy_is_independent_and_user_edit_blocks_publication(self):
        task_id, work = self.task({"a.txt": b"original"})
        (work / "a.txt").write_bytes(b"agent")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"original")
        (self.source / "a.txt").write_bytes(b"user")
        commit = self.store.prepare(task_id)
        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], lambda: None)
        self.assertEqual((self.source / "a.txt").read_bytes(), b"user")
        self.assertNotEqual(self.store.read_commit(commit["id"])["status"], "committed")

    def test_damaged_commit_is_rejected_before_recovery_or_file_changes(self):
        task_id, work = self.task({"a.txt": b"original"})
        (work / "a.txt").write_bytes(b"new")
        commit = self.store.prepare(task_id)
        with self.store.state.transaction() as connection:
            original = connection.execute("SELECT record FROM commits WHERE id=?", (commit["id"],)).fetchone()[0]
        for changed in ({"extra": "ignored"}, {"state": "unknown"}, {"identity": [True, 1, 2]}):
            record = json.loads(original)
            record["items"][0].update(changed)
            damaged = json.dumps(record)
            with self.store.state.transaction() as connection:
                connection.execute("UPDATE commits SET record=? WHERE id=?", (damaged, commit["id"]))
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.store.recover(commit["id"])
            self.assertEqual((self.source / "a.txt").read_bytes(), b"original")
            with self.store.state.transaction(write=False) as connection:
                self.assertEqual(connection.execute("SELECT status,record FROM commits WHERE id=?", (commit["id"],)).fetchone(), ("prepared", damaged))

    def test_raw_relative_paths_cannot_hide_empty_or_dot_segments(self):
        for value in ("a/./b", "a//b", "a/../b", "a/", "CON.txt", "x:stream", "a\\b", "/absolute"):
            with self.subTest(path=value), self.assertRaises(ConflictError):
                _relative(value)
        self.assertEqual(_relative("合成/regular.txt"), Path("合成/regular.txt"))

    def test_new_file_collision_keeps_user_file(self):
        task_id, work = self.task({})
        (work / "new.txt").write_bytes(b"agent")
        commit = self.store.prepare(task_id)
        (self.source / "new.txt").write_bytes(b"user")
        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], lambda: None)
        self.assertEqual((self.source / "new.txt").read_bytes(), b"user")

    def interrupt_after_first_write(self, task_id):
        commit = self.store.prepare(task_id)
        original = self.store._save_commit

        def crash(record):
            original(record)
            if record["status"] == "prepared" and any(i["state"] == "applied" for i in record["items"]):
                raise KeyboardInterrupt("simulated process exit after durable publication")

        with patch.object(self.store, "_save_commit", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.store.publish(commit["id"], lambda: None)
        return commit["id"]

    def test_interrupted_batch_rolls_back_without_running_model(self):
        task_id, work = self.task({"a.txt": b"a", "b.txt": b"b"})
        (work / "a.txt").write_bytes(b"changed")
        (work / "b.txt").unlink()
        commit_id = self.interrupt_after_first_write(task_id)
        store = Store(self.root / "data")
        self.assertEqual(store.recover(commit_id)["status"], "rolled_back")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"a")
        self.assertEqual((self.source / "b.txt").read_bytes(), b"b")
        self.assertEqual(store.recover(commit_id)["status"], "rolled_back")

    def test_recovery_preserves_later_user_edit(self):
        task_id, work = self.task({"a.txt": b"a", "b.txt": b"b"})
        (work / "a.txt").write_bytes(b"changed")
        (work / "b.txt").write_bytes(b"changed b")
        commit_id = self.interrupt_after_first_write(task_id)
        (self.source / "a.txt").write_bytes(b"new user edit")
        recovered = self.store.recover(commit_id)
        self.assertEqual(recovered["status"], "recovery_conflict")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"new user edit")
        self.assertEqual((self.source / "b.txt").read_bytes(), b"b")
        self.assertEqual(self.store.read_version(recovered["items"][0]["before"]), b"a")

    def test_deleted_file_recovery_preserves_identity_and_collision(self):
        task_id, work = self.task({"a.txt": b"deleted", "b.txt": b"b"})
        identity = (self.source / "a.txt").stat().st_ino
        (work / "a.txt").unlink()
        (work / "b.txt").write_bytes(b"changed")
        commit_id = self.interrupt_after_first_write(task_id)
        (self.source / "a.txt").write_bytes(b"user replacement")
        self.assertEqual(self.store.recover(commit_id)["status"], "recovery_conflict")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"user replacement")
        (self.source / "a.txt").unlink()
        self.assertEqual(self.store.recover(commit_id)["status"], "rolled_back")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"deleted")
        self.assertEqual((self.source / "a.txt").stat().st_ino, identity)

    def test_authorization_or_revision_failure_never_publishes(self):
        task_id, work = self.task({"a.txt": b"a"})
        (work / "a.txt").write_bytes(b"changed")
        commit = self.store.prepare(task_id)

        def stale():
            raise ConflictError("input revision or permission changed")

        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], stale)
        self.assertEqual((self.source / "a.txt").read_bytes(), b"a")

    def test_committed_recovery_is_idempotent_and_does_not_undo_user_edit(self):
        task_id, work = self.task({"a.txt": b"a"})
        (work / "a.txt").write_bytes(b"changed")
        commit = self.publish(task_id)
        (self.source / "a.txt").write_bytes(b"user")
        self.assertEqual(self.store.recover(commit["id"])["status"], "committed")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"user")

    def test_committed_missing_content_reports_conflict_without_reverting_other_files(self):
        task_id, work = self.task({"a.txt": b"old a", "b.txt": b"old b"})
        (work / "a.txt").write_bytes(b"new a")
        (work / "b.txt").write_bytes(b"new b")
        commit = self.publish(task_id)
        (self.source / "a.txt").unlink()
        recovered = self.store.recover(commit["id"])
        self.assertEqual(recovered["status"], "committed")
        self.assertEqual([item["path"] for item in recovered.get("conflicts", [])], ["a.txt"])
        self.assertEqual((self.source / "b.txt").read_bytes(), b"new b")
        self.assertEqual(self.store.read_version(next(item["before"] for item in recovered["items"] if item["path"] == "a.txt")), b"old a")
        (self.source / "a.txt").write_bytes(b"user restored content")
        self.assertEqual(self.store.recover(commit["id"])["conflicts"], [])
        self.assertEqual((self.source / "a.txt").read_bytes(), b"user restored content")

    def test_source_hardlink_and_workspace_hardlink_are_rejected(self):
        (self.source / "a.txt").write_bytes(b"a")
        os.link(self.source / "a.txt", self.source / "alias.txt")
        with self.assertRaises(ConflictError):
            self.store.create_workspace(self.source)
        (self.source / "alias.txt").unlink()
        task = self.store.create_workspace(self.source)
        work = Path(task["workspace"])
        os.link(work / "a.txt", work / "alias.txt")
        with self.assertRaises(ConflictError):
            self.store.prepare(task["id"])

    def test_workspace_alternate_stream_is_rejected(self):
        task_id, work = self.task({"a.txt": b"a"})
        Path(str(work / "a.txt") + ":hidden").write_bytes(b"hidden")
        with self.assertRaises(ConflictError):
            self.store.prepare(task_id)

    def test_new_subdirectory_and_failed_batch_recovery(self):
        task_id, work = self.task({"z.txt": b"z"})
        (work / "nested").mkdir()
        (work / "nested" / "new.txt").write_bytes(b"new")
        (work / "z.txt").write_bytes(b"changed")
        commit_id = self.interrupt_after_first_write(task_id)
        self.assertEqual(self.store.recover(commit_id)["status"], "rolled_back")
        self.assertFalse((self.source / "nested").exists())
        self.assertEqual((self.source / "z.txt").read_bytes(), b"z")

    def test_later_baseline_conflict_prevents_earlier_file_write(self):
        task_id, work = self.task({"a.txt": b"a", "z.txt": b"z"})
        (work / "a.txt").write_bytes(b"agent a")
        (work / "z.txt").write_bytes(b"agent z")
        commit = self.store.prepare(task_id)
        (self.source / "z.txt").write_bytes(b"user z")
        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], lambda: None)
        self.assertEqual((self.source / "a.txt").read_bytes(), b"a")
        self.assertEqual((self.source / "z.txt").read_bytes(), b"user z")

    def test_interruption_before_applied_journal_still_restores(self):
        task_id, work = self.task({"a.txt": b"a"})
        (work / "a.txt").write_bytes(b"changed")
        commit = self.store.prepare(task_id)
        original = self.store._save_commit

        def crash(record):
            if any(i["state"] == "applied" for i in record["items"]):
                raise KeyboardInterrupt("exit after write, before applied journal")
            original(record)

        with patch.object(self.store, "_save_commit", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.store.publish(commit["id"], lambda: None)
        self.assertEqual((self.source / "a.txt").read_bytes(), b"changed")
        self.assertEqual(self.store.recover(commit["id"])["status"], "rolled_back")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"a")

    def test_new_file_recovery_keeps_later_user_edit(self):
        task_id, work = self.task({})
        (work / "a.txt").write_bytes(b"new")
        commit_id = self.interrupt_after_first_write(task_id)
        (self.source / "a.txt").write_bytes(b"user")
        self.assertEqual(self.store.recover(commit_id)["status"], "recovery_conflict")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"user")

    def test_replaced_source_directory_is_not_authorized_by_old_task(self):
        task_id, work = self.task({})
        (work / "a.txt").write_bytes(b"new")
        commit = self.store.prepare(task_id)
        self.source.rename(self.root / "old-source")
        self.source.mkdir()
        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], lambda: None)
        self.assertFalse((self.source / "a.txt").exists())

    def test_partial_write_is_not_blindly_restored(self):
        task_id, work = self.task({"a.txt": b"a"})
        (work / "a.txt").write_bytes(b"changed")
        commit_id = self.interrupt_after_first_write(task_id)
        (self.source / "a.txt").write_bytes(b"partial")
        self.assertEqual(self.store.recover(commit_id)["status"], "recovery_conflict")
        self.assertEqual((self.source / "a.txt").read_bytes(), b"partial")

    def test_workspace_directory_metadata_changes_are_rejected(self):
        task_id, work = self.task({"nested/a.txt": b"a"})
        import ctypes
        set_attributes = ctypes.WinDLL("kernel32", use_last_error=True).SetFileAttributesW
        set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong]
        self.assertTrue(set_attributes(str(work / "nested"), 0x12))
        with self.assertRaises(ConflictError):
            self.store.prepare(task_id)

    def test_business_subtree_can_be_copied_but_runtime_state_cannot(self):
        business = self.store.home / "knowledge"
        business.mkdir()
        (business / "item.json").write_bytes(b'{"id":"synthetic"}')
        task = self.store.create_workspace(business)
        self.assertEqual((Path(task["workspace"]) / "item.json").read_bytes(), b'{"id":"synthetic"}')
        for private in (self.store.home, self.store.home / "tasks", self.store.home / "workspaces"):
            with self.assertRaises(ConflictError):
                self.store.create_workspace(private)

    def test_selected_business_roots_share_one_commit_without_private_state(self):
        for name in ("knowledge", "relations"):
            (self.store.home / name).mkdir()
            (self.store.home / name / "item.json").write_bytes(b"old")
        task = self.store.create_workspace(self.store.home, allowed_paths=["knowledge", "relations"])
        work = Path(task["workspace"])
        self.assertEqual({p.name for p in work.iterdir()}, {"knowledge", "relations"})
        for name in ("knowledge", "relations"):
            (work / name / "item.json").write_bytes(b"new")
        self.assertEqual(self.publish(task["id"])["status"], "committed")
        self.assertEqual((self.store.home / "knowledge" / "item.json").read_bytes(), b"new")
        self.assertEqual((self.store.home / "relations" / "item.json").read_bytes(), b"new")

    def test_copy_scope_cannot_be_expanded_by_task_output(self):
        (self.store.home / "knowledge").mkdir()
        task = self.store.create_workspace(self.store.home, allowed_paths=["knowledge"])
        (Path(task["workspace"]) / "config.json").write_bytes(b"unauthorized")
        with self.assertRaises(ConflictError):
            self.store.prepare(task["id"])
        with self.assertRaises(ConflictError):
            self.store.create_workspace(self.store.home, allowed_paths=["config"])

    def test_unicode_directory_and_filename_survive_copy_and_publication(self):
        task_id, work = self.task({"中文/🦆.txt": b"before"})
        (work / "中文" / "🦆.txt").write_bytes(b"after")
        self.assertEqual(self.publish(task_id)["status"], "committed")
        self.assertEqual((self.source / "中文" / "🦆.txt").read_bytes(), b"after")

    def test_unchanged_context_file_changed_by_user_invalidates_fixed_snapshot(self):
        task_id, work = self.task({"target.txt": b"old", "context.txt": b"context"})
        (work / "target.txt").write_bytes(b"agent result")
        commit = self.store.prepare(task_id)
        (self.source / "context.txt").write_bytes(b"user changed input")
        with self.assertRaises(ConflictError):
            self.store.publish(commit["id"], lambda: None)
        self.assertEqual((self.source / "target.txt").read_bytes(), b"old")
        self.assertEqual((self.source / "context.txt").read_bytes(), b"user changed input")


if __name__ == "__main__":
    unittest.main()
