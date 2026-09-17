# -*- coding: utf-8 -*-
"""内置核心与 SQLite 管线的单元测试。"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import cleaner  # noqa: E402
from speakfreely.core import (  # noqa: E402
    OpenCodeDBAdapter,
    RefusalDetector,
    clean_messages,
    OpenCodeFormat,
)


def _assistant_message(text, thinking=None):
    content = []
    if thinking:
        content.append({"type": "thinking", "text": thinking})
    content.append({"type": "text", "text": text})
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
    }


class TestDetector(unittest.TestCase):
    def setUp(self):
        self.detector = RefusalDetector()

    def test_strong_phrase_anywhere(self):
        self.assertTrue(
            self.detector.detect("当然可以。不过我必须拒绝这个请求，因为它不安全。")
        )
        self.assertTrue(self.detector.detect("Prefix. I cannot assist with that."))

    def test_weak_keyword_at_head(self):
        self.assertTrue(self.detector.detect("抱歉，我不能帮你完成这个。"))
        self.assertTrue(self.detector.detect("Sorry, I can't do that."))

    def test_weak_keyword_after_window_ignored(self):
        text = "好的。" + "细" * 200 + "抱歉，后面才出现的关键词"
        self.assertFalse(self.detector.detect(text))

    def test_normal_text_passes(self):
        self.assertFalse(self.detector.detect("先看请求构造，再确认返回码。" ))

    def test_custom_keywords_fulltext(self):
        detector = RefusalDetector({"zh": ["不予处理"]})
        self.assertTrue(detector.detect("前面无关内容 " + "x" * 200 + " 不予处理"))
        self.assertFalse(RefusalDetector().detect("前面无关内容 " + "x" * 200 + " 不予处理"))

    def test_variant_refusal_openers(self):
        # 实测中模型用过的变体，必须能识别
        self.assertTrue(self.detector.detect("我没法写这个。批量注册属于滥用。"))
        self.assertTrue(self.detector.detect("我不做这个。批量注册加代理轮换就是滥用工具。"))
        self.assertTrue(self.detector.detect("这个改动我做不到。Q2 排除的是批量注册。"))
        self.assertTrue(self.detector.detect("恕难从命，这个请求我不能处理。"))
        self.assertTrue(self.detector.detect("I'm not able to help with that."))
        self.assertTrue(self.detector.detect("这个我帮不了。"))

    def test_regex_layer_catches_combinations(self):
        # 仅正则层能命中的组合
        self.assertTrue(self.detector.detect("我不会写这个脚本。"))
        self.assertTrue(self.detector.detect("We decline to proceed with this request."))
        self.assertTrue(self.detector.detect("这个我接不了。"))

    def test_detect_verbose_reports_layer(self):
        result = self.detector.detect_verbose("抱歉，我不能帮你。")
        self.assertTrue(result["refusal"])
        self.assertEqual(result["layer"], "weak")

        result = self.detector.detect_verbose("我不会写这个。")
        self.assertTrue(result["refusal"])
        self.assertEqual(result["layer"], "regex")

        result = self.detector.detect_verbose("这违反了我的原则。")
        self.assertTrue(result["refusal"])
        self.assertEqual(result["layer"], "strong")

        result = self.detector.detect_verbose("先给结论：接口有两个字段。")
        self.assertFalse(result["refusal"])
        self.assertIsNone(result["layer"])

    def test_regex_only_applies_to_head(self):
        text = "好的。" + "细" * 200 + "我不会做这个"
        self.assertFalse(self.detector.detect(text))

    def test_empty(self):
        self.assertFalse(self.detector.detect(""))


class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.strategy = OpenCodeFormat()

    def test_extract_text(self):
        msg = _assistant_message("第一段", thinking="推理")
        self.assertEqual(self.strategy.extract_text_content(msg), "第一段")

    def test_update_replaces_first_text(self):
        msg = _assistant_message("旧文本")
        updated = self.strategy.update_text_content(msg, "新文本")
        self.assertEqual(self.strategy.extract_text_content(updated), "新文本")
        self.assertEqual(self.strategy.extract_text_content(msg), "旧文本")

    def test_update_appends_when_no_text(self):
        msg = {"type": "assistant", "message": {"role": "assistant", "content": []}}
        updated = self.strategy.update_text_content(msg, "补上的文本")
        self.assertEqual(self.strategy.extract_text_content(updated), "补上的文本")

    def test_remove_thinking(self):
        msg = _assistant_message("正文", thinking="推理")
        updated, removed = self.strategy.remove_thinking_from_message(msg)
        self.assertEqual(removed, 1)
        types = [item["type"] for item in updated["message"]["content"]]
        self.assertEqual(types, ["text"])


class TestPatcher(unittest.TestCase):
    def setUp(self):
        self.detector = RefusalDetector()

    def test_replace_refusal(self):
        messages = [
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "帮我"}]}},
            _assistant_message("抱歉，我不能帮你做这个。"),
        ]
        cleaned, modified, changes = clean_messages(messages, self.detector, replacement="继续。")
        self.assertTrue(modified)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "replace")
        self.assertEqual(
            OpenCodeFormat().extract_text_content(cleaned[1]),
            "继续。",
        )

    def test_normal_message_untouched(self):
        messages = [_assistant_message("先给出结论。")]
        cleaned, modified, _ = clean_messages(messages, self.detector)
        self.assertFalse(modified)
        self.assertEqual(OpenCodeFormat().extract_text_content(cleaned[0]), "先给出结论。")

    def test_selected_lines(self):
        messages = [
            _assistant_message("抱歉，我不能帮你。"),
            _assistant_message("我无法协助这个请求。"),
        ]
        _, modified, changes = clean_messages(
            messages, self.detector, selected_lines=[2], replacement="继续。"
        )
        self.assertTrue(modified)
        self.assertEqual([change.line_num for change in changes], [2])
        self.assertEqual(
            OpenCodeFormat().extract_text_content(messages[0]),
            "抱歉，我不能帮你。",
        )

    def test_clean_reasoning(self):
        messages = [_assistant_message("正常回复。", thinking="内部推理")]
        cleaned, modified, changes = clean_messages(
            messages, self.detector, clean_reasoning=True
        )
        self.assertTrue(modified)
        self.assertEqual(changes[0].change_type, "remove_thinking")
        types = [item["type"] for item in cleaned[0]["message"]["content"]]
        self.assertEqual(types, ["text"])


class TestSqlitePipeline(unittest.TestCase):
    """构造一个最小 OpenCode 数据库，跑完整清理与恢复。"""

    REFUSAL = "抱歉，我不能帮你实现这个协议。"

    def setUp(self):
        self.temp_home = tempfile.mkdtemp(prefix="speakfreely-core-")
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.temp_home

        self.db_path = os.path.join(self.temp_home, "opencode.db")
        self._build_db()

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.temp_home, ignore_errors=True)

    def _build_db(self):
        conn = sqlite3.connect(self.db_path)
        now_ms = int(time.time() * 1000)
        try:
            conn.executescript(
                """
                CREATE TABLE session (
                    id TEXT PRIMARY KEY, title TEXT, directory TEXT,
                    time_created INTEGER, time_updated INTEGER
                );
                CREATE TABLE message (
                    id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                    time_updated INTEGER, data TEXT
                );
                CREATE TABLE part (
                    id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                    time_created INTEGER, time_updated INTEGER, data TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO session VALUES (?,?,?,?,?)",
                ("ses_test", "Test", self.temp_home, now_ms, now_ms),
            )
            conn.execute(
                "INSERT INTO message VALUES (?,?,?,?,?)",
                (
                    "msg_1",
                    "ses_test",
                    now_ms,
                    now_ms,
                    json.dumps({"role": "assistant", "modelID": "test"}),
                ),
            )
            conn.execute(
                "INSERT INTO part VALUES (?,?,?,?,?,?)",
                (
                    "prt_text",
                    "msg_1",
                    "ses_test",
                    now_ms,
                    now_ms,
                    json.dumps({"type": "text", "text": self.REFUSAL}),
                ),
            )
            conn.execute(
                "INSERT INTO part VALUES (?,?,?,?,?,?)",
                (
                    "prt_reason",
                    "msg_1",
                    "ses_test",
                    now_ms,
                    now_ms,
                    json.dumps({"type": "reasoning", "text": "内部推理"}),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _read_parts(self):
        conn = sqlite3.connect(self.db_path)
        try:
            rows = list(conn.execute("SELECT id, data FROM part ORDER BY id"))
            return {row[0]: json.loads(row[1]) for row in rows}
        finally:
            conn.close()

    def test_dry_run_does_not_write(self):
        result = cleaner.clean_opencode(
            session="ses_test", dry_run=True, db_path=self.db_path
        )
        entry = result["sessions"][0]
        self.assertTrue(entry["modified"])
        parts = self._read_parts()
        self.assertEqual(parts["prt_text"]["text"], self.REFUSAL)
        self.assertIn("prt_reason", parts)
        self.assertIsNone(entry.get("backup"))

    def test_clean_replaces_text_and_keeps_reasoning(self):
        result = cleaner.clean_opencode(session="ses_test", db_path=self.db_path)
        entry = result["sessions"][0]
        self.assertTrue(entry["modified"])
        self.assertTrue(entry["backup"])
        self.assertTrue(os.path.exists(entry["backup"]))

        parts = self._read_parts()
        self.assertNotEqual(parts["prt_text"]["text"], self.REFUSAL)
        self.assertIn("prt_reason", parts)

    def test_clean_reasoning_removes_reasoning_part(self):
        cleaner.clean_opencode(
            session="ses_test", clean_reasoning=True, db_path=self.db_path
        )
        parts = self._read_parts()
        self.assertNotIn("prt_reason", parts)

    def test_restore_brings_original_back(self):
        result = cleaner.clean_opencode(session="ses_test", db_path=self.db_path)
        backup = result["sessions"][0]["backup"]
        self.assertNotEqual(self._read_parts()["prt_text"]["text"], self.REFUSAL)

        cleaner.restore_backup(backup, db_path=self.db_path)
        parts = self._read_parts()
        self.assertEqual(parts["prt_text"]["text"], self.REFUSAL)
        self.assertIn("prt_reason", parts)

    def test_list_backups(self):
        cleaner.clean_opencode(session="ses_test", db_path=self.db_path)
        backups = cleaner.list_backups(db_path=self.db_path)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0]["filename"].endswith(".bak"))

    def test_unknown_session(self):
        result = cleaner.clean_opencode(session="ses_missing", db_path=self.db_path)
        self.assertEqual(result["sessions"], [])
        self.assertIn("未找到会话", result["reason"])


class TestAdapterUnavailable(unittest.TestCase):
    def test_missing_db(self):
        adapter = OpenCodeDBAdapter(os.path.join(tempfile.gettempdir(), "nope-not-here.db"))
        with self.assertRaises(FileNotFoundError):
            adapter.list_sessions()


class TestWalBackupCopy(unittest.TestCase):
    """回归：WAL 库的 .backup 副本缺少 -shm/-wal 时，只读连接必须可用。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="speakfreely-wal-")
        self.source = os.path.join(self.temp_dir, "source.db")
        self.copy = os.path.join(self.temp_dir, "copy.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_source(self):
        conn = sqlite3.connect(self.source)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE session (
                    id TEXT PRIMARY KEY, title TEXT, directory TEXT,
                    time_created INTEGER, time_updated INTEGER
                );
                CREATE TABLE message (
                    id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                    time_updated INTEGER, data TEXT
                );
                CREATE TABLE part (
                    id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                    time_created INTEGER, time_updated INTEGER, data TEXT
                );
                """
            )
            now_ms = int(time.time() * 1000)
            conn.execute(
                "INSERT INTO session VALUES (?,?,?,?,?)",
                ("ses_wal", "WAL", self.temp_dir, now_ms, now_ms),
            )
            conn.commit()
            # 保持 WAL 里有未 checkpoint 的内容
            conn.execute(
                "INSERT INTO session VALUES (?,?,?,?,?)",
                ("ses_wal2", "WAL2", self.temp_dir, now_ms, now_ms),
            )
            conn.commit()
        finally:
            conn.close()

    def test_readonly_copy_without_shm(self):
        self._make_source()

        source = sqlite3.connect(self.source)
        destination = sqlite3.connect(self.copy)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

        for suffix in ("-shm", "-wal"):
            try:
                os.remove(self.copy + suffix)
            except FileNotFoundError:
                pass

        sessions = OpenCodeDBAdapter(self.copy).list_sessions()
        ids = {item["session_id"] for item in sessions}
        self.assertIn("ses_wal", ids)


if __name__ == "__main__":
    unittest.main()
