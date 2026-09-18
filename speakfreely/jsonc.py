# -*- coding: utf-8 -*-
"""JSONC 解析（去注释/尾逗号，字符串内的 // 不处理）。"""
from __future__ import annotations

import json
import re
from typing import Any, Optional


def parse(raw: str) -> Optional[Any]:
    try:
        return json.loads(strip(raw))
    except json.JSONDecodeError:
        return None


def strip(raw: str) -> str:
    out = []
    index = 0
    length = len(raw)
    in_string = False

    while index < length:
        char = raw[index]

        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(raw[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length and raw[index + 1] == "/":
            while index < length and raw[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and index + 1 < length and raw[index + 1] == "*":
            index += 2
            while index + 1 < length and not (raw[index] == "*" and raw[index + 1] == "/"):
                index += 1
            index += 2
            continue

        out.append(char)
        index += 1

    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))
