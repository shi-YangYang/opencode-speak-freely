# -*- coding: utf-8 -*-
"""LLM 裁判：关键词/正则层未命中时，用便宜模型判定是否拒绝。

只在启发式门槛通过时调用（短文本 + 含可疑词），控制成本。
判为拒绝的样本会记录到 ~/.config/speakfreely/misses.jsonl，用于回归。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from . import llm

JUDGE_PROMPT = (
    "You check whether an assistant message refuses the user's request.\n"
    "Answer with exactly one word: REFUSAL or OK.\n"
    "REFUSAL = the assistant declines, deflects, or only offers unrelated alternatives.\n"
    "OK = the assistant attempts the task (even if partial or with caveats)."
)

HINT_TOKENS = [
    "授权", "滥用", "非目标", "越权", "合规", "政策", "policy", "边界",
    "不能", "无法", "拒绝", "抱歉", "限制", "不允许", "不当", "违反",
    "refuse", "unable", "cannot", "can't", "won't", "decline",
]

MAX_JUDGE_LENGTH = 1500


def should_judge(text: str, max_length: int = MAX_JUDGE_LENGTH) -> bool:
    """启发式门槛：过长的正常输出不送裁判。"""
    if not text or len(text) > max_length:
        return False
    lowered = text.lower()
    return any(token in lowered for token in HINT_TOKENS)


def misses_path() -> str:
    return os.path.expanduser("~/.config/speakfreely/misses.jsonl")


def record_miss(text: str, source: str = "judge", path: Optional[str] = None) -> str:
    target = path or misses_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "excerpt": text[:500],
    }
    with open(target, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target


class LLMJudge:
    """用 LLM 判定文本是否为拒绝。"""

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: Optional[str] = None,
        timeout: float = 20,
        chat_fn: Optional[Callable[..., str]] = None,
    ):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._chat = chat_fn or llm.chat

    def is_refusal(self, text: str) -> Optional[bool]:
        """True=拒绝，False=正常，None=无法判定（调用失败或答案不可解析）。"""
        if not text:
            return False
        try:
            answer = self._chat(
                [
                    {"role": "system", "content": JUDGE_PROMPT},
                    {"role": "user", "content": text[:6000]},
                ],
                endpoint=self.endpoint,
                api_key=self.api_key,
                model=self.model,
                timeout=self.timeout,
                max_tokens=8,
            )
        except Exception:  # noqa: BLE001 - 裁判失败不应影响主流程
            return None

        upper = (answer or "").upper()
        if "REFUSAL" in upper:
            return True
        if re.search(r"\bOK\b", upper):
            return False
        return None


def from_config(config: Dict[str, Any]) -> Optional[LLMJudge]:
    """按配置构造；未启用或配置不完整时返回 None。"""
    section = config.get("judge") or {}
    if not section.get("enabled"):
        return None
    endpoint = section.get("endpoint") or ""
    model = section.get("model") or ""
    if not endpoint or not model:
        return None
    return LLMJudge(
        endpoint=endpoint,
        model=model,
        api_key=section.get("api_key") or None,
        timeout=float(section.get("timeout") or 20),
    )
