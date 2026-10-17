"""Browser-only regressions: input retention, response ordering and text rendering."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import httpx
from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

from serve_fixture import A, HTML


class BrowserTests(unittest.TestCase):
    def tearDown(self):
        result = self._outcome.result
        if any(test is self for test, _ in result.failures + result.errors) and hasattr(self, "browser"):
            folder = Path(".artifacts/browser")
            folder.mkdir(parents=True, exist_ok=True)
            for index, page in enumerate(page for context in self.browser.contexts for page in context.pages):
                try:
                    page.screenshot(path=folder / f"{self._testMethodName}-{index}.png", timeout=3000)
                except PlaywrightError:
                    pass

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        self.log = (home / "fixture.log").open("wb")
        self.addCleanup(self.log.close)
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("serve_fixture.py")), str(home)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
            stdout=self.log, stderr=self.log, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.stop_fixture)
        self.http = httpx.Client(timeout=3, trust_env=False)
        self.addCleanup(self.http.close)
        deadline = time.monotonic() + 20
        self.instance = None
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                instance = json.loads((home / "instance.json").read_bytes())
                response = self.http.get(instance["url"] + "/v1/health",
                    headers={"Authorization": "Bearer " + instance["token"]})
                if response.status_code == 200 and response.json()["ready"]:
                    self.instance = instance
                    break
            except (OSError, ValueError, httpx.HTTPError):
                pass
            threading.Event().wait(.05)
        self.assertIsNotNone(self.instance, "Synthetic fixture did not become healthy: " + (home / "fixture.log").read_text(encoding="utf-8", errors="replace"))
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch()
        self.addCleanup(self.browser.close)

    def stop_fixture(self):
        if self.process.poll() is None:
            if self.instance:
                try:
                    with httpx.Client(timeout=3, trust_env=False) as client:
                        client.post(self.instance["url"] + "/internal/stop", json={},
                            headers={"Authorization": "Bearer " + self.instance["token"]})
                except httpx.HTTPError:
                    pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def request(self, path, method="GET", body=None):
        response = self.http.request(method, self.instance["url"] + path, json=body,
            headers={"Authorization": "Bearer " + self.instance["token"]})
        response.raise_for_status()
        return response.json()

    def page(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(10000)
        bootstrap = self.request("/internal/web/bootstrap", "POST", {})
        page.goto(bootstrap["url"])
        expect(page.get_by_role("heading", name="知识与关系", exact=True)).to_be_visible()
        return page

    def alpha(self, page):
        page.get_by_role("button", name="Alpha").click()
        expect(page.get_by_label("正文摘要", exact=True)).to_have_value(HTML)

    def edit(self, page, text, reason):
        page.get_by_label("正文摘要", exact=True).fill(text)
        page.get_by_label("修改原因", exact=True).fill(reason)

    def test_two_sessions_keep_losing_edit_and_reason_on_real_conflict(self):
        first, second = self.page(), self.page()
        self.alpha(first)
        self.alpha(second)
        self.edit(first, "Committed first", "First correction")
        first.get_by_role("button", name="提交修改", exact=True).click()
        expect(first.get_by_text("修改已提交。", exact=False)).to_be_visible()
        self.edit(second, "Keep my draft", "Keep my reason")
        with second.expect_response(lambda response: response.url.endswith("/v1/knowledge-edits") and response.status == 409):
            second.get_by_role("button", name="提交修改", exact=True).click()
        expect(second.get_by_text("记录已被其他操作修改。", exact=False)).to_be_visible()
        expect(second.get_by_label("正文摘要", exact=True)).to_have_value("Keep my draft")
        expect(second.get_by_label("修改原因", exact=True)).to_have_value("Keep my reason")
        self.assertEqual(self.request("/v1/records/knowledge/" + A)["record"]["content"]["summary"], "Committed first")

    def test_failed_save_keeps_input_and_can_retry(self):
        page = self.page()
        self.alpha(page)
        self.edit(page, "Retry this input", "Retain reason")
        page.route("**/v1/knowledge-edits", lambda route: route.fulfill(status=503, json={"error": {"code": "synthetic_unavailable"}}))
        page.get_by_role("button", name="提交修改", exact=True).click()
        expect(page.get_by_text("请求失败：synthetic_unavailable", exact=True)).to_be_visible()
        expect(page.get_by_label("正文摘要", exact=True)).to_have_value("Retry this input")
        expect(page.get_by_label("修改原因", exact=True)).to_have_value("Retain reason")
        expect(page.get_by_role("button", name="提交修改", exact=True)).to_be_enabled()
        page.unroute("**/v1/knowledge-edits")
        page.get_by_role("button", name="提交修改", exact=True).click()
        expect(page.get_by_text("修改已提交。", exact=False)).to_be_visible()

    def test_late_detail_cannot_replace_current_record(self):
        page = self.page()
        held = []
        page.route("**/v1/records/knowledge/" + A, lambda route: held.append(route))
        with page.expect_request("**/v1/records/knowledge/" + A):
            page.get_by_role("button", name="Alpha").click()
        page.get_by_role("button", name="Beta").click()
        expect(page.get_by_role("heading", name="Beta", exact=True)).to_be_visible()
        self.edit(page, "New record draft", "Current record")
        self.assertEqual(len(held), 1)
        with page.expect_response("**/v1/records/knowledge/" + A):
            held[0].fulfill(response=held[0].fetch())
        expect(page.get_by_label("名称", exact=True)).to_have_value("Beta")
        expect(page.get_by_label("正文摘要", exact=True)).to_have_value("New record draft")

    def test_save_result_keeps_input_typed_during_submission(self):
        page = self.page()
        self.alpha(page)
        self.edit(page, "Submitted value", "Submitted reason")
        held = []
        page.route("**/v1/knowledge-edits", lambda route: held.append(route))
        with page.expect_request("**/v1/knowledge-edits"):
            page.get_by_role("button", name="提交修改", exact=True).click()
        self.edit(page, "Typed while saving", "New reason")
        self.assertEqual(len(held), 1)
        held[0].fulfill(response=held[0].fetch())
        expect(page.get_by_text("修改已提交。", exact=False)).to_be_visible()
        page.get_by_role("button", name="读取已保存记录", exact=True).click()
        expect(page.get_by_label("正文摘要", exact=True)).to_have_value("Typed while saving")
        expect(page.get_by_label("修改原因", exact=True)).to_have_value("New reason")
        self.assertEqual(self.request("/v1/records/knowledge/" + A)["record"]["content"]["summary"], "Submitted value")

    def test_source_and_record_html_render_as_literal_text(self):
        page = self.page()
        self.alpha(page)
        page.get_by_role("button", name="codex / synthetic / 行 1–1", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("user: Synthetic explanation " + HTML, exact=True)).to_be_visible()
        self.assertIsNone(page.evaluate("window.syntheticScriptRan"))
        page.get_by_role("button", name="关闭", exact=True).click()
        expect(page.get_by_label("正文摘要", exact=True)).to_have_value(HTML)


if __name__ == "__main__":
    unittest.main()
