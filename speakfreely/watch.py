# -*- coding: utf-8 -*-
"""监视模式：定时扫描会话，自动清理新出现的拒绝（供 Desktop 使用）。"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from . import cleaner as cleaner_module
from .core import DEFAULT_OPENCODE_DB, OpenCodeDBAdapter, RefusalDetector


def watch(
    project_dir: Optional[str] = None,
    interval: float = 5.0,
    settle_seconds: float = 3.0,
    once: bool = False,
    dry_run: bool = False,
    clean_reasoning: bool = False,
    replacement: Optional[str] = None,
    db_path: Optional[str] = None,
    detector: Optional[RefusalDetector] = None,
    on_event: Optional[Callable[[str], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """轮询数据库，发现新的拒绝就替换。

    返回 {scans, cleaned: [{session, backup}], errors}
    """
    adapter = OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB)
    detector = detector or RefusalDetector()
    project_dir = (
        os.path.realpath(os.path.expanduser(project_dir)) if project_dir else None
    )

    def emit(message: str) -> None:
        if on_event:
            on_event(message)

    seen_updated: Dict[str, float] = {}
    cleaned: List[Dict[str, Any]] = []
    errors: List[str] = []
    scans = 0
    now = time.time()

    while True:
        if should_stop and should_stop():
            return {"scans": scans, "cleaned": cleaned, "errors": errors}
        scans += 1
        try:
            sessions = adapter.list_sessions()
        except FileNotFoundError as exc:
            errors.append(str(exc))
            return {"scans": scans, "cleaned": cleaned, "errors": errors}

        for item in sessions:
            session_id = item["session_id"]
            if project_dir and os.path.realpath(item.get("directory") or "") != project_dir:
                continue

            updated = item.get("mtime") or 0
            if seen_updated.get(session_id) == updated:
                continue
            if now - updated < settle_seconds:
                # 可能仍在流式输出，下一轮再看
                continue
            seen_updated[session_id] = updated

            try:
                result = cleaner_module.clean_opencode(
                    session=session_id,
                    dry_run=dry_run,
                    clean_reasoning=clean_reasoning,
                    replacement=replacement,
                    db_path=db_path,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append("{}: {}".format(session_id, exc))
                continue

            entry = (result.get("sessions") or [{}])[0]
            if entry.get("modified"):
                if dry_run:
                    emit(
                        "[{}] 检测到 {} 处（预览，未修改）".format(
                            session_id, len(entry.get("changes", []))
                        )
                    )
                else:
                    emit(
                        "[{}] 已替换 {} 处".format(
                            session_id, len(entry.get("changes", []))
                        )
                    )
                cleaned.append({"session": session_id, "backup": entry.get("backup")})

        if once:
            return {"scans": scans, "cleaned": cleaned, "errors": errors}
        sleep(interval)
        if should_stop and should_stop():
            return {"scans": scans, "cleaned": cleaned, "errors": errors}


def watch_forever(**kwargs: Any) -> Dict[str, Any]:
    kwargs.setdefault("once", False)
    return watch(**kwargs)
