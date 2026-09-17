# -*- coding: utf-8 -*-
"""尝试日志与统计：记录每次发送的结果，用于模型/阶段拒绝率分析。"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def attempts_path() -> str:
    return os.path.expanduser("~/.config/speakfreely/attempts.jsonl")


def log_attempt(record: Dict[str, Any], path: Optional[str] = None) -> str:
    target = path or attempts_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    entry.update(record)
    with open(target, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return target


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def load_attempts(path: Optional[str] = None, days: Optional[int] = None) -> List[Dict[str, Any]]:
    target = path or attempts_path()
    if not os.path.exists(target):
        return []

    cutoff = datetime.now() - timedelta(days=days) if days else None
    records = []
    with open(target, "r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff is not None:
                stamp = _parse_ts(record.get("ts", ""))
                if stamp is None or stamp < cutoff:
                    continue
            records.append(record)
    return records


def summarize(
    path: Optional[str] = None, days: Optional[int] = None
) -> Dict[str, Any]:
    """按模型和阶段聚合发送/拒绝/成功。"""
    records = load_attempts(path=path, days=days)
    summary: Dict[str, Any] = {
        "total": {"sends": 0, "refusals": 0, "timeouts": 0, "cost": 0.0},
        "models": {},
        "stages": {},
    }

    for record in records:
        refused = bool(record.get("refused"))
        timeout = bool(record.get("timeout"))
        cost = float(record.get("cost") or 0)
        model = record.get("model") or "(default)"
        stage = record.get("stage") or "(unknown)"

        summary["total"]["sends"] += 1
        summary["total"]["refusals"] += 1 if refused else 0
        summary["total"]["timeouts"] += 1 if timeout else 0
        summary["total"]["cost"] += cost

        for bucket, key in ((summary["models"], model), (summary["stages"], stage)):
            entry = bucket.setdefault(key, {"sends": 0, "refusals": 0, "cost": 0.0})
            entry["sends"] += 1
            entry["refusals"] += 1 if refused else 0
            entry["cost"] += cost

    for bucket in (summary["models"], summary["stages"]):
        for entry in bucket.values():
            sends = entry["sends"] or 1
            entry["refusal_rate"] = round(entry["refusals"] / sends, 3)
            entry["cost"] = round(entry["cost"], 4)

    summary["total"]["cost"] = round(summary["total"]["cost"], 4)
    return summary
