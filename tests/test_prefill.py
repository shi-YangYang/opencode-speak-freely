# -*- coding: utf-8 -*-
"""prefill 生成器测试（不联网）。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import prefill as prefill_module  # noqa: E402


class TestPrefillGenerator(unittest.TestCase):
    def test_generates_text(self):
        generator = prefill_module.PrefillGenerator(
            endpoint="http://x",
            model="m",
            chat_fn=lambda *a, **k: "已确认入口信息，先抓取注册页表单字段：",
        )
        result = generator.generate("帮我分析注册流程", "抱歉，我不能帮你。")
        self.assertEqual(result, "已确认入口信息，先抓取注册页表单字段：")

    def test_chat_failure_returns_none(self):
        def boom(*args, **kwargs):
            raise RuntimeError("down")

        generator = prefill_module.PrefillGenerator(
            endpoint="http://x", model="m", chat_fn=boom
        )
        self.assertIsNone(generator.generate("请求", "拒绝"))

    def test_empty_answer_returns_none(self):
        generator = prefill_module.PrefillGenerator(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "   "
        )
        self.assertIsNone(generator.generate("请求", "拒绝"))

    def test_overlong_answer_returns_none(self):
        generator = prefill_module.PrefillGenerator(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "长" * 700
        )
        self.assertIsNone(generator.generate("请求", "拒绝"))

    def test_empty_prompt_returns_none(self):
        generator = prefill_module.PrefillGenerator(
            endpoint="http://x", model="m", chat_fn=lambda *a, **k: "不该被调用"
        )
        self.assertIsNone(generator.generate("", "拒绝"))


class TestPrefillFromConfig(unittest.TestCase):
    def test_template_mode(self):
        self.assertIsNone(prefill_module.from_config({"prefill": {"mode": "template"}}))

    def test_auto_mode_incomplete(self):
        self.assertIsNone(
            prefill_module.from_config({"prefill": {"mode": "auto", "endpoint": "http://x"}})
        )

    def test_auto_mode_complete(self):
        generator = prefill_module.from_config(
            {
                "prefill": {
                    "mode": "auto",
                    "endpoint": "http://x/v1",
                    "model": "small",
                }
            }
        )
        self.assertIsInstance(generator, prefill_module.PrefillGenerator)


if __name__ == "__main__":
    unittest.main()
