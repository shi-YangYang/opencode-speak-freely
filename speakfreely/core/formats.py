# -*- coding: utf-8 -*-
"""OpenCode 消息格式操作。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。

消息结构（由 sqlite_store 转换）:

    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": "..."},
            {"type": "thinking", "text": "..."},   # reasoning 映射为 thinking
        ]},
        "_oc_msg_id": "msg_xxx",
        "_oc_parts": [{"id": "prt_xxx", "type": "text"}, ...],
    }
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple


class OpenCodeFormat:
    """OpenCode 格式操作。本项目只支持 OpenCode。"""

    def get_assistant_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Tuple[int, Dict[str, Any]]]:
        found = []
        for index, line in enumerate(messages):
            if line.get("type") != "assistant":
                continue
            message = line.get("message", {})
            if message.get("role") == "assistant":
                found.append((index, line))
        return found

    def extract_text_content(self, msg: Dict[str, Any]) -> str:
        content = msg.get("message", {}).get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        return ""

    def update_text_content(self, msg: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        updated = copy.deepcopy(msg)
        message = updated.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    item["text"] = new_text
                    return updated
            content.append({"type": "text", "text": new_text})
        else:
            message["content"] = [{"type": "text", "text": new_text}]
        return updated

    def remove_thinking_from_message(self, msg: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        updated = copy.deepcopy(msg)
        message = updated.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            return updated, 0
        original_len = len(content)
        message["content"] = [
            item
            for item in content
            if not (isinstance(item, dict) and item.get("type") == "thinking")
        ]
        return updated, original_len - len(message["content"])
