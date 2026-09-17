# -*- coding: utf-8 -*-
"""speakfreely 冒烟测试（stdlib unittest）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakfreely import installer, paths, project, workflow  # noqa: E402


class TempHomeCase(unittest.TestCase):
    def setUp(self):
        self.temp_home = tempfile.mkdtemp(prefix="speakfreely-test-")
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.temp_home

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.temp_home, ignore_errors=True)


class TestInstallGlobal(TempHomeCase):
    def test_install_creates_file(self):
        result = installer.install_global()
        self.assertEqual(result["status"], "installed")
        self.assertTrue(os.path.exists(result["target"]))
        template = paths.load_text(
            os.path.join(paths.prompts_dir(), "opencode-global.md")
        )
        self.assertEqual(paths.load_text(result["target"]), template)

    def test_install_second_run_unchanged(self):
        installer.install_global()
        result = installer.install_global()
        self.assertEqual(result["status"], "unchanged")
        self.assertIsNone(result["backup"])

    def test_install_backs_up_existing(self):
        target = paths.global_prompt_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("USER OWNED\n")

        result = installer.install_global()
        self.assertEqual(result["status"], "updated")
        self.assertIsNotNone(result["backup"])
        self.assertEqual(paths.load_text(result["backup"]), "USER OWNED\n")

    def test_uninstall_removes_matching_file(self):
        installer.install_global()
        result = installer.uninstall_global()
        self.assertEqual(result["status"], "removed")
        self.assertFalse(os.path.exists(paths.global_prompt_path()))

    def test_uninstall_keeps_modified_file(self):
        target = paths.global_prompt_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("USER OWNED\n")

        result = installer.uninstall_global()
        self.assertEqual(result["status"], "kept")
        self.assertTrue(os.path.exists(target))


class TestWorkspace(TempHomeCase):
    def test_install_workspace(self):
        result = installer.install_workspace()
        self.assertEqual(result["status"], "installed")
        self.assertTrue(os.path.exists(result["target"]))
        self.assertTrue(os.path.exists(result["config"]))
        content = paths.load_text(result["target"])
        self.assertIn("managed-by: codex-session-patcher", content)

    def test_uninstall_workspace_removes_when_matching(self):
        installer.install_workspace()
        result = installer.uninstall_workspace()
        self.assertEqual(result["status"], "removed")
        self.assertFalse(os.path.exists(paths.workspace_prompt_path()))


class TestInitProject(TempHomeCase):
    def test_init_creates_agents_and_dirs(self):
        target_dir = os.path.join(self.temp_home, "target-project")
        result = project.init_project(
            target_dir,
            name="Demo",
            target="https://example.test",
            authorization="Unit test fixture",
        )
        self.assertEqual(result["status"], "created")
        content = paths.load_text(result["target"])
        self.assertIn("# Demo", content)
        self.assertIn("https://example.test", content)
        self.assertIn("Unit test fixture", content)
        self.assertNotIn("{{", content)
        self.assertTrue(os.path.isdir(os.path.join(target_dir, "tools")))
        self.assertTrue(os.path.isdir(os.path.join(target_dir, "evidence")))

    def test_init_refuses_existing_without_force(self):
        target_dir = os.path.join(self.temp_home, "target-project")
        os.makedirs(target_dir)
        agents = os.path.join(target_dir, "AGENTS.md")
        with open(agents, "w", encoding="utf-8") as stream:
            stream.write("USER OWNED\n")

        result = project.init_project(target_dir, target="t")
        self.assertEqual(result["status"], "exists")
        self.assertEqual(paths.load_text(agents), "USER OWNED\n")

        result = project.init_project(target_dir, target="t", force=True)
        self.assertEqual(result["status"], "created")
        self.assertIsNotNone(result["backup"])
        self.assertNotEqual(paths.load_text(agents), "USER OWNED\n")

    def test_init_reports_missing_fields(self):
        target_dir = os.path.join(self.temp_home, "no-fields")
        result = project.init_project(target_dir)
        self.assertEqual(sorted(result["missing"]), ["authorization", "target"])


class TestWorkflow(unittest.TestCase):
    def test_first_stage(self):
        stage = workflow.next_stage(None)
        self.assertIsNotNone(stage)
        self.assertEqual(stage["key"], "recon")

    def test_chain(self):
        keys = []
        stage = workflow.next_stage(None)
        while stage:
            keys.append(stage["key"])
            stage = workflow.next_stage(stage["key"])
        self.assertEqual(keys, ["recon", "enum", "analyze", "exploit", "evidence"])

    def test_unknown_stage(self):
        self.assertIsNone(workflow.get_stage("nope"))
        self.assertIsNone(workflow.next_stage("nope"))


if __name__ == "__main__":
    unittest.main()
