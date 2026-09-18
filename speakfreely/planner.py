# -*- coding: utf-8 -*-
"""LLM 规划器：根据项目结构与大白话目标，决定半成品文件的位置、语言与步骤。

面向 vibe coding：用户只说需求，由模型决定"从哪个文件开始、写成什么样"。
失败时返回 None，调用方回退到模板默认行为。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from . import llm

PLANNER_PROMPT = """You are a coding-workflow planner for an autonomous coding agent.

Given a user's goal (plain language) and the repository layout, choose the single best
file to start implementing in, and outline concrete TODO steps.

Rules:
1. "path" MUST be relative, inside the repository, using forward slashes.
2. Prefer an existing conventional directory (src/, app/, webui/, lib/, docs/, tests/).
   If nothing fits, choose a sensible new path.
3. Choose the language from the repo stack; the file extension must match it.
4. 3-6 steps, each a concrete action someone can start with.
5. Propose 1-4 function/class names to stub where applicable.

Return ONLY JSON:
{"path": "...", "language": "...", "steps": ["..."], "functions": ["..."]}
"""

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".go", ".rs",
    ".sh", ".md", ".yml", ".yaml", ".toml", ".json",
}

STACK_MARKERS = (
    "pyproject.toml", "setup.py", "requirements.txt", "package.json",
    "go.mod", "Cargo.toml", "Gemfile", "pom.xml", "build.gradle",
)


def gather_context(project_dir: str, max_entries: int = 60) -> str:
    project_dir = os.path.realpath(os.path.expanduser(project_dir))
    entries = []
    try:
        for name in sorted(os.listdir(project_dir)):
            if name.startswith("."):
                continue
            full = os.path.join(project_dir, name)
            entries.append(name + ("/" if os.path.isdir(full) else ""))
    except OSError:
        entries = []
    markers = [name for name in STACK_MARKERS if os.path.exists(os.path.join(project_dir, name))]
    return "Repo root: {}\nTop level: {}\nStack markers: {}".format(
        project_dir,
        ", ".join(entries[:max_entries]) or "(empty)",
        ", ".join(markers) or "(none)",
    )


def parse_response(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出里提取并校验规划 JSON。"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    path = str(data.get("path") or "").strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        return None
    extension = os.path.splitext(path)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return None

    steps = [str(step).strip() for step in (data.get("steps") or []) if str(step).strip()]
    functions = [str(fn).strip() for fn in (data.get("functions") or []) if str(fn).strip()]
    if not steps:
        return None
    return {
        "path": path,
        "language": str(data.get("language") or extension.lstrip(".")).strip(),
        "steps": steps[:6],
        "functions": functions[:4],
    }


class ScaffoldPlanner:
    """让模型决定半成品的位置与内容。"""

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: Optional[str] = None,
        timeout: float = 30,
        chat_fn=None,
    ):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._chat = chat_fn or llm.chat

    def plan(self, goal: str, project_dir: str) -> Optional[Dict[str, Any]]:
        if not goal:
            return None
        try:
            answer = self._chat(
                [
                    {"role": "system", "content": PLANNER_PROMPT},
                    {
                        "role": "user",
                        "content": "Goal: {}\n\n{}\n\nReturn the JSON plan now.".format(
                            goal.strip()[:1000], gather_context(project_dir)
                        ),
                    },
                ],
                endpoint=self.endpoint,
                api_key=self.api_key,
                model=self.model,
                timeout=self.timeout,
                max_tokens=500,
                temperature=0.2,
            )
        except Exception:  # noqa: BLE001 - 规划失败必须不影响主流程
            return None
        return parse_response(answer or "")


def from_config(config: Dict[str, Any]) -> Optional[ScaffoldPlanner]:
    section = config.get("planner") or {}
    if not section.get("enabled"):
        return None
    endpoint = section.get("endpoint") or ""
    model = section.get("model") or ""
    if not endpoint or not model:
        return None
    return ScaffoldPlanner(
        endpoint=endpoint,
        model=model,
        api_key=section.get("api_key") or None,
        timeout=float(section.get("timeout") or 30),
    )
