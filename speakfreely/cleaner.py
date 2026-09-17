# -*- coding: utf-8 -*-
"""会话清理与恢复（内置核心，不依赖上游）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config as config_module
from . import workflow
from .core import (
    DEFAULT_OPENCODE_DB,
    DEFAULT_REPLACEMENT,
    OpenCodeDBAdapter,
    RefusalDetector,
    clean_messages,
)


def _resolve_replacement(
    explicit: Optional[str],
    stage: Optional[str],
    config: Dict[str, Any],
) -> str:
    if explicit:
        return explicit
    if stage:
        found = workflow.get_stage(stage)
        if found is None:
            raise ValueError("未知阶段: {}".format(stage))
        return found["replacement"]
    return config.get("replacement") or DEFAULT_REPLACEMENT


def _change_line(change: Any) -> str:
    kind = {
        "replace": "替换拒绝回复",
        "remove_thinking": "移除 thinking 块",
    }.get(change.change_type, change.change_type)
    return "第 {} 行 {}".format(change.line_num, kind)


def clean_opencode(
    all_sessions: bool = False,
    session: Optional[str] = None,
    dry_run: bool = False,
    show_content: bool = False,
    clean_reasoning: Optional[bool] = None,
    replacement: Optional[str] = None,
    stage: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """清理 OpenCode 会话中被拒的助手消息。

    Returns:
        {"sessions": [{"id", "title", "modified", "changes", "backup", "error"}]}
    """
    config = config_module.load_config()
    if clean_reasoning is None:
        clean_reasoning = bool(config.get("clean_reasoning", False))
    replacement_text = _resolve_replacement(replacement, stage, config)

    detector = RefusalDetector(config.get("keywords") or {})

    adapter = OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB)
    try:
        sessions = adapter.list_sessions()
    except FileNotFoundError as exc:
        return {"sessions": [], "reason": str(exc)}

    if session:
        sessions = [item for item in sessions if item["session_id"] == session]
        if not sessions:
            return {"sessions": [], "reason": "未找到会话: {}".format(session)}
    elif not all_sessions:
        sessions = sessions[:1]

    if not sessions:
        return {"sessions": [], "reason": "没有可处理的会话"}

    results: List[Dict[str, Any]] = []
    for item in sessions:
        session_id = item["session_id"]
        entry: Dict[str, Any] = {
            "id": session_id,
            "title": item.get("title", ""),
            "modified": False,
            "changes": [],
        }

        try:
            messages = adapter.load_session_messages(session_id)
        except Exception as exc:  # noqa: BLE001 - 单会话失败不影响其他会话
            entry["error"] = str(exc)
            results.append(entry)
            continue

        cleaned, modified, changes = clean_messages(
            messages,
            detector,
            replacement=replacement_text,
            clean_reasoning=clean_reasoning,
            show_content=show_content,
        )
        entry["modified"] = modified
        entry["changes"] = [_change_line(change) for change in changes]
        if show_content:
            entry["details"] = changes

        if modified and not dry_run:
            entry["backup"] = adapter.backup_database()
            adapter.save_session_messages(session_id, cleaned)

        results.append(entry)

    return {"sessions": results, "reason": None}


def list_backups(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    return OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB).list_backups()


def restore_backup(backup_path: str, db_path: Optional[str] = None) -> None:
    OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB).restore_database(backup_path)
