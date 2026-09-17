# -*- coding: utf-8 -*-
"""自动化循环与监视模式的测试（不联网、不依赖真实 CLI）。"""
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

from speakfreely import auto as auto_module  # noqa: E402
from speakfreely import watch as watch_module  # noqa: E402
from speakfreely.runner import parse_events  # noqa: E402


REFUSAL = "抱歉，我不能帮你实现这个协议。"


def build_db(db_path: str, directory: str, session_id: str = "ses_test"):
    conn = sqlite3.connect(db_path)
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
            (session_id, "auto-test", directory, now_ms, now_ms),
        )
        conn.execute(
            "INSERT INTO message VALUES (?,?,?,?,?)",
            ("msg_1", session_id, now_ms, now_ms, json.dumps({"role": "assistant"})),
        )
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?,?)",
            (
                "prt_text",
                "msg_1",
                session_id,
                now_ms,
                now_ms,
                json.dumps({"type": "text", "text": REFUSAL}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def read_text(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT data FROM part WHERE id = 'prt_text'"
        ).fetchone()
        return json.loads(row[0])["text"]
    finally:
        conn.close()


class TestParseEvents(unittest.TestCase):
    def test_parses_session_text_and_cost(self):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "step_start",
                        "sessionID": "ses_abc",
                        "part": {"type": "step-start"},
                    }
                ),
                json.dumps(
                    {
                        "type": "text",
                        "sessionID": "ses_abc",
                        "part": {"id": "prt_1", "type": "text", "text": "hello"},
                    }
                ),
                json.dumps(
                    {
                        "type": "tool",
                        "sessionID": "ses_abc",
                        "part": {"id": "prt_2", "type": "tool"},
                    }
                ),
                json.dumps(
                    {
                        "type": "step_finish",
                        "sessionID": "ses_abc",
                        "part": {"type": "step-finish", "cost": 0.02},
                    }
                ),
            ]
        )
        parsed = parse_events(stdout)
        self.assertEqual(parsed["session_id"], "ses_abc")
        self.assertEqual(parsed["text"], "hello")
        self.assertAlmostEqual(parsed["cost"], 0.02)
        self.assertEqual(parsed["tool_calls"], 1)

    def test_last_update_of_same_part_wins(self):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "text",
                        "sessionID": "ses_abc",
                        "part": {"id": "prt_1", "type": "text", "text": "he"},
                    }
                ),
                json.dumps(
                    {
                        "type": "text",
                        "sessionID": "ses_abc",
                        "part": {"id": "prt_1", "type": "text", "text": "hello"},
                    }
                ),
            ]
        )
        self.assertEqual(parse_events(stdout)["text"], "hello")

    def test_garbage_lines_ignored(self):
        parsed = parse_events("not json\n[]\n{bad}\n")
        self.assertIsNone(parsed["session_id"])
        self.assertEqual(parsed["text"], "")


class TestAutoLoop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-auto-")
        self.db_path = os.path.join(self.temp, "opencode.db")
        self.project = os.path.join(self.temp, "project")
        os.makedirs(self.project, exist_ok=True)
        build_db(self.db_path, self.project)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_refusal_then_success(self):
        calls = []
        responses = [
            {"session_id": "ses_test", "text": REFUSAL, "cost": 0.01},
            {"session_id": "ses_test", "text": "已经抓到入口信息并写入 evidence/。", "cost": 0.02},
        ]

        def fake_runner(prompt, directory=None, model=None, session=None, timeout=None):
            calls.append({"prompt": prompt, "model": model, "session": session})
            return responses.pop(0)

        cleaned = []

        def fake_clean(session_id, replacement, db_path):
            cleaned.append({"session": session_id, "replacement": replacement})
            return {"sessions": [{"backup": "/tmp/fake.bak", "modified": True}]}

        result = auto_module.run_auto(
            project_dir=self.project,
            stages=["recon"],
            runner=fake_runner,
            clean_fn=fake_clean,
            db_path=self.db_path,
            max_attempts=3,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["sends"], 2)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["session"], "ses_test")
        self.assertEqual(cleaned[0]["replacement"], "继续，先把入口信息整理清楚：目标页面、接口路径、请求方法、返回状态。")
        self.assertEqual(calls[0]["prompt"].endswith("只做记录，不做其他操作。"), True)
        self.assertEqual(calls[1]["prompt"], "继续")
        self.assertEqual(calls[1]["session"], "ses_test")

    def test_gives_up_after_max_attempts(self):
        def fake_runner(prompt, **kwargs):
            return {"session_id": "ses_test", "text": REFUSAL, "cost": 0.0}

        result = auto_module.run_auto(
            project_dir=self.project,
            stages=["recon"],
            runner=fake_runner,
            clean_fn=lambda *args, **kwargs: {"sessions": [{}]},
            db_path=self.db_path,
            max_attempts=2,
        )

        self.assertFalse(result["ok"])
        self.assertIn("连续被拒", result["reason"])
        self.assertEqual(result["sends"], 2)

    def test_model_rotation(self):
        seen_models = []

        def fake_runner(prompt, model=None, **kwargs):
            seen_models.append(model)
            return {"session_id": "ses_test", "text": REFUSAL, "cost": 0.0}

        auto_module.run_auto(
            project_dir=self.project,
            stages=["recon"],
            models=["a/one", "b/two"],
            runner=fake_runner,
            clean_fn=lambda *args, **kwargs: {"sessions": [{}]},
            db_path=self.db_path,
            max_attempts=3,
        )

        self.assertEqual(seen_models, ["a/one", "b/two", "a/one"])

    def test_dry_run_does_not_send(self):
        def fake_runner(*args, **kwargs):
            raise AssertionError("dry-run 不应发送")

        result = auto_module.run_auto(
            project_dir=self.project,
            stages=["recon", "enum"],
            runner=fake_runner,
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["plan"]["stages"], ["recon", "enum"])

    def test_goal_injected_into_first_prompt(self):
        prompts = []

        def fake_runner(prompt, **kwargs):
            prompts.append(prompt)
            return {"session_id": "ses_test", "text": "ok", "cost": 0.0}

        auto_module.run_auto(
            project_dir=self.project,
            goal="梳理注册流程",
            stages=["recon"],
            runner=fake_runner,
        )
        self.assertTrue(prompts[0].startswith("目标：梳理注册流程"))


class TestWatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-watch-")
        self.db_path = os.path.join(self.temp, "opencode.db")
        self.project = os.path.join(self.temp, "project")
        os.makedirs(self.project, exist_ok=True)
        build_db(self.db_path, self.project)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_once_cleans_refusal(self):
        result = watch_module.watch(
            once=True, settle_seconds=0, db_path=self.db_path
        )
        self.assertEqual(len(result["cleaned"]), 1)
        self.assertNotEqual(read_text(self.db_path), REFUSAL)

    def test_second_scan_is_noop(self):
        watch_module.watch(once=True, settle_seconds=0, db_path=self.db_path)
        result = watch_module.watch(once=True, settle_seconds=0, db_path=self.db_path)
        self.assertEqual(result["cleaned"], [])

    def test_project_filter(self):
        result = watch_module.watch(
            once=True,
            settle_seconds=0,
            db_path=self.db_path,
            project_dir=os.path.join(self.temp, "other"),
        )
        self.assertEqual(result["cleaned"], [])
        self.assertEqual(read_text(self.db_path), REFUSAL)

    def test_dry_run_does_not_write(self):
        result = watch_module.watch(
            once=True, settle_seconds=0, dry_run=True, db_path=self.db_path
        )
        self.assertEqual(len(result["cleaned"]), 1)
        self.assertEqual(read_text(self.db_path), REFUSAL)


if __name__ == "__main__":
    unittest.main()
