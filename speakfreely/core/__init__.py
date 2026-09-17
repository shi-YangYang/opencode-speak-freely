# -*- coding: utf-8 -*-
"""speakfreely OpenCode 会话核心（内置版，改编自 codex-session-patcher，MIT）。"""
from .constants import DEFAULT_REPLACEMENT, HEAD_WINDOW, STRONG_REFUSAL_PHRASES, WEAK_REFUSAL_KEYWORDS
from .detector import RefusalDetector
from .formats import OpenCodeFormat
from .patcher import ChangeDetail, clean_messages
from .sqlite_store import DEFAULT_OPENCODE_DB, OpenCodeDBAdapter

__all__ = [
    "DEFAULT_REPLACEMENT",
    "HEAD_WINDOW",
    "STRONG_REFUSAL_PHRASES",
    "WEAK_REFUSAL_KEYWORDS",
    "RefusalDetector",
    "OpenCodeFormat",
    "ChangeDetail",
    "clean_messages",
    "DEFAULT_OPENCODE_DB",
    "OpenCodeDBAdapter",
]
