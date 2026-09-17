# -*- coding: utf-8 -*-
"""全自动循环：发送 → 检测拒绝 → 清理 → 重试 → 进入下一阶段。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from . import attempts as attempts_module
from . import cleaner as cleaner_module
from . import config as config_module
from . import judge as judge_module
from . import prefill as prefill_module
from . import workflow
from .core import OpenCodeDBAdapter, RefusalDetector
from .runner import run_open

DEFAULT_RETRY_PROMPT = "继续"

SUMMARY_LIMIT = 400


def _summarize(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """把上一轮产出压成摘要（优先在句末截断）。"""
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    window = compact[:limit]
    for separator in ("。", ".", "\n", "；", ";"):
        index = window.rfind(separator)
        if index > limit // 2:
            return window[: index + 1]
    return window + "…"


def _default_clean_fn(session_id: str, replacement: str, db_path: Optional[str]) -> Dict[str, Any]:
    return cleaner_module.clean_opencode(
        session=session_id,
        replacement=replacement,
        db_path=db_path,
    )


def _log_dir(project_dir: str, dry_run: bool) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(project_dir, "evidence", "auto", stamp)


def _write_log(log_dir: Optional[str], name: str, payload: Any) -> Optional[str]:
    if not log_dir:
        return None
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name)
    with open(path, "w", encoding="utf-8") as stream:
        if isinstance(payload, str):
            stream.write(payload)
        else:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    return path


def run_auto(
    project_dir: str,
    goal: Optional[str] = None,
    stages: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    max_attempts: int = 3,
    max_sends: int = 30,
    timeout: int = 600,
    dry_run: bool = False,
    db_path: Optional[str] = None,
    runner: Optional[Callable[..., Dict[str, Any]]] = None,
    clean_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    detector: Optional[RefusalDetector] = None,
    retry_prompt: str = DEFAULT_RETRY_PROMPT,
    on_event: Optional[Callable[[str], None]] = None,
    seed: bool = False,
    seed_name: Optional[str] = None,
    judge: Any = None,
    prefill_fn: Any = None,
    prefill_mode: Optional[str] = None,
    crescendo: bool = True,
    prime: int = 0,
) -> Dict[str, Any]:
    """按工作流阶段自动推进，被拒时自动清理并重试。

    Returns:
        {ok, stages: [{stage, attempts, cost, session_id, logs}], sends, cost, reason}
    """
    project_dir = os.path.realpath(os.path.expanduser(project_dir))
    runner = runner or run_open
    clean_fn = clean_fn or _default_clean_fn
    detector = detector or RefusalDetector()
    config = config_module.load_config()
    if judge is None:
        judge = judge_module.from_config(config)
    if prefill_fn is None:
        prefill_fn = prefill_module.from_config(config, mode=prefill_mode)

    def emit(message: str) -> None:
        if on_event:
            on_event(message)

    if stages:
        stage_defs = []
        for key in stages:
            found = workflow.get_stage(key)
            if found is None:
                raise ValueError("未知阶段: {}".format(key))
            stage_defs.append(found)
    else:
        stage_defs = list(workflow.STAGES)

    models = models or []

    seed_prompt: Optional[str] = None
    if seed:
        from . import seed as seed_module

        seeded = seed_module.scaffold(
            project_dir=project_dir,
            goal=goal or "Task harness",
            name=seed_name,
        )
        seed_prompt = seeded["prompt"]
        emit("已生成半成品: {}".format(seeded["path"]))

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "plan": {
                "project": project_dir,
                "goal": goal,
                "stages": [stage["key"] for stage in stage_defs],
                "models": models,
                "max_attempts": max_attempts,
                "max_sends": max_sends,
                "seed": seed_prompt,
            },
            "stages": [],
            "sends": 0,
            "cost": 0.0,
            "reason": "dry-run",
        }

    log_dir = _log_dir(project_dir, dry_run)
    session_id: Optional[str] = None
    sends = 0
    total_cost = 0.0
    last_summary = ""
    stage_reports: List[Dict[str, Any]] = []

    if prime:
        from . import prime as prime_module

        primed = prime_module.create_primed_session(
            project_dir, examples=prime, db_path=db_path
        )
        session_id = primed["session_id"]
        emit(
            "已创建预热会话: {}（{} 条示例消息）".format(
                session_id, primed["messages"]
            )
        )

    for stage_index, stage in enumerate(stage_defs, 1):
        if stage_index == 1 and seed_prompt:
            prompt = seed_prompt
        else:
            prompt = stage["request"]
            if goal and stage_index == 1:
                prompt = "目标：{}\n\n{}".format(goal, prompt)
            if crescendo and last_summary:
                prompt = "上一轮你已完成（摘要）：{}\n\n{}".format(last_summary, prompt)

        report = {
            "stage": stage["key"],
            "attempts": 0,
            "cost": 0.0,
            "session_id": None,
            "logs": [],
        }

        while True:
            if sends >= max_sends:
                stage_reports.append(report)
                return _summary(False, stage_reports, sends, total_cost, "达到总发送上限", session_id)

            model = models[report["attempts"] % len(models)] if models else None
            emit("[{}] 发送（第 {} 次尝试{}）...".format(
                stage["key"], report["attempts"] + 1,
                "，模型 {}".format(model) if model else "",
            ))

            result = runner(
                prompt,
                directory=project_dir,
                model=model,
                session=session_id,
                timeout=timeout,
            )
            sends += 1
            total_cost += float(result.get("cost") or 0)
            session_id = result.get("session_id") or session_id
            report["session_id"] = session_id

            log_path = _write_log(
                log_dir,
                "stage{}-attempt{}.json".format(stage_index, report["attempts"] + 1),
                result,
            )
            if log_path:
                report["logs"].append(log_path)

            if result.get("timeout"):
                attempts_module.log_attempt(
                    {
                        "project": project_dir,
                        "stage": stage["key"],
                        "model": model or "",
                        "refused": False,
                        "cleaned": False,
                        "timeout": True,
                        "cost": float(result.get("cost") or 0),
                        "text_len": len(result.get("text") or ""),
                    }
                )
                report["attempts"] += 1
                if report["attempts"] >= max_attempts:
                    stage_reports.append(report)
                    return _summary(
                        False, stage_reports, sends, total_cost,
                        "阶段 {} 超时".format(stage["key"]), session_id,
                    )
                continue

            output_text = result.get("text") or ""
            refused = detector.detect(output_text)
            if not refused and judge is not None and judge_module.should_judge(output_text):
                if judge.is_refusal(output_text) is True:
                    judge_module.record_miss(output_text, source="auto")
                    refused = True

            attempts_module.log_attempt(
                {
                    "project": project_dir,
                    "stage": stage["key"],
                    "model": model or "",
                    "refused": refused,
                    "cleaned": False,
                    "timeout": False,
                    "cost": float(result.get("cost") or 0),
                    "text_len": len(output_text),
                }
            )

            if not refused:
                emit("[{}] 完成（{} 字符）".format(stage["key"], len(output_text)))
                last_summary = _summarize(output_text)
                break

            emit("[{}] 检测到拒绝，清理会话后重试".format(stage["key"]))
            if not session_id:
                session_id = _latest_session_for(project_dir, db_path)
                report["session_id"] = session_id

            if session_id:
                replacement_for_clean = stage["replacement"]
                if prefill_fn is not None:
                    generated = prefill_fn.generate(prompt, output_text)
                    if generated:
                        replacement_for_clean = generated
                        emit("    已生成内容感知 prefill")
                clean_result = clean_fn(session_id, replacement_for_clean, db_path)
                entry = (clean_result.get("sessions") or [{}])[0]
                if entry.get("backup"):
                    emit("    已备份: {}".format(entry["backup"]))
                if entry.get("error"):
                    emit("    清理失败: {}".format(entry["error"]))

            report["attempts"] += 1
            if report["attempts"] >= max_attempts:
                stage_reports.append(report)
                return _summary(
                    False, stage_reports, sends, total_cost,
                    "阶段 {} 连续被拒 {} 次".format(stage["key"], max_attempts), session_id,
                )
            prompt = retry_prompt

        stage_reports.append(report)

    return _summary(True, stage_reports, sends, total_cost, None, session_id)


def _summary(
    ok: bool,
    stage_reports: List[Dict[str, Any]],
    sends: int,
    cost: float,
    reason: Optional[str],
    session_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "stages": stage_reports,
        "sends": sends,
        "cost": cost,
        "reason": reason,
        "session_id": session_id,
    }


def _latest_session_for(project_dir: str, db_path: Optional[str]) -> Optional[str]:
    try:
        adapter = OpenCodeDBAdapter(db_path) if db_path else OpenCodeDBAdapter()
        sessions = adapter.list_sessions()
    except Exception:  # noqa: BLE001
        return None
    target = os.path.realpath(project_dir)
    for item in sessions:
        if os.path.realpath(item.get("directory") or "") == target:
            return item["session_id"]
    return sessions[0]["session_id"] if sessions else None
