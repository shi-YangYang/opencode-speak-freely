# -*- coding: utf-8 -*-
"""尝试日志与统计测试。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import attempts as attempts_module  # noqa: E402


class TestAttempts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-attempts-")
        self.path = os.path.join(self.temp, "attempts.jsonl")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_log_and_load(self):
        attempts_module.log_attempt(
            {"model": "a/one", "stage": "recon", "refused": True, "cost": 0.1},
            path=self.path,
        )
        attempts_module.log_attempt(
            {"model": "a/one", "stage": "recon", "refused": False, "cost": 0.2},
            path=self.path,
        )
        attempts_module.log_attempt(
            {"model": "b/two", "stage": "enum", "refused": True, "cost": 0.3},
            path=self.path,
        )

        records = attempts_module.load_attempts(path=self.path)
        self.assertEqual(len(records), 3)
        self.assertIn("ts", records[0])

    def test_summarize_aggregates(self):
        attempts_module.log_attempt(
            {"model": "a/one", "stage": "recon", "refused": True, "cost": 0.1},
            path=self.path,
        )
        attempts_module.log_attempt(
            {"model": "a/one", "stage": "recon", "refused": False, "cost": 0.2},
            path=self.path,
        )
        attempts_module.log_attempt(
            {"model": "b/two", "stage": "enum", "refused": True, "cost": 0.3},
            path=self.path,
        )

        summary = attempts_module.summarize(path=self.path)
        self.assertEqual(summary["total"]["sends"], 3)
        self.assertEqual(summary["total"]["refusals"], 2)
        self.assertAlmostEqual(summary["total"]["cost"], 0.6)

        self.assertEqual(summary["models"]["a/one"]["sends"], 2)
        self.assertEqual(summary["models"]["a/one"]["refusals"], 1)
        self.assertEqual(summary["models"]["a/one"]["refusal_rate"], 0.5)
        self.assertEqual(summary["models"]["b/two"]["refusal_rate"], 1.0)
        self.assertEqual(summary["stages"]["recon"]["sends"], 2)

    def test_days_filter(self):
        path = self.path
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps({"ts": "2020-01-01T00:00:00", "model": "a", "refused": False})
                + "\n"
            )
        attempts_module.log_attempt({"model": "b", "refused": False}, path=path)

        self.assertEqual(len(attempts_module.load_attempts(path=path, days=1)), 1)
        self.assertEqual(len(attempts_module.load_attempts(path=path)), 2)

    def test_missing_file(self):
        summary = attempts_module.summarize(path=os.path.join(self.temp, "none.jsonl"))
        self.assertEqual(summary["total"]["sends"], 0)
        self.assertEqual(summary["models"], {})


if __name__ == "__main__":
    unittest.main()
