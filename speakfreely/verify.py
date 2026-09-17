"""上下文加载校验（调用 opencode CLI 自检）。"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, Optional

DEFAULT_MARKER = "Engagement Baseline"


def find_opencode() -> Optional[str]:
    from .paths import find_command
    return find_command("opencode")


def check_context(
    marker: str = DEFAULT_MARKER,
    directory: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 180,
) -> Dict[str, Any]:
    """让模型自己回答上下文里是否有标记短语。

    返回 {available, ok, answer, command, returncode}
    """
    binary = find_opencode()
    if not binary:
        return {
            "available": False,
            "ok": False,
            "answer": "",
            "command": None,
            "returncode": None,
        }

    command = [binary, "run"]
    if directory:
        command += ["--dir", os.path.abspath(directory)]
    if model:
        command += ["-m", model]
    command.append(
        "Answer only 'yes' or 'no': does your current context contain "
        "the exact phrase '{}'?".format(marker)
    )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": True,
            "ok": False,
            "answer": "timeout",
            "command": command,
            "returncode": None,
        }

    output = (completed.stdout or "") + (completed.stderr or "")
    stripped = output.strip()

    affirmative = re.search(r"\byes\b", stripped, re.IGNORECASE) is not None
    negative = re.search(r"\bno\b", stripped, re.IGNORECASE) is not None
    ok = completed.returncode == 0 and affirmative and not negative

    return {
        "available": True,
        "ok": ok,
        "answer": stripped[-400:],
        "command": command,
        "returncode": completed.returncode,
    }
