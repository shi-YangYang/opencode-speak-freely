# -*- coding: utf-8 -*-
"""拒绝检测器。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import constants


class RefusalDetector:
    """两级拒绝检测：强短语全文匹配 + 弱关键词开头匹配 + 自定义关键词全文匹配。"""

    def __init__(
        self,
        custom_keywords: Optional[Dict[str, List[str]]] = None,
        head_window: int = constants.HEAD_WINDOW,
        strong_phrases: Optional[List[str]] = None,
        weak_keywords: Optional[List[str]] = None,
    ):
        self.custom_keywords = {}
        if custom_keywords:
            for lang, words in custom_keywords.items():
                self.custom_keywords[lang] = list(words)

        self.head_window = head_window
        self.strong_phrases = list(
            strong_phrases if strong_phrases is not None else constants.STRONG_REFUSAL_PHRASES
        )
        self.weak_keywords = list(
            weak_keywords if weak_keywords is not None else constants.WEAK_REFUSAL_KEYWORDS
        )

    def detect(self, content: str) -> bool:
        if not content:
            return False

        lowered = content.lower()

        for phrase in self.strong_phrases:
            if phrase in lowered:
                return True

        head = lowered[: self.head_window]
        for keyword in self.weak_keywords:
            if keyword in head:
                return True

        for lang_keywords in self.custom_keywords.values():
            for keyword in lang_keywords:
                if keyword.lower() in lowered:
                    return True

        return False
