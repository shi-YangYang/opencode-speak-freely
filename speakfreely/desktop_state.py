# -*- coding: utf-8 -*-
"""读取 OpenCode Desktop 的本地状态（项目列表等）。

Desktop 侧边栏里的项目保存在它自己的状态文件里，只有真正产生会话后才会写入
共享数据库；这里直接读状态文件，避免"桌面里开着、Web UI 里看不到"。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

STATE_CANDIDATES = (
    "~/Library/Application Support/ai.opencode.desktop/opencode.global.dat",  # macOS
    "~/.config/ai.opencode.desktop/opencode.global.dat",                     # Linux
    "~/AppData/Roaming/ai.opencode.desktop/opencode.global.dat",             # Windows
)


def _load_state() -> Dict[str, Any]:
    for candidate in STATE_CANDIDATES:
        target = os.path.expanduser(candidate)
        if not os.path.exists(target):
            continue
        try:
            with open(target, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _as_dict(value: Any) -> Dict[str, Any]:
    """状态文件里有些值是 JSON 字符串，需要二次解析。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def project_dirs() -> List[str]:
    """Desktop 侧边栏里的项目目录列表。"""
    server = _as_dict(_load_state().get("server"))
    projects = _as_dict(server.get("projects"))
    local = projects.get("local")
    if isinstance(local, str):
        try:
            local = json.loads(local)
        except json.JSONDecodeError:
            local = []
    entries = local or []
    dirs = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        worktree = entry.get("worktree") or ""
        if worktree:
            dirs.append(worktree)
    return dirs
