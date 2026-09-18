# -*- coding: utf-8 -*-
"""从 OpenCode 自身配置检测可用的 OpenAI 兼容 LLM（免手填）。

来源：
  1. ~/.config/opencode/opencode.jsonc(.json)  — 自定义 provider（含 baseURL/key/models）
  2. ~/.local/share/opencode/auth.json         — 登录/密钥型 provider
  3. ~/.cache/opencode/models.json             — provider 目录（endpoint 与模型列表）
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from . import jsonc

_FILE_CACHE: Dict[str, Dict[str, Any]] = {}
_FILE_TTL = 10.0
_DETECT_CACHE: Dict[str, Any] = {"time": 0.0, "entries": []}

CONFIG_CANDIDATES = (
    "~/.config/opencode/opencode.jsonc",
    "~/.config/opencode/opencode.json",
)
AUTH_PATH = "~/.local/share/opencode/auth.json"
CATALOG_PATH = "~/.cache/opencode/models.json"


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    target = os.path.expanduser(path)
    if not os.path.exists(target):
        return None
    try:
        mtime = os.path.getmtime(target)
    except OSError:
        return None

    cached = _FILE_CACHE.get(target)
    if cached and cached["mtime"] == mtime and time.time() - cached["time"] < _FILE_TTL:
        return cached["data"]

    try:
        with open(target, "r", encoding="utf-8") as stream:
            raw = stream.read()
    except OSError:
        return None

    # 大文件（models.json）走标准 JSON 快速路径，带注释的配置再回退 JSONC 解析
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = jsonc.parse(raw)

    result = data if isinstance(data, dict) else None
    _FILE_CACHE[target] = {"mtime": mtime, "time": time.time(), "data": result}
    return result


def _load_config() -> Optional[Dict[str, Any]]:
    for candidate in CONFIG_CANDIDATES:
        data = _load_json(candidate)
        if data:
            return data
    return None


def detect_all(use_cache: bool = True) -> List[Dict[str, Any]]:
    """列出所有可用 provider：{provider, endpoint, api_key, models, source}。"""
    if use_cache and _DETECT_CACHE["entries"] and time.time() - _DETECT_CACHE["time"] < _FILE_TTL:
        return _DETECT_CACHE["entries"]

    providers: Dict[str, Dict[str, Any]] = {}

    config = _load_config() or {}
    for pid, provider in (config.get("provider") or {}).items():
        options = (provider or {}).get("options") or {}
        endpoint = options.get("baseURL") or ""
        api_key = options.get("apiKey") or ""
        if not endpoint or not api_key:
            continue
        providers[pid] = {
            "provider": pid,
            "endpoint": endpoint.rstrip("/"),
            "api_key": api_key,
            "models": sorted((provider.get("models") or {}).keys()),
            "source": "config",
        }

    auth = _load_json(AUTH_PATH) or {}
    catalog = _load_json(CATALOG_PATH) or {}
    for pid, entry in auth.items():
        if pid in providers:
            continue
        if (entry or {}).get("type") != "api":
            continue
        api_key = entry.get("key") or ""
        if not api_key:
            continue
        meta = catalog.get(pid) or {}
        endpoint = (meta.get("api") or "").rstrip("/")
        if not endpoint:
            continue
        models = sorted((meta.get("models") or {}).keys())
        providers[pid] = {
            "provider": pid,
            "endpoint": endpoint,
            "api_key": api_key,
            "models": models,
            "source": "auth",
        }

    entries = sorted(providers.values(), key=lambda item: -len(item["models"]))
    _DETECT_CACHE["time"] = time.time()
    _DETECT_CACHE["entries"] = entries
    return entries


def resolve(provider_id: str) -> Optional[Dict[str, Any]]:
    for entry in detect_all():
        if entry["provider"] == provider_id:
            return entry
    return None


def detect() -> Optional[Dict[str, str]]:
    """按默认模型对应的 provider 优先，否则取模型最多的一个。"""
    entries = detect_all()
    if not entries:
        return None

    config = _load_config() or {}
    default_ref = str(config.get("model") or "")
    default_provider = default_ref.partition("/")[0]
    model_id = default_ref.partition("/")[2]

    chosen = next((entry for entry in entries if entry["provider"] == default_provider), entries[0])
    model = model_id if chosen["provider"] == default_provider and model_id else (
        chosen["models"][0] if chosen["models"] else ""
    )
    return {
        "endpoint": chosen["endpoint"],
        "api_key": chosen["api_key"],
        "model": model,
        "provider": chosen["provider"],
    }
