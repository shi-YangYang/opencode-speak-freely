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
        self.last_raw = ""
        self.last_refused = False

    def plan(
        self, goal: str, project_dir: str, prefer: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
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
                max_tokens=3000,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 - 规划失败必须不影响主流程
            self.last_raw = "调用失败: {}".format(exc)
            self.last_refused = False
            return None

        self.last_raw = answer or ""
        from .core import RefusalDetector

        self.last_refused = bool(self.last_raw) and RefusalDetector().detect(self.last_raw)
        return parse_response(self.last_raw)


STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "with", "in", "on", "by",
    "from", "at", "as", "into", "via", "using", "use", "make", "build", "create",
    "write", "add", "implement", "fix", "update", "refactor", "support", "please",
    "script", "tool", "code", "project", "task", "help", "want", "need", "this",
    "that", "some", "new", "based",
}


def _goal_keywords(goal: str, limit: int = 3) -> List[str]:
    """从目标里提取可做文件名的英文标识符（确定性规则，不调用模型）。"""
    picked: List[str] = []
    for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", goal or ""):
        lowered = token.lower()
        if lowered in STOPWORDS or len(lowered) < 2 or lowered.isdigit():
            continue
        if lowered not in picked:
            picked.append(lowered)
        if len(picked) >= limit:
            break
    return picked


class LocalPlanner:
    """本地规则规划：按目标关键词挑模板与文件名，不调用任何模型。"""

    def __init__(self) -> None:
        self.last_raw = "(本地规则，未调用模型)"
        self.last_refused = False

    def plan(
        self, goal: str, project_dir: str, prefer: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        from . import seed as seed_module

        template = prefer if prefer in seed_module.TEMPLATES else seed_module.pick_template(goal)
        fallback_name = seed_module.DEFAULT_NAMES.get(template, template)
        keywords = _goal_keywords(goal)
        name = seed_module._slugify("_".join(keywords), fallback_name) if keywords else fallback_name
        if template == "plan":
            return {
                "path": "docs/{}.md".format(name),
                "language": "markdown",
                "template": template,
                "steps": [],
                "functions": [],
            }
        return {
            "path": "tools/{}.py".format(name),
            "language": "python",
            "template": template,
            "steps": [],
            "functions": [],
        }


def from_config(config: Dict[str, Any]) -> Optional[Any]:
    """构造规划器：默认本地规则；planner.mode=llm 时才用模型规划。"""
    from . import config as config_module

    section = config.get("planner") or {}
    if not section.get("enabled"):
        return None

    mode = str(section.get("mode") or "local").lower()
    if mode == "llm":
        options = config_module.llm_settings(config, section)
        endpoint = options.get("endpoint") or ""
        model = options.get("model") or ""
        if endpoint and model:
            return ScaffoldPlanner(
                endpoint=endpoint,
                model=model,
                api_key=options.get("api_key") or None,
                timeout=float(options.get("timeout") or 30),
            )
    return LocalPlanner()
