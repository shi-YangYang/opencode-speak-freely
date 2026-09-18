# -*- coding: utf-8 -*-
"""清理管线。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。

针对 OpenCode 消息结构（dict 序列）重写，去掉了上游对 Codex JSONL /
Claude Code 的耦合，保留：拒绝替换、thinking 擦除、按行选择、变更详情。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .constants import DEFAULT_REPLACEMENT
from .detector import RefusalDetector
from .formats import OpenCodeFormat


@dataclass
class ChangeDetail:
    """一处修改详情。"""

    line_num: int
    change_type: str  # 'replace' | 'remove_thinking'
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    line_nums: Optional[List[int]] = field(default=None)


def clean_messages(
    messages: List[Dict[str, Any]],
    detector: RefusalDetector,
    replacement: Optional[str] = None,
    clean_reasoning: bool = False,
    selected_lines: Optional[List[int]] = None,
    show_content: bool = False,
    strategy: Optional[OpenCodeFormat] = None,
) -> Tuple[List[Dict[str, Any]], bool, List[ChangeDetail]]:
    """清理消息序列。

    Args:
        messages: sqlite_store 转换后的消息列表
        detector: 拒绝检测器
        replacement: 替换文本，默认 constants.DEFAULT_REPLACEMENT
        clean_reasoning: 是否移除 thinking/reasoning 内容
        selected_lines: 只处理指定行号（1-based），None 表示全部
        show_content: 是否在 ChangeDetail 中携带原文预览
        strategy: 格式策略，默认 OpenCode

    Returns:
        (清理后的消息, 是否有修改, 变更列表)
    """
    strategy = strategy or OpenCodeFormat()
    replacement = replacement or DEFAULT_REPLACEMENT
    selected = set(selected_lines) if selected_lines else None

    modified = False
    changes: List[ChangeDetail] = []

    for index, msg in strategy.get_assistant_messages(messages):
        if selected is not None and (index + 1) not in selected:
            continue

        content = strategy.extract_text_content(msg)
        if not content or not detector.detect_strict(content):
            continue

        detail = ChangeDetail(
            line_num=index + 1,
            change_type="replace",
            line_nums=[index + 1],
        )
        if show_content:
            detail.original_content = content[:500] + ("..." if len(content) > 500 else "")
            detail.new_content = replacement
        changes.append(detail)

        messages[index] = strategy.update_text_content(msg, replacement)
        modified = True

    if clean_reasoning:
        for index, msg in enumerate(messages):
            updated, removed = strategy.remove_thinking_from_message(msg)
            if removed <= 0:
                continue
            detail = ChangeDetail(
                line_num=index + 1,
                change_type="remove_thinking",
            )
            if show_content:
                detail.original_content = "移除 {} 个 thinking 块".format(removed)
            changes.append(detail)
            messages[index] = updated
            modified = True

    return messages, modified, changes
