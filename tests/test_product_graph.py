"""Name and graph queries preserve stable identities, versions and direction."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from distillai.knowledge import KnowledgeIndex, IndexNotReady
from distillai.storage import Store, atomic_json


A, B, C, R, S = (str(i) * 32 for i in range(1, 6))


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "data")
        for kind in ("knowledge", "relations"):
            (self.store.home / kind).mkdir()
        queue = self.store.home / "codex/queue/synthetic.jsonl"
        queue.parent.mkdir(parents=True)
        queue.write_text('{"role":"user","text":"synthetic evidence"}\n', encoding="utf-8")
        self.source = {"connector": "codex", "session_key": "synthetic", "line_start": 1, "line_end": 1}
        self.write("knowledge", {"id": A, "name": "Cause", "aliases": ["Shared"], "content": {"summary": "cause content", "source_refs": [self.source]}, "cognition": {"understanding": "unknown"}})
        self.write("knowledge", {"id": B, "name": "Effect", "aliases": ["shared"], "content": {"summary": "effect content", "source_refs": [self.source]}})
        self.write("knowledge", {"id": C, "name": "Isolated", "content": {"summary": "isolated content", "source_refs": [self.source]}})
        self.write("relations", self.relation(R, "Causal link"))
        self.write("relations", self.relation(S, "Prerequisite link"))
        self.index = KnowledgeIndex(self.store)
        self.index.rebuild()

    def relation(self, identifier, name):
        return {"id": identifier, "name": name, "source_knowledge_id": A, "target_knowledge_id": B,
                "kind": "knowledge_relation", "relation_type": "custom relation type", "direction_semantics": "source to target",
                "content": {"statement": "synthetic relation", "source_refs": [self.source]}}

    def write(self, kind, record):
        atomic_json(self.store.home / kind / (record["id"] + ".json"), record)

    def test_lookup_is_exact_case_insensitive_and_aliases_can_match_multiple(self):
        self.assertEqual(self.index.lookup(" cause ")["matches"][0]["id"], A)
        self.assertEqual([r["id"] for r in self.index.lookup("SHARED")["matches"]], [A, B])
        self.assertEqual(self.index.lookup("caus")["matches"], [])
        self.assertEqual(self.index.detail("knowledge", A)["record"]["content"]["summary"], "cause content")
        with self.assertRaises(FileNotFoundError):
            self.index.detail("knowledge", "f" * 32)

    def test_multirelations_keep_edges_and_deduplicate_neighbors_without_content_attributes(self):
        result = self.index.neighbors(A)
        self.assertEqual([r["id"] for r in result["knowledge_refs"]], [B])
        self.assertEqual([r["id"] for r in result["relations"]], [R, S])
        self.assertEqual(self.index.neighbors(A, direction="in"), {"knowledge_refs": [], "relations": []})
        self.assertEqual([r["id"] for r in self.index.neighbors(B, direction="in")["knowledge_refs"]], [A])
        self.assertEqual(self.index.neighbors(C), {"knowledge_refs": [], "relations": []})
        self.assertNotIn("cause content", json.dumps(result))
        self.assertNotIn("cognition", json.dumps(result))
        with self.assertRaises(ValueError):
            self.index.neighbors(A, direction="sideways")
        with self.assertRaises(FileNotFoundError):
            self.index.neighbors("f" * 32)

    def test_symmetric_inactive_rename_and_historical_detail(self):
        old = self.index.detail("knowledge", A)
        symmetric = self.relation(R, "Analogy")
        symmetric.update(kind="user_association", relation_type="analogy", symmetric=True)
        self.write("relations", symmetric)
        self.write("relations", {**self.relation(S, "Retired link"), "record_status": "inactive"})
        self.write("knowledge", {**old["record"], "name": "Reference concept"})
        self.index.rebuild()
        for node in (A, B):
            for direction in ("in", "out", "both"):
                result = self.index.neighbors(node, direction=direction)
                self.assertEqual([r["id"] for r in result["relations"]], [R])
                self.assertEqual((result["relations"][0]["source_knowledge_id"], result["relations"][0]["target_knowledge_id"]), (A, B))
        self.assertEqual(self.index.lookup("Cause")["matches"], [])
        self.assertEqual(self.index.lookup("reference concept")["matches"][0]["id"], A)
        self.assertEqual(self.index.detail("knowledge", A, version=old["version"]), old)

    def test_symmetric_self_loop_and_parallel_edges_are_returned_once(self):
        self.write("relations", {**self.relation(R, "Self analogy"), "target_knowledge_id": A, "symmetric": True})
        reverse = "6" * 32
        self.write("relations", {**self.relation(reverse, "Reverse analogy"),
            "source_knowledge_id": B, "target_knowledge_id": A, "symmetric": True})
        self.index.rebuild()
        for direction, expected in (("in", [R, reverse]), ("out", [R, S, reverse]), ("both", [R, S, reverse])):
            result = self.index.neighbors(A, direction=direction)
            self.assertEqual([ref["id"] for ref in result["knowledge_refs"]], [A, B])
            self.assertEqual([ref["id"] for ref in result["relations"]], expected)
        self.assertEqual([ref["id"] for ref in self.index.neighbors(B, direction="out")["relations"]], [reverse])

    def test_failed_rebuild_has_no_stale_graph_and_detail_stays_available(self):
        old = self.index.neighbors(A)
        with patch.object(self.store, "_scan", side_effect=OSError("synthetic failure")), self.assertRaises(OSError):
            self.index.rebuild()
        with self.assertRaises(IndexNotReady):
            self.index.neighbors(A)
        self.assertEqual(self.index.detail("knowledge", A)["record"]["name"], "Cause")
        self.index.rebuild()
        self.assertEqual(self.index.neighbors(A), old)
        rebuilt = KnowledgeIndex(self.store)
        rebuilt.rebuild()
        self.assertEqual(rebuilt.neighbors(A), old)


if __name__ == "__main__":
    unittest.main()
