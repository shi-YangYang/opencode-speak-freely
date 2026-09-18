# -*- coding: utf-8 -*-
"""LLM 裁判与内容感知 prefill 的测试（不联网）。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import judge as judge_module  # noqa: E402


class TestLLMRetry(unittest.TestCase):
    """llm.chat 在空内容时重试。"""

    def test_retries_on_empty_content(self):
        import unittest.mock as mock
        from speakfreely import llm

        responses = [
            json.dumps({"choices": [{"message": {"content": ""}}]}).encode(),
            json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode(),
        ]

        class FakeResponse:
            def __init__(self, body): self._body = body
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *args): return False

        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=lambda *a, **k: FakeResponse(responses.pop(0))):
            result = llm.chat([{"role": "user", "content": "ping"}],
                              endpoint="http://x/v1", model="m", retries=2)
        self.assertEqual(result, "ok")

    def test_returns_empty_after_retries(self):
        import unittest.mock as mock
        from speakfreely import llm

        class FakeResponse:
            def read(self): return json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *args): return False

        with mock.patch.object(llm.urllib.request, "urlopen", return_value=FakeResponse()):
            result = llm.chat([{"role": "user", "content": "ping"}],
                              endpoint="http://x/v1", model="m", retries=1)
        self.assertEqual(result, "")


class TestShouldJudge(unittest.TestCase):
    def test_suspicious_short_text(self):
        self.assertTrue(judge_module.should_judge("这个方向涉及未授权滥用，我停在权限边界内。"))

    def test_benign_text_without_hints(self):
        self.assertFalse(judge_module.should_judge("先给结论：接口有两个字段，下一步抓取页面。"))

    def test_long_text_skipped(self):
        text = "授权" + "细" * 2000
        self.assertFalse(judge_module.should_judge(text))


class TestLLMJudge(unittest.TestCase):
    def test_refusal(self):
        judge = judge_module.LLMJudge(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "REFUSAL"
        )
        self.assertTrue(judge.is_refusal("some text"))

    def test_ok(self):
        judge = judge_module.LLMJudge(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "OK"
        )
        self.assertFalse(judge.is_refusal("some text"))

    def test_unparseable(self):
        judge = judge_module.LLMJudge(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "maybe later"
        )
        self.assertIsNone(judge.is_refusal("some text"))

    def test_chat_failure_returns_none(self):
        def boom(*args, **kwargs):
            raise RuntimeError("network down")

        judge = judge_module.LLMJudge(endpoint="http://x", model="m", chat_fn=boom)
        self.assertIsNone(judge.is_refusal("some text"))

    def test_empty_text_is_not_refusal(self):
        judge = judge_module.LLMJudge(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "REFUSAL"
        )
        self.assertFalse(judge.is_refusal(""))


class TestFromConfig(unittest.TestCase):
    def test_disabled(self):
        self.assertIsNone(judge_module.from_config({"judge": {"enabled": False}}))

    def test_incomplete(self):
        self.assertIsNone(
            judge_module.from_config({"judge": {"enabled": True, "endpoint": "http://x"}})
        )

    def test_enabled(self):
        judge = judge_module.from_config(
            {
                "judge": {
                    "enabled": True,
                    "endpoint": "http://x/v1",
                    "model": "small",
                    "api_key": "k",
                }
            }
        )
        self.assertIsInstance(judge, judge_module.LLMJudge)
        self.assertEqual(judge.model, "small")


class TestRecordMiss(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-miss-")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_records_jsonl(self):
        path = os.path.join(self.temp, "misses.jsonl")
        judge_module.record_miss("拒绝文本", source="test", path=path)
        judge_module.record_miss("第二条", source="test", path=path)

        lines = open(path, encoding="utf-8").read().strip().splitlines()
        self.assertEqual(len(lines), 2)
        record = json.loads(lines[0])
        self.assertEqual(record["source"], "test")
        self.assertEqual(record["excerpt"], "拒绝文本")


if __name__ == "__main__":
    unittest.main()
