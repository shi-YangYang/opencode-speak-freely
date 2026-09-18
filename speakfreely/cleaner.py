# -*- coding: utf-8 -*-
"""会话清理与恢复（内置核心，不依赖上游）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config as config_module
from . import judge as judge_module
from . import prefill as prefill_module
from . import workflow
from .core import (
    DEFAULT_OPENCODE_DB,
    DEFAULT_REPLACEMENT,
    ChangeDetail,
    OpenCodeDBAdapter,
    OpenCodeFormat,
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


def _change_dict(change: Any) -> Dict[str, Any]:
    return {
        "line_num": change.line_num,
        "change_type": change.change_type,
        "original_content": change.original_content,
        "new_content": change.new_content,
        "line_nums": change.line_nums,
    }


def _change_line(change: Any) -> str:
    kind = {
        "replace": "替换拒绝回复",
        "remove_thinking": "移除 thinking 块",
    }.get(change.change_type, change.change_type)
    return "第 {} 行 {}".format(change.line_num, kind)


def _context_for_prefill(
    messages: List[Dict[str, Any]], detector: RefusalDetector
) -> tuple:
    """取最近一条用户消息 + 第一条拒绝文本，供 prefill 生成使用。"""
    strategy = OpenCodeFormat()
    last_user = ""
    refusal_text = ""

    for message in messages:
        role = message.get("type")
        content = message.get("message", {}).get("content", [])
        if role == "user":
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if texts:
                last_user = "\n".join(texts)
        elif role == "assistant" and not refusal_text:
            text = strategy.extract_text_content(message)
            if text and detector.detect(text):
                refusal_text = text

    return last_user, refusal_text


def _judge_pass(
    messages: List[Dict[str, Any]],
    detector: RefusalDetector,
    judge: Any,
    replacement: str,
    show_content: bool = False,
) -> tuple:
    """对关键词层未命中、但启发式可疑的消息做 LLM 裁判；判为拒绝则替换。"""
    strategy = OpenCodeFormat()
    modified = False
    changes: List[ChangeDetail] = []

    for index, msg in strategy.get_assistant_messages(messages):
        text = strategy.extract_text_content(msg)
        if not text or detector.detect(text):
            continue
        if not judge_module.should_judge(text):
            continue
        if judge.is_refusal(text) is not True:
            continue

        judge_module.record_miss(text, source="judge")
        detail = ChangeDetail(line_num=index + 1, change_type="replace", line_nums=[index + 1])
        if show_content:
            detail.original_content = text[:500] + ("..." if len(text) > 500 else "")
            detail.new_content = replacement
        changes.append(detail)
        messages[index] = strategy.update_text_content(msg, replacement)
        modified = True

    return modified, changes


def clean_opencode(
    all_sessions: bool = False,
    session: Optional[str] = None,
    dry_run: bool = False,
    show_content: bool = False,
    clean_reasoning: Optional[bool] = None,
    replacement: Optional[str] = None,
    stage: Optional[str] = None,
    db_path: Optional[str] = None,
    use_judge: bool = True,
    judge: Any = None,
    prefill_mode: Optional[str] = None,
    prefill_fn: Any = None,
    selected_lines: Optional[List[int]] = None,
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
    if judge is None and use_judge:
        judge = judge_module.from_config(config)

    if prefill_fn is None:
        prefill_fn = prefill_module.from_config(config, mode=prefill_mode)

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

        session_replacement = replacement_text
        if prefill_fn is not None:
            user_prompt, refusal_text = _context_for_prefill(messages, detector)
            generated = prefill_fn.generate(user_prompt, refusal_text)
            if generated:
                session_replacement = generated
                entry["prefill"] = generated

        cleaned, modified, changes = clean_messages(
            messages,
            detector,
            replacement=session_replacement,
            clean_reasoning=clean_reasoning,
            show_content=show_content,
            selected_lines=selected_lines,
        )
        if judge is not None and not selected_lines:
            judged, judged_changes = _judge_pass(
                cleaned, detector, judge, session_replacement, show_content=show_content
            )
            if judged:
                modified = True
                changes.extend(judged_changes)
        entry["modified"] = modified
        entry["changes"] = [_change_line(change) for change in changes]
        if show_content:
            entry["details"] = [_change_dict(change) for change in changes]

        if modified and not dry_run:
            entry["backup"] = adapter.backup_database()
            adapter.save_session_messages(session_id, cleaned)

        results.append(entry)

    return {"sessions": results, "reason": None}


def list_backups(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    return OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB).list_backups()


def restore_backup(backup_path: str, db_path: Optional[str] = None) -> None:
    OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB).restore_database(backup_path)


def delete_backup(backup_path: str, db_path: Optional[str] = None) -> None:
    OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB).delete_backup(backup_path)
