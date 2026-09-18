# -*- coding: utf-8 -*-
"""从 OpenCode 自己的配置里检测可用的 OpenAI 兼容 LLM（免手填）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from . import jsonc

CONFIG_CANDIDATES = (
    "~/.config/opencode/opencode.jsonc",
    "~/.config/opencode/opencode.json",
)


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as stream:
            data = jsonc.parse(stream.read())
    except OSError:
        return None
    return data if isinstance(data, dict) else None


def detect() -> Optional[Dict[str, str]]:
    """返回 {endpoint, api_key, model}（取配置里的默认模型与对应 provider）。"""
    data = None
    for candidate in CONFIG_CANDIDATES:
        data = _load(candidate)
        if data:
            break
    if not data:
        return None

    providers = data.get("provider") or {}
    model_ref = str(data.get("model") or "")
    provider_id, _, model_id = model_ref.partition("/")

    if not provider_id:
        # 没有默认模型：取第一个带 baseURL+key 的 provider 的第一个模型
        for pid, provider in providers.items():
            options = (provider or {}).get("options") or {}
            if options.get("baseURL") and options.get("apiKey"):
                models = list(((provider or {}).get("models") or {}).keys())
                if models:
                    return {
                        "endpoint": options["baseURL"],
                        "api_key": options["apiKey"],
                        "model": models[0],
                        "provider": pid,
                    }
        return None

    provider = providers.get(provider_id) or {}
    options = provider.get("options") or {}
    endpoint = options.get("baseURL") or ""
    api_key = options.get("apiKey") or ""
    if not endpoint or not api_key:
        return None
    if not model_id:
        models = list((provider.get("models") or {}).keys())
        model_id = models[0] if models else ""
    if not model_id:
        return None
    return {
        "endpoint": endpoint,
        "api_key": api_key,
        "model": model_id,
        "provider": provider_id,
    }
