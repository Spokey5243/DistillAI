"""SDK transport retains durable request budgets, connection failures and private history."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import httpx

from distillai.config import Config
from distillai.hermes import _meter_client, _model_result, _operation, HermesError
from distillai.runtime import Runtime
from distillai.storage import Store


class HermesTransportTests(unittest.TestCase):
    def test_model_result_accepts_one_json_fence_and_rejects_prose_or_trailing_payloads(self):
        expected = {"knowledge_refs": [], "relation_refs": [], "reason": "no change"}
        body = json.dumps(expected)
        for text in (body, "```json\n" + body + "\n```", "```\r\n" + body + "\r\n```"):
            with self.subTest(text=text):
                self.assertEqual(_model_result(text), expected)
        for text in ("explanation " + body, body + body, "```json\n" + body + "\n``` extra",
                     "```python\n" + body + "\n```", "```json\nnot JSON\n```"):
            with self.subTest(text=text), self.assertRaises(json.JSONDecodeError):
                _model_result(text)

    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.store = Store(Path(temporary) / "data")
        config = Config(self.store)
        config.update(1, {"llm": {"model": "synthetic", "base_url": "https://model.test/v1", "api_key": "synthetic-key"}})
        self.runtime = Runtime(self.store, config, lambda task, control: {}, lambda task, result: None)
        self.addCleanup(self.runtime.close)
        self.task = self.runtime.register("query", {}, "synthetic-model")
        self.task["status"] = "running"
        self.runtime._save(self.task)
        self.frame = {"llm": config.private()["values"]["llm"]}
        self.enterContext(patch("distillai.hermes._program_tool", side_effect=lambda frame, operation, args: _operation(self.runtime, self.task["id"], operation, args)))

    def client(self, handler):
        client = self.enterContext(httpx.Client(transport=httpx.MockTransport(handler)))
        return _meter_client(client, self.frame)

    def generate(self, client, messages=None):
        return client.post("https://model.test/v1/chat/completions", json={"model": "synthetic", "messages": messages or [{"role": "user", "content": "synthetic"}]})

    def test_last_allowed_request_completes_and_rebuilt_client_cannot_send_an_extra(self):
        received = []
        def provider(request):
            received.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic"}}]})
        client = self.client(provider)
        for _ in range(16):
            self.assertEqual(self.generate(client).status_code, 200)
        restarted = self.client(provider)
        self.assertEqual(self.generate(restarted).status_code, 400)
        self.assertEqual(len(received), 16)
        self.assertEqual(Store(self.store.home).read_task(self.task["id"])["model_calls"], 16)

    def test_unsent_connection_failure_is_refunded_but_read_timeout_stays_counted(self):
        for error, expected in ((httpx.ConnectError("not connected"), 0), (httpx.ReadTimeout("unknown delivery"), 1)):
            def fail(request):
                raise error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.generate(self.client(fail))
            self.assertEqual(self.runtime.task(self.task["id"])["model_calls"], expected)

    def test_history_keeps_actual_prompt_without_internal_reasoning_or_credentials(self):
        messages = [{"role": "system", "content": "actual synthetic system prompt"},
                    {"role": "assistant", "content": "visible", "reasoning_content": "private reasoning"}]
        self.generate(self.client(lambda request: httpx.Response(200, json={})), messages)
        task = self.runtime.task(self.task["id"])
        snapshot = self.store.read_version(next(iter(task["generation_attempts"].values()))["request_version"]).decode()
        self.assertIn("actual synthetic system prompt", snapshot)
        self.assertNotIn("private reasoning", snapshot)
        self.assertNotIn("synthetic-key", snapshot)

    def test_wrong_model_is_rejected_and_redirect_does_not_send_to_another_endpoint(self):
        requests = []
        client = self.client(lambda request: requests.append(request) or httpx.Response(307, headers={"Location": "https://other.test/v1/chat/completions"}))
        self.assertEqual(self.generate(client).status_code, 307)
        with self.assertRaises(HermesError):
            client.post("https://model.test/v1/chat/completions", json={"model": "other", "messages": []})
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.runtime.task(self.task["id"])["model_calls"], 1)

    def test_generation_operations_require_a_fixed_attempt_identity_before_writing(self):
        before = set((self.store.home / "versions").glob("*"))
        for attempt in (None, True, 1, "", "not-an-attempt"):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                _operation(self.runtime, self.task["id"], "reserve_generation",
                    {"attempt_id": attempt, "request": {"model": "synthetic"}})
        self.assertEqual(self.runtime.task(self.task["id"])["model_calls"], 0)
        self.assertEqual(set((self.store.home / "versions").glob("*")), before)


if __name__ == "__main__":
    unittest.main()
