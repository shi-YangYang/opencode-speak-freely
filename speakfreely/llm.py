# -*- coding: utf-8 -*-
"""OpenAI 兼容的最小 LLM 客户端（标准库，无依赖）。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class LLMError(RuntimeError):
    """LLM 调用失败。"""


def chat(
    messages: List[Dict[str, str]],
    endpoint: str,
    api_key: Optional[str] = None,
    model: str = "",
    timeout: float = 30,
    max_tokens: int = 256,
    temperature: float = 0.0,
    retries: int = 2,
) -> str:
    """调用 {endpoint}/chat/completions；空内容或网络错误时自动重试。"""
    if not endpoint:
        raise LLMError("未配置 LLM endpoint")
    if not model:
        raise LLMError("未配置 LLM model")

    last_error: Optional[Exception] = None
    budget = max_tokens
    for attempt in range(max(0, retries) + 1):
        try:
            content = _chat_once(
                messages=messages,
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                timeout=timeout,
                max_tokens=budget,
                temperature=temperature,
            )
        except LLMError as exc:
            last_error = exc
            content = ""
        if content:
            return content
        if attempt < retries:
            # 推理模型可能把预算花在 reasoning 上导致 content 为空：翻倍再试
            budget = min(budget * 2, 8000)
            time.sleep(0.3)

    if last_error is not None:
        raise last_error
    return ""


def _chat_once(
    messages: List[Dict[str, str]],
    endpoint: str,
    api_key: Optional[str],
    model: str,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    url = endpoint.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer {}".format(api_key)

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LLMError("LLM 请求失败: {}".format(exc)) from exc

    choices = data.get("choices") or []
    if not choices:
        raise LLMError("LLM 返回空结果")
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()
