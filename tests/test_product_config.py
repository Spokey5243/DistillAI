"""Versioned configuration must retain secrets, reject invalid input and freeze tasks."""
import tempfile
from copy import deepcopy
from pathlib import Path
import unittest

from distillai.config import Config, ConfigError
from distillai.storage import ConflictError, Store, atomic_json


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.config = Config(self.store)

    def test_damaged_private_configuration_is_not_adopted_or_rewritten(self):
        original = self.config.private()
        path = self.store.home / "config/1.json"
        for changed in ({"version": True}, {"version": 2}, {"extra": "ignored"},
                        {"values": {**original["values"], "runtime": {"max_model_calls": True, "poll_interval_seconds": 1}}}):
            atomic_json(path, {**original, **changed})
            before = path.read_bytes()
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.config.private()
            self.assertEqual(path.read_bytes(), before)

    def test_legacy_private_configuration_without_search_keeps_original_bytes(self):
        record = deepcopy(self.config.private())
        del record["values"]["search"]
        path = self.store.home / "config/1.json"
        atomic_json(path, record)
        before = path.read_bytes()
        self.assertEqual(self.config.private()["values"]["search"], {"api_key": ""})
        self.assertEqual(path.read_bytes(), before)

    def test_initial_values_and_invalid_update_preserves_version(self):
        current = self.config.read()
        self.assertEqual(current["values"]["runtime"]["max_model_calls"], 16)
        self.assertEqual(current["values"]["episode"]["switch_buffer_turns"], 3)
        self.assertEqual(current["values"]["context"]["refresh_update_count"], 3)
        self.assertEqual(current["values"]["expansion"], {"interval_seconds": 3600, "batch_size": 10})
        for invalid in (0, -1, True, "16", 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                self.config.update(current["version"], {"runtime": {"max_model_calls": invalid}})
            self.assertEqual(self.config.read(), current)

    def test_secret_redaction_and_blank_display_do_not_clear_saved_key(self):
        updated = self.config.update(1, {"llm": {"api_key": "synthetic-test-credential"}})
        self.assertEqual(updated["values"]["llm"]["api_key"], "")
        self.assertTrue(updated["api_key_configured"])
        next_version = self.config.update(updated["version"], {"llm": {"api_key": "", "model": "synthetic"}})
        self.assertEqual(self.config.private(next_version["version"])["values"]["llm"]["api_key"], "synthetic-test-credential")
        self.assertNotIn("synthetic-test-credential", str(self.config.snapshot()))

    def test_search_credential_is_private_versioned_and_blank_does_not_erase_it(self):
        first = self.config.update(1, {"search": {"api_key": "synthetic-search-key"}})
        self.assertTrue(first["search_key_configured"])
        self.assertEqual(first["values"]["search"]["api_key"], "")
        second = self.config.update(first["version"], {"search": {"api_key": ""}})
        self.config.update(second["version"], {"search": {"api_key": "replacement-search-key"}})
        self.assertEqual(self.config.private(second["version"])["values"]["search"]["api_key"], "synthetic-search-key")
        self.assertNotIn("synthetic-search-key", str(first))
        self.assertNotIn("replacement-search-key", str(self.config.snapshot()))
        with self.assertRaises(ConfigError):
            self.config.update(4, {"search": {"api_key": "invalid\nheader"}})
        cleared = self.config.update(4, {"search": {"api_key": None}})
        self.assertFalse(cleared["search_key_configured"])
        self.assertEqual(self.config.private()["values"]["search"]["api_key"], "")

    def test_stale_version_is_rejected_and_old_task_snapshot_remains_readable(self):
        old = self.config.snapshot()
        self.config.update(old["version"], {"runtime": {"max_model_calls": 8}})
        with self.assertRaises(ConflictError):
            self.config.update(old["version"], {"runtime": {"max_model_calls": 4}})
        self.assertEqual(self.config.private(old["version"])["values"]["runtime"]["max_model_calls"], 16)
        self.assertEqual(old["values"]["runtime"]["max_model_calls"], 16)
        self.assertEqual(Config(self.store).read()["values"]["runtime"]["max_model_calls"], 8)

    def test_invalid_endpoint_protocol_and_parameter_are_field_errors(self):
        for patch in ({"llm": {"base_url": "file:///secret"}},
                      {"llm": {"api": "invented"}},
                      {"llm": {"parameters": {"made_up": 1}}},
                      {"llm": {"parameters": {"temperature": 99}}},
                      {"runtime": {"poll_interval_seconds": float("nan")}},
                      {"runtime": {"poll_interval_seconds": 10 ** 500}},
                      {"llm": {"api_key": "无效凭证"}},
                      {"unrecognized": {"value": 1}}):
            with self.subTest(patch=patch), self.assertRaises(ConfigError) as error:
                self.config.update(1, patch)
            self.assertTrue(error.exception.fields)
            self.assertEqual(self.config.read()["version"], 1)

    def test_valid_model_parameters_have_no_unrequested_defaults(self):
        self.assertEqual(self.config.read()["values"]["llm"]["parameters"], {})
        result = self.config.update(1, {"llm": {"api": "chat_completions",
                                               "base_url": "https://api.deepseek.com",
                                               "model": "deepseek-flash",
                                               "parameters": {"max_tokens": 1024, "thinking": {"type": "disabled"}}}})
        self.assertEqual(result["values"]["llm"]["parameters"],
                         {"max_tokens": 1024, "thinking": {"type": "disabled"}})

    def test_workspace_paths_cannot_authorize_runtime_state_or_program(self):
        for forbidden in (self.root, self.store.home, Path(__file__).resolve().parents[1]):
            with self.subTest(forbidden=forbidden), self.assertRaises(ConfigError):
                self.config.update(1, {"workspace": {"paths": [str(forbidden)]}})
        workspace = self.root / "workspace"
        workspace.mkdir()
        result = self.config.update(1, {"workspace": {"paths": [str(workspace)]}})
        self.assertEqual([Path(path).resolve() for path in result["values"]["workspace"]["paths"]], [workspace.resolve()])

    def test_dot_segments_do_not_authorize_private_runtime_directory(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        with self.assertRaises(ConfigError):
            self.config.update(1, {"workspace": {"paths": [str(workspace / ".." / "data")]}})


if __name__ == "__main__":
    unittest.main()
