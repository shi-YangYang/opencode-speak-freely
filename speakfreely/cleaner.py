"""会话清理（直接调用 codex_session_patcher 库，绕开其 CLI 的已知缺陷）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _load_deps():
    try:
        from codex_session_patcher.config import load_config
        from codex_session_patcher.core import (
            MOCK_RESPONSE,
            OpenCodeDBAdapter,
            RefusalDetector,
            SessionFormat,
            clean_session_jsonl,
        )
    except ImportError:
        return None

    return {
        "load_config": load_config,
        "MOCK_RESPONSE": MOCK_RESPONSE,
        "OpenCodeDBAdapter": OpenCodeDBAdapter,
        "RefusalDetector": RefusalDetector,
        "SessionFormat": SessionFormat,
        "clean_session_jsonl": clean_session_jsonl,
    }


def _change_line(change: Any) -> str:
    kind = {
        "replace": "替换拒绝回复",
        "delete": "删除推理内容",
        "remove_thinking": "移除 thinking 块",
    }.get(change.change_type, change.change_type)
    return "第 {} 行 {}".format(change.line_num, kind)


def clean_opencode(
    all_sessions: bool = False,
    dry_run: bool = False,
    show_content: bool = False,
    clean_reasoning: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """清理 OpenCode 会话中被拒的助手消息。

    返回 {available, sessions: [{id, modified, backup, changes: [...]}]}
    """
    deps = _load_deps()
    if deps is None:
        return {"available": False, "sessions": [], "reason": "未安装 codex-session-patcher"}

    adapter = deps["OpenCodeDBAdapter"](db_path) if db_path else deps["OpenCodeDBAdapter"]()
    try:
        sessions = adapter.list_sessions()
    except FileNotFoundError as exc:
        return {"available": True, "sessions": [], "reason": str(exc)}

    if not sessions:
        return {"available": True, "sessions": [], "reason": "未找到会话"}

    selected = sessions if all_sessions else sessions[:1]

    config = deps["load_config"]()
    mock_response = config.get("mock_response") or deps["MOCK_RESPONSE"]
    keywords = config.get("custom_keywords", None)
    detector = deps["RefusalDetector"](keywords)

    results: List[Dict[str, Any]] = []
    for session in selected:
        session_id = session["session_id"]
        entry: Dict[str, Any] = {"id": session_id, "modified": False, "changes": []}

        try:
            lines = adapter.load_session_messages(session_id)
        except Exception as exc:  # noqa: BLE001 - 单个会话失败不影响其他会话
            entry["error"] = str(exc)
            results.append(entry)
            continue

        cleaned, modified, changes = deps["clean_session_jsonl"](
            lines,
            detector,
            show_content=show_content,
            mock_response=mock_response,
            session_format=deps["SessionFormat"].OPENCODE,
            clean_reasoning=clean_reasoning,
        )
        entry["modified"] = modified
        entry["changes"] = [_change_line(change) for change in changes]

        if modified and not dry_run:
            entry["backup"] = adapter.backup_database()
            adapter.save_session_messages(session_id, cleaned)

        results.append(entry)

    return {"available": True, "sessions": results, "reason": None}
