# -*- coding: utf-8 -*-
"""opencode CLI 调用与事件解析。"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from .verify import find_opencode


def parse_events(stdout: str) -> Dict[str, Any]:
    """解析 `opencode run --format json` 输出。

    返回 {session_id, text, cost, tool_calls}
    """
    session_id: Optional[str] = None
    texts: Dict[str, str] = {}
    order: List[str] = []
    cost = 0.0
    tool_calls = 0

    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        session_id = event.get("sessionID") or session_id
        part = event.get("part") or {}
        event_type = event.get("type")

        if event_type == "text":
            part_id = part.get("id") or "unknown"
            if part_id not in texts:
                order.append(part_id)
            texts[part_id] = part.get("text", "")
        elif event_type in ("tool", "tool_use"):
            tool_calls += 1
        elif event_type == "step_finish":
            try:
                cost += float(part.get("cost") or 0)
            except (TypeError, ValueError):
                pass

    return {
        "session_id": session_id,
        "text": "\n".join(texts[part_id] for part_id in order),
        "cost": cost,
        "tool_calls": tool_calls,
    }


def run_open(
    prompt: str,
    directory: Optional[str] = None,
    model: Optional[str] = None,
    session: Optional[str] = None,
    timeout: int = 600,
    auto_approve: bool = True,
) -> Dict[str, Any]:
    """调用 `opencode run`，返回 {session_id, text, cost, returncode, stderr}。"""
    binary = find_opencode()
    if not binary:
        raise RuntimeError("未找到 opencode CLI，请先安装（npm i -g opencode-ai）")

    command = [binary, "run", "--format", "json"]
    if directory:
        command += ["--dir", directory]
    if model:
        command += ["-m", model]
    if session:
        command += ["-s", session]
    if auto_approve:
        command += ["--auto"]
    command.append(prompt)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # 超时也要尽量从已产生的输出里恢复 session id / 文本
        raw = exc.stdout or ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        parsed = parse_events(raw)
        parsed.update(
            {
                "text": parsed["text"],
                "session_id": parsed["session_id"] or session,
                "cost": parsed["cost"],
                "returncode": None,
                "stderr": "timeout after {}s".format(timeout),
                "timeout": True,
                "command": command,
            }
        )
        return parsed

    parsed = parse_events(completed.stdout)
    parsed.update(
        {
            "returncode": completed.returncode,
            "stderr": completed.stderr[-2000:] if completed.stderr else "",
            "timeout": False,
            "command": command,
        }
    )
    if parsed["session_id"] is None:
        parsed["session_id"] = session
    return parsed
