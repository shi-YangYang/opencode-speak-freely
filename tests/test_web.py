# -*- coding: utf-8 -*-
"""Web UI 测试：在临时 HOME/DB 上跑真实 HTTP 请求（不联网、不调模型）。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import web  # noqa: E402
from test_auto import build_db  # noqa: E402


class WebCase(unittest.TestCase):
    def setUp(self):
        self.temp_home = tempfile.mkdtemp(prefix="speakfreely-web-")
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.temp_home

        self.db_path = os.path.join(self.temp_home, "opencode.db")
        self.project = os.path.join(self.temp_home, "project")
        os.makedirs(self.project, exist_ok=True)
        build_db(self.db_path, self.project)

        self.server = web.create_server(port=0, db_path=self.db_path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.server.server_address[1])

    def tearDown(self):
        for event in web.WATCH_STOPS.values():
            event.set()
        web.WATCH_STOPS.clear()
        time.sleep(0.1)
        self.server.shutdown()
        self.server.server_close()
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.temp_home, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def wait_job(self, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, job = self.get("/api/job?id=" + job_id)
            if job["status"] != "running":
                return job
            time.sleep(0.2)
        raise AssertionError("job 未在超时内完成")


class TestModelsFallback(unittest.TestCase):
    """CLI 拿不到时回退到配置文件解析。"""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="speakfreely-models-")
        self.config = os.path.join(self.temp, "opencode.jsonc")
        with open(self.config, "w", encoding="utf-8") as stream:
            stream.write(
                """
                {
                  "provider": {
                    "tokenrhythm": {
                      "options": { "baseURL": "https://example.test/v1" },
                      "models": { "glm-5.2": {}, "kimi-k2.6": {} },
                    }
                  }
                }
                """
            )

    def tearDown(self):
        web._MODELS_CACHE["models"] = []
        web._MODELS_CACHE["time"] = 0.0
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_fallback_to_config(self):
        web._MODELS_CACHE["models"] = []
        original = web._models_from_cli
        web._models_from_cli = lambda: []
        try:
            models = web.list_models(path=self.config)
        finally:
            web._models_from_cli = original
        self.assertIn("tokenrhythm/glm-5.2", models)
        self.assertIn("tokenrhythm/kimi-k2.6", models)


class TestJsoncParser(unittest.TestCase):
    def test_keeps_urls_comments_and_trailing_commas(self):
        raw = """
        {
          // 默认模型
          "model": "tokenrhythm/glm-5.2",
          "provider": {
            "tokenrhythm": {
              "options": { "baseURL": "https://tokenrhythm.studio/v1" },
              "models": {
                "glm-5.2": { "name": "GLM-5.2" }, /* 内置 */
              },
            },
          },
        }
        """
        data = web._parse_jsonc(raw)
        self.assertIsInstance(data, dict)
        self.assertEqual(
            data["provider"]["tokenrhythm"]["options"]["baseURL"],
            "https://tokenrhythm.studio/v1",
        )
        self.assertIn("glm-5.2", data["provider"]["tokenrhythm"]["models"])

    def test_invalid_returns_none(self):
        self.assertIsNone(web._parse_jsonc("{not json"))


class TestApi(WebCase):
    def test_index_served(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("speakfreely", body)

    def test_projects_and_sessions(self):
        _, projects = self.get("/api/projects")
        directories = [item["directory"] for item in projects]
        self.assertIn(os.path.realpath(self.project), [os.path.realpath(d) for d in directories])

        _, sessions = self.get("/api/sessions?project=" + urllib.request.quote(self.project))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "ses_test")

    def test_session_preview_flags_refusal(self):
        _, data = self.get("/api/session?id=ses_test")
        self.assertGreaterEqual(data["refusals"], 1)
        self.assertTrue(any(message["refusal"] for message in data["messages"]))

    def test_clean_dry_run_then_real(self):
        _, dry = self.post("/api/clean", {"session": "ses_test", "dry_run": True})
        self.assertTrue(dry["sessions"][0]["modified"])

        _, real = self.post("/api/clean", {"session": "ses_test"})
        self.assertTrue(real["sessions"][0]["modified"])
        self.assertTrue(real["sessions"][0]["backup"])

        _, data = self.get("/api/session?id=ses_test")
        self.assertEqual(data["refusals"], 0)

    def test_run_seed_job(self):
        _, created = self.post(
            "/api/run",
            {
                "mode": "seed",
                "project": self.project,
                "goal": "梳理注册接口并整理证据",
            },
        )
        job = self.wait_job(created["job"])
        self.assertEqual(job["status"], "done")
        self.assertTrue(
            os.path.exists(os.path.join(self.project, "tools", "web_probe.py"))
        )

    def test_run_requires_goal(self):
        request = urllib.request.Request(
            self.base + "/api/run",
            data=json.dumps({"mode": "seed", "project": self.project}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            created = json.loads(response.read().decode())
        job = self.wait_job(created["job"])
        self.assertEqual(job["status"], "error")
        self.assertIn("目标不能为空", job["result"]["error"])

    def test_watch_start_and_stop(self):
        _, started = self.post("/api/watch", {"project": self.project, "action": "start"})
        self.assertEqual(started["status"], "started")

        _, again = self.post("/api/watch", {"project": self.project, "action": "start"})
        self.assertEqual(again["status"], "already-running")

        _, status = self.post("/api/watch", {"project": self.project, "action": "stop"})
        self.assertEqual(status["status"], "stopping")

    def test_preview_has_index_and_message_returns_full_text(self):
        long_text = "抱歉，我不能帮你。" + "细节。" * 800  # > 1500 字符
        conn = __import__("sqlite3").connect(self.db_path)
        try:
            conn.execute(
                "UPDATE part SET data = ? WHERE id = 'prt_text'",
                (json.dumps({"type": "text", "text": long_text}),),
            )
            conn.commit()
        finally:
            conn.close()

        _, preview = self.get("/api/session?id=ses_test")
        last = preview["messages"][-1]
        self.assertIn("index", last)
        self.assertLessEqual(len(last["text"]), 1500)

        _, full = self.get("/api/message?id=ses_test&index={}".format(last["index"]))
        self.assertEqual(full["role"], "assistant")
        self.assertTrue(full["refusal"])
        self.assertEqual(len(full["text"]), len(long_text))

    def test_non_text_message_is_hidden(self):
        conn = __import__("sqlite3").connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO message VALUES (?,?,?,?,?)",
                ("msg_tool", "ses_test", 1, 1, json.dumps({"role": "assistant"})),
            )
            conn.execute(
                "INSERT INTO part VALUES (?,?,?,?,?,?)",
                (
                    "prt_tool", "msg_tool", "ses_test", 1, 1,
                    json.dumps({"type": "tool", "tool": "bash"}),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        _, preview = self.get("/api/session?id=ses_test")
        indices = [m["index"] for m in preview["messages"]]
        self.assertNotIn(0, indices)          # 新插入的无文本消息（绝对索引 0）不展示
        self.assertEqual(preview["total"], 2)  # 两条都在库里
        self.assertEqual(preview["shown"], 1)  # 只展示有文本的那条

    def test_message_out_of_range(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/message?id=ses_test&index=999")
        self.assertEqual(ctx.exception.code, 500)

    def _add_refusal(self, message_id, part_id, text, timestamp=2):
        conn = __import__("sqlite3").connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO message VALUES (?,?,?,?,?)",
                (message_id, "ses_test", timestamp, timestamp, json.dumps({"role": "assistant"})),
            )
            conn.execute(
                "INSERT INTO part VALUES (?,?,?,?,?,?)",
                (part_id, message_id, "ses_test", timestamp, timestamp,
                 json.dumps({"type": "text", "text": text})),
            )
            conn.commit()
        finally:
            conn.close()

    def test_refusals_session_endpoint(self):
        _, data = self.get("/api/refusals?session=ses_test")
        self.assertEqual(len(data["refusals"]), 1)
        self.assertEqual(data["refusals"][0]["index"], 0)

    def test_refusals_project_scan(self):
        _, data = self.get("/api/refusals?project=" + urllib.request.quote(self.project))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "ses_test")
        self.assertEqual(data[0]["count"], 1)

    def test_selective_clean_only_chosen(self):
        self._add_refusal("msg_2", "prt_2", "抱歉，我不能帮你做这个。", timestamp=2)

        _, data = self.get("/api/refusals?session=ses_test")
        lines = [item["line"] for item in data["refusals"]]
        self.assertEqual(len(lines), 2)

        _, result = self.post(
            "/api/clean",
            {"session": "ses_test", "selected": [lines[1]]},
        )
        entry = result["sessions"][0]
        self.assertTrue(entry["modified"])
        self.assertEqual(len(entry["details"]), 1)

        conn = __import__("sqlite3").connect(self.db_path)
        try:
            rows = {row[0]: json.loads(row[1])["text"] for row in
                    conn.execute("SELECT id, data FROM part WHERE id IN ('prt_text','prt_2')")}
        finally:
            conn.close()
        self.assertIn("抱歉，我不能帮你做这个。", rows["prt_2"])       # 未选中的保持原样
        self.assertNotIn("抱歉，我不能帮你实现这个协议。", rows["prt_text"])  # 选中的被替换

    def test_backups_and_restore(self):
        _, backups = self.get("/api/backups")
        self.assertEqual(backups, [])

        self.post("/api/clean", {"session": "ses_test"})
        _, backups = self.get("/api/backups")
        self.assertEqual(len(backups), 1)

        _, restored = self.post("/api/restore", {"backup": backups[0]["path"]})
        self.assertTrue(restored["ok"])

        _, data = self.get("/api/session?id=ses_test")
        self.assertEqual(data["refusals"], 1)  # 原文回来了

    def test_stages_endpoint(self):
        _, stages = self.get("/api/stages")
        self.assertEqual(
            [stage["key"] for stage in stages],
            ["recon", "enum", "analyze", "exploit", "evidence"],
        )
        self.assertTrue(all(stage["name"] for stage in stages))
        self.assertTrue(all(stage["description"] for stage in stages))

    def test_unknown_api(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
