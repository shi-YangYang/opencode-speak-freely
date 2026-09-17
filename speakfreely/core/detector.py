# -*- coding: utf-8 -*-
"""拒绝检测器。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。

四层策略（按顺序，第一个命中即返回）：
  1. 强短语：全文匹配
  2. 弱关键词：开头窗口内匹配
  3. 正则兜底：开头窗口内的变体（处理"我做不到/帮不了/I can't"这类组合）
  4. 自定义关键词：全文匹配

`detect_verbose` 返回命中的层与模式，便于统计漏检和回归。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import constants


class RefusalDetector:
    """拒绝检测器。"""

    def __init__(
        self,
        custom_keywords: Optional[Dict[str, List[str]]] = None,
        head_window: int = constants.HEAD_WINDOW,
        strong_phrases: Optional[List[str]] = None,
        weak_keywords: Optional[List[str]] = None,
        regex_patterns: Optional[List[str]] = None,
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
        patterns = (
            regex_patterns if regex_patterns is not None else constants.REGEX_HEAD_PATTERNS
        )
        self.regex_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

    def detect_verbose(self, content: str) -> Dict[str, Optional[str]]:
        """返回 {refusal, layer, matched}；layer ∈ strong/weak/regex/custom。"""
        if not content:
            return {"refusal": False, "layer": None, "matched": None}

        lowered = content.lower()

        for phrase in self.strong_phrases:
            if phrase in lowered:
                return {"refusal": True, "layer": "strong", "matched": phrase}

        head = lowered[: self.head_window]
        for keyword in self.weak_keywords:
            if keyword in head:
                return {"refusal": True, "layer": "weak", "matched": keyword}

        for pattern in self.regex_patterns:
            match = pattern.search(head)
            if match:
                return {"refusal": True, "layer": "regex", "matched": match.group(0)}

        for lang_keywords in self.custom_keywords.values():
            for keyword in lang_keywords:
                if keyword.lower() in lowered:
                    return {"refusal": True, "layer": "custom", "matched": keyword}

        return {"refusal": False, "layer": None, "matched": None}

    def detect(self, content: str) -> bool:
        return bool(self.detect_verbose(content)["refusal"])
