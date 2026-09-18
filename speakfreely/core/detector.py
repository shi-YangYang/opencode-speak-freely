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

# 防误报：长消息里中后部出现的拒绝短语多半是"引用/分析"而非拒绝本身
QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f`"
MAX_SHORT_LENGTH = 600
MAX_MATCH_POSITION = 200
STRICT_MAX_LENGTH = 400
STRICT_MAX_POSITION = 0.4

# 单纯的礼貌用语不是拒绝，必须伴随拒绝动词
POLITE_ONLY = {"抱歉", "很抱歉", "对不起", "不好意思", "sorry", "apologize"}
REFUSAL_SIGNALS = (
    "不能", "无法", "没法", "不会", "不做", "拒绝", "不允许", "禁止",
    "帮不了", "做不到", "unable", "cannot", "can't", "won't", "refuse",
)


def _quoted(content: str, position: int, window: int = 3) -> bool:
    """命中位置前 window 个字符里出现引号/反引号时，视为引用而非拒绝。"""
    start = max(0, position - window)
    return any(char in QUOTE_CHARS for char in content[start:position])


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
            position = lowered.find(phrase)
            if position < 0:
                continue
            # 引用/转述不算拒绝：命中前紧邻引号/反引号
            if _quoted(content, position):
                continue
            # 长消息里中后部的命中不算拒绝（分析、汇报在引用拒绝内容）
            if len(content) > MAX_SHORT_LENGTH and position > MAX_MATCH_POSITION:
                continue
            return {"refusal": True, "layer": "strong", "matched": phrase}

        head = lowered[: self.head_window]
        for keyword in self.weak_keywords:
            position = head.find(keyword)
            if position < 0:
                continue
            if _quoted(content, position):
                continue
            return {"refusal": True, "layer": "weak", "matched": keyword}

        for pattern in self.regex_patterns:
            match = pattern.search(head)
            if match and _quoted(content, match.start()):
                continue
            if match:
                return {"refusal": True, "layer": "regex", "matched": match.group(0)}

        for lang_keywords in self.custom_keywords.values():
            for keyword in lang_keywords:
                if keyword.lower() in lowered:
                    return {"refusal": True, "layer": "custom", "matched": keyword}

        return {"refusal": False, "layer": None, "matched": None}

    def detect(self, content: str) -> bool:
        return bool(self.detect_verbose(content)["refusal"])

    def detect_strict(self, content: str) -> bool:
        """严格模式：只认"短消息 + 开头命中 + 未被引用"的拒绝。

        清理链路默认用它，避免把分析/汇报里引用的拒绝短语误替换。
        """
        result = self.detect_verbose(content)
        if not result["refusal"]:
            return False

        matched = (result["matched"] or "").lower()
        position = content.lower().find(matched)
        if position < 0:
            return False
        if len(content) > STRICT_MAX_LENGTH:
            return False
        if position > min(150, len(content) * STRICT_MAX_POSITION):
            return False
        if _quoted(content, position):
            return False

        # 仅有"抱歉/对不起"这类礼貌词、全文没有拒绝动词 -> 不算拒绝
        if matched.strip() in POLITE_ONLY:
            lowered = content.lower()
            if not any(signal in lowered for signal in REFUSAL_SIGNALS):
                return False
        return True
