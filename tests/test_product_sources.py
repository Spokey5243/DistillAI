"""Queue physical positions remain stable across tail repair and invalid input."""
import json
from pathlib import Path
import tempfile
import unittest

from distillai.capture import capture
from distillai.sources import SourceError, read_source, scan_queue, contains, record_submission
from distillai.config import Config
from distillai.runtime import Runtime
from distillai.storage import Store, atomic_json, ConflictError


def row(text="body", role="user"):
    return json.dumps({"role": role, "text": text}).encode()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.queue = self.home / "codex/queue/synthetic.jsonl"
        self.queue.parent.mkdir(parents=True)
        self.tool = {"hook_event_name": "PostToolUse", "session_id": "synthetic", "tool_name": "build"}
        self.ref = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 2}

    def test_user_submission_is_a_versioned_source_and_never_a_fabricated_queue_position(self):
        store = Store(self.home)
        ref = record_submission(store, {"content": "original synthetic edit"}, "synthetic correction", identifier="c" * 32)
        original = read_source(self.home, ref)
        self.assertEqual(ref["source_kind"], "user_submission")
        self.assertNotIn("line_start", ref)
        self.assertIn("original synthetic edit", original["text"])
        self.assertEqual(original["rows"][0]["role"], "user")
        self.assertEqual(record_submission(store, {"content": "original synthetic edit"}, "synthetic correction", identifier="c" * 32), ref)
        with self.assertRaises(ConflictError):
            record_submission(store, {"content": "changed"}, "same ID", identifier="c" * 32)
        unrelated = record_submission(store, {"content": "another edit"}, "another reason")
        with self.assertRaises(SourceError):
            read_source(self.home, {**ref, "version": unrelated["version"]})
        self.assertTrue(contains(ref, [ref]))
        self.assertFalse(contains(ref, [unrelated]))

    def test_external_source_keeps_the_read_excerpt_and_cannot_supply_user_performance(self):
        store = Store(self.home)
        folder = self.home / "external-sources"
        folder.mkdir()
        source = {"id": "d" * 32, "source_kind": "external", "url": "https://example.invalid/synthetic",
                  "title": "Synthetic primary source", "read_at": "2026-10-15T00:00:00Z", "text": "actually read excerpt"}
        path = folder / (source["id"] + ".json")
        atomic_json(path, source)
        ref = {"source_kind": "external", "id": source["id"], "version": store.put_version(path.read_bytes())}
        result = read_source(self.home, ref)
        self.assertEqual(result["text"], source["text"])
        self.assertEqual(result["rows"][0]["role"], "external")
        from distillai.cognition import source_identity
        with self.assertRaises(ValueError):
            source_identity(store, [ref])
        atomic_json(path, {**source, "text": "a later reading"})
        self.assertEqual(read_source(self.home, ref)["text"], "actually read excerpt")
        with self.assertRaises(SourceError):
            read_source(self.home, {**ref, "path": str(path)})

    def test_read_physical_rows_including_tools_and_reject_arbitrary_paths(self):
        self.queue.write_bytes(row("one\ntwo") + b"\n" + row("used build", "tool") + b"\n" + row("tail"))
        self.assertEqual([r["text"] for r in read_source(self.home, self.ref)["rows"]], ["one\ntwo", "used build"])
        for change in ({"connector": "file"}, {"session_key": "../synthetic"}, {"session_key": str(self.queue)},
                       {"line_start": 0}, {"line_end": True}, {"line_end": 3}, {"line_end": 1, "line_start": 2}, {"path": str(self.queue)}):
            with self.subTest(change=change), self.assertRaises(SourceError):
                read_source(self.home, {**self.ref, **change})

    def test_fixed_source_scope_allows_adjacent_ranges_but_cannot_swallow_gaps(self):
        self.assertTrue(contains(self.ref, [{**self.ref, "line_end": 1}, {**self.ref, "line_start": 2}]))
        self.assertFalse(contains({**self.ref, "line_end": 3}, [{**self.ref, "line_end": 1}, {**self.ref, "line_start": 3, "line_end": 3}]))
        self.assertFalse(contains({**self.ref, "line_end": 10 ** 100}, [self.ref]))
        self.assertFalse(contains({**self.ref, "session_key": "other"}, [self.ref]))

    def test_valid_tail_gets_lf_and_incomplete_tail_only_is_removed(self):
        prefix = row("stable") + b"\n"
        for tail, preserved in ((row("complete"), prefix + row("complete") + b"\n"), (b'{"role":', prefix)):
            self.queue.write_bytes(prefix + tail)
            self.assertEqual(capture(self.home, self.tool), "saved")
            self.assertTrue(self.queue.read_bytes().startswith(preserved))
            rows, invalid_line = scan_queue(self.home, "synthetic")
            self.assertIsNone(invalid_line)
            self.assertEqual(rows[-1]["role"], "tool")

    def test_bad_complete_fields_or_middle_bytes_are_preserved_and_block_later_rows(self):
        for suffix in (b'{"role":"unknown","text":"x"}', b'{"role":"user","text":""}\n', b'broken\n' + row("later") + b'\n', b'\n', b'not json', b'{"role"oops}'):
            original = row("stable") + b"\n" + suffix
            self.queue.write_bytes(original)
            self.assertEqual(capture(self.home, self.tool), "error")
            self.assertEqual(self.queue.read_bytes(), original)
            rows, invalid_line = scan_queue(self.home, "synthetic")
            self.assertEqual(len(rows), 1)
            self.assertEqual(invalid_line, 2 if b"\n" in suffix else None)

    def test_scanning_discovers_without_notification_and_never_changes_started_inputs(self):
        store = Store(self.home)
        runtime = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
        self.addCleanup(runtime.close)
        self.queue.write_bytes(row("first") + b"\n" + row("tool", "tool") + b"\n" + row("tail"))
        runtime.discover_materials()
        first = runtime.tasks()[0]
        self.assertEqual(first["inputs"]["source_refs"][0]["line_end"], 2)
        runtime.discover_materials()
        self.assertEqual(len(runtime.tasks()), 1)
        with self.queue.open("ab") as stream:
            stream.write(b"\n")
        runtime.discover_materials()
        merged = runtime.task(first["id"])
        self.assertNotEqual(merged["input_version"], first["input_version"])
        self.assertEqual(merged["inputs"]["source_refs"][0]["line_end"], 3)
        merged["started"], merged["status"] = True, "failed"
        runtime._save(merged)
        with self.queue.open("ab") as stream:
            stream.write(row("next") + b"\n" + b"broken\n" + row("must wait") + b"\n")
        runtime.discover_materials()
        self.assertEqual(runtime.task(first["id"])["input_version"], merged["input_version"])
        last = max(runtime.tasks(), key=lambda task: task["order"])
        self.assertEqual(last["inputs"]["source_refs"][0], {**self.ref, "line_start": 4, "line_end": 4})
        self.assertEqual(len(runtime.tasks()), 2)
        self.assertFalse((self.home / "codex/processed.json").exists())
        restarted = Runtime(store, Config(store), lambda task, control: {}, lambda task, result: None)
        self.addCleanup(restarted.close)
        restarted.discover_materials()
        self.assertEqual(len(restarted.tasks()), 2)


if __name__ == "__main__":
    unittest.main()
