# -*- coding: utf-8 -*-
"""预热会话（many-shot）测试。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import auto as auto_module  # noqa: E402
from speakfreely import prime as prime_module  # noqa: E402
from speakfreely.core import OpenCodeDBAdapter  # noqa: E402
from test_auto import build_db  # noqa: E402


class TestPrime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-prime-")
        self.db_path = os.path.join(self.temp, "opencode.db")
        self.project = os.path.join(self.temp, "project")
        os.makedirs(self.project, exist_ok=True)
        build_db(self.db_path, self.project)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_creates_session_with_examples(self):
        result = prime_module.create_primed_session(
            self.project, examples=2, db_path=self.db_path
        )
        self.assertTrue(result["session_id"].startswith("ses_prime"))
        self.assertEqual(result["messages"], 4)

        messages = OpenCodeDBAdapter(self.db_path).load_session_messages(
            result["session_id"]
        )
        self.assertEqual(len(messages), 4)
        self.assertEqual([m["type"] for m in messages], ["user", "assistant", "user", "assistant"])

    def test_ask_appended_last(self):
        result = prime_module.create_primed_session(
            self.project, examples=1, ask="真实的请求内容", db_path=self.db_path
        )
        messages = OpenCodeDBAdapter(self.db_path).load_session_messages(
            result["session_id"]
        )
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[-1]["type"], "user")
        text = messages[-1]["message"]["content"][0]["text"]
        self.assertEqual(text, "真实的请求内容")

    def test_directory_recorded(self):
        result = prime_module.create_primed_session(
            self.project, examples=1, db_path=self.db_path
        )
        sessions = OpenCodeDBAdapter(self.db_path).list_sessions()
        match = [s for s in sessions if s["session_id"] == result["session_id"]]
        self.assertEqual(len(match), 1)
        self.assertEqual(
            os.path.realpath(match[0]["directory"]), os.path.realpath(self.project)
        )

    def test_examples_clamped(self):
        result = prime_module.create_primed_session(
            self.project, examples=99, db_path=self.db_path
        )
        self.assertEqual(result["messages"], len(prime_module.EXAMPLES) * 2)


class TestAutoPrime(unittest.TestCase):
    def setUp(self):
        self.temp_home = tempfile.mkdtemp(prefix="speakfreely-prime-home-")
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.temp_home
        self.db_path = os.path.join(self.temp_home, "opencode.db")
        self.project = os.path.join(self.temp_home, "project")
        os.makedirs(self.project, exist_ok=True)
        build_db(self.db_path, self.project)

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.temp_home, ignore_errors=True)

    def test_auto_uses_primed_session(self):
        seen_sessions = []

        def fake_runner(prompt, session=None, **kwargs):
            seen_sessions.append(session)
            return {"session_id": session, "text": "完成。", "cost": 0.0}

        result = auto_module.run_auto(
            project_dir=self.project,
            stages=["recon"],
            runner=fake_runner,
            clean_fn=lambda *args, **kwargs: {"sessions": [{}]},
            db_path=self.db_path,
            prime=2,
            judge=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(seen_sessions[0].startswith("ses_prime"))
        self.assertEqual(result["session_id"], seen_sessions[0])


if __name__ == "__main__":
    unittest.main()
