"""本工具配置（~/.config/speakfreely/config.json）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .core.constants import DEFAULT_REPLACEMENT
from .core.file_ops import atomic_write_json

DEFAULTS: Dict[str, Any] = {
    "llm": {
        "endpoint": "",
        "api_key": "",
        "model": "",
        "timeout": 30,
    },
    "replacement": DEFAULT_REPLACEMENT,
    "keywords": {},
    "clean_reasoning": False,
    "judge": {
        "enabled": False,
        "endpoint": "",
        "api_key": "",
        "model": "",
        "timeout": 20,
    },
    "planner": {
        "enabled": False,
        "endpoint": "",
        "api_key": "",
        "model": "",
        "timeout": 30,
    },
    "prefill": {
        "mode": "template",  # template | auto
        "endpoint": "",
        "api_key": "",
        "model": "",
        "timeout": 30,
    },
}


class ConfigError(ValueError):
    """配置无法读取或保存。"""


def default_config_path() -> str:
    return os.path.expanduser("~/.config/speakfreely/config.json")


def config_path(path: Optional[str] = None) -> str:
    return path or default_config_path()


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """读取配置；文件不存在时返回默认值，字段与默认值合并。"""
    target = config_path(path)
    data: Dict[str, Any] = {}
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError("读取配置失败: {}: {}".format(target, exc)) from exc
        if not isinstance(data, dict):
            raise ConfigError("配置根节点必须是对象: {}".format(target))

    merged = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in DEFAULTS.items()
    }
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(DEFAULTS.get(key), dict):
            section = dict(DEFAULTS[key])
            section.update(value)
            merged[key] = section
        else:
            merged[key] = value
    return merged


def llm_settings(config: Dict[str, Any], section: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """共享 LLM 配置 + 功能段覆盖值；缺 endpoint/model 时回退到 OpenCode 自身配置。"""
    merged = dict(config.get("llm") or {})
    for key in ("endpoint", "api_key", "model", "timeout"):
        value = (section or {}).get(key)
        if value:
            merged[key] = value

    if not merged.get("endpoint") or not merged.get("model"):
        from . import opencode_llm

        detected = opencode_llm.detect()
        if detected:
            for key in ("endpoint", "api_key", "model"):
                if not merged.get(key):
                    merged[key] = detected.get(key)
    return merged


def save_config(data: Dict[str, Any], path: Optional[str] = None) -> None:
    if not isinstance(data, dict):
        raise ConfigError("配置根节点必须是对象")
    target = config_path(path)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.name != "nt":
            os.chmod(os.path.dirname(target), 0o700)
        atomic_write_json(target, data, mode=0o600)
    except OSError as exc:
        raise ConfigError("保存配置失败: {}: {}".format(target, exc)) from exc
