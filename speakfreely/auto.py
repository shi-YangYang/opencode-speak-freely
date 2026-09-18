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
from . import planner as planner_module
from . import prefill as prefill_module
from . import wrap as wrap_module
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
    seed_template: str = "harness",
    seed_path: Optional[str] = None,
    seed_plan: bool = False,
    seed_kind: Optional[str] = None,
    planner_fn: Any = None,
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
    seed_plan_note: Optional[str] = None
    if seed:
        if dry_run:
            seed_plan_note = "将用模板 {} 生成 tools/ 下的半成品文件".format(seed_template)
        else:
            from . import seed as seed_module

            plan = None
            prefer = "plan" if seed_kind == "doc" or seed_template == "plan" else None
            if seed_plan and not seed_path:
                planner_fn = planner_fn or planner_module.from_config(config)
                if planner_fn is None:
                    emit("自动规划已关闭（设置页可开启），使用默认模板")
                if planner_fn is not None:
                    plan = planner_fn.plan(goal or "", project_dir, prefer=prefer)
                    if plan and plan.get("template"):
                        emit("本地规划: {}（模板 {}，规则匹配，不调用模型）".format(
                            plan["path"], plan["template"]))
                    elif plan:
                        emit("LLM 规划: {}（{} 步）".format(plan["path"], len(plan["steps"])))
                    elif getattr(planner_fn, "last_refused", False):
                        emit("规划失败：模型拒绝该目标（内容原因），使用默认模板")
                        emit("  模型原话: {}".format(_summarize(planner_fn.last_raw, 160)))
                    else:
                        raw = _summarize(getattr(planner_fn, "last_raw", "") or "(空)", 160)
                        emit("规划失败：模型未返回可解析的 JSON，使用默认模板 —— {}".format(raw))
            if plan and plan.get("template"):
                seeded = seed_module.scaffold(
                    project_dir=project_dir,
                    goal=goal or "Task harness",
                    name=seed_name,
                    template=plan["template"],
                    path=plan["path"],
                )
            else:
                seeded = seed_module.scaffold(
                    project_dir=project_dir,
                    goal=goal or "Task harness",
                    name=seed_name,
                    template=seed_template,
                    path=seed_path,
                    plan=plan,
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
                "seed": seed_plan_note,
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
                emit("[{}] 完成（{} 字符）：{}".format(
                    stage["key"], len(output_text), _summarize(output_text, 200)
                ))
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


def send_to_session(
    project_dir: str,
    session_id: str,
    prompt: str,
    model: Optional[str] = None,
    max_attempts: int = 3,
    timeout: int = 900,
    db_path: Optional[str] = None,
    runner: Optional[Callable[..., Dict[str, Any]]] = None,
    clean_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    detector: Optional[RefusalDetector] = None,
    judge: Any = None,
    prefill_fn: Any = None,
    retry_prompt: str = DEFAULT_RETRY_PROMPT,
    on_event: Optional[Callable[[str], None]] = None,
    auto_clean: bool = True,
    seed: bool = False,
    seed_template: Optional[str] = None,
    seed_path: Optional[str] = None,
    seed_plan: bool = False,
    seed_kind: Optional[str] = None,
    planner_fn: Any = None,
    wrap: Optional[str] = None,
) -> Dict[str, Any]:
    """向已有会话发一条消息；被拒时自动清理并重试（auto_clean=False 时只报告）。

    seed=True 时把目标写进半成品文件，实际发送"补全 TODO"而不是原始请求。
    

    Returns:
        {ok, text, attempts, sends, cost, session_id, backup, reason}
    """
    project_dir = os.path.realpath(os.path.expanduser(project_dir))
    runner = runner or run_open
    clean_fn = clean_fn or _default_clean_fn
    detector = detector or RefusalDetector()
    config = config_module.load_config()
    if judge is None:
        judge = judge_module.from_config(config)
    if prefill_fn is None:
        prefill_fn = prefill_module.from_config(config)

    def emit(message: str) -> None:
        if on_event:
            on_event(message)

    sends = 0
    cost = 0.0
    attempts = 0
    current = prompt
    backup = None

    if seed:
        from . import seed as seed_module

        plan = None
        prefer = "plan" if seed_kind == "doc" or seed_template == "plan" else None
        if seed_plan and not seed_path:
            planner_fn = planner_fn or planner_module.from_config(config)
            if planner_fn is None:
                emit("自动规划已关闭（设置页可开启），使用默认模板")
            if planner_fn is not None:
                plan = planner_fn.plan(prompt, project_dir, prefer=prefer)
                if plan and plan.get("template"):
                    emit("本地规划: {}（模板 {}，规则匹配，不调用模型）".format(
                        plan["path"], plan["template"]))
                elif plan:
                    emit("LLM 规划: {}（{} 步）".format(plan["path"], len(plan["steps"])))
                elif getattr(planner_fn, "last_refused", False):
                    emit("规划失败：模型拒绝该目标（内容原因），使用默认模板")
                    emit("  模型原话: {}".format(_summarize(planner_fn.last_raw, 160)))
                else:
                    raw = _summarize(getattr(planner_fn, "last_raw", "") or "(空)", 160)
                    emit("规划失败：模型未返回可解析的 JSON，使用默认模板 —— {}".format(raw))
        if plan and plan.get("template"):
            seeded = seed_module.scaffold(
                project_dir=project_dir,
                goal=prompt,
                template=plan["template"],
                path=plan["path"],
            )
        else:
            seeded = seed_module.scaffold(
                project_dir=project_dir,
                goal=prompt,
                template=seed_template or ("plan" if seed_kind == "doc" else seed_module.pick_template(prompt)),
                path=seed_path,
                plan=plan,
            )
        emit("已生成半成品: {}".format(seeded["path"]))
        emit("实际发送: {}".format(seeded["prompt"]))
        current = seeded["prompt"]
    elif wrap:
        current = wrap_module.apply(prompt, wrap)
        emit("已应用 TODO 包装（{}），实际发送: {}".format(wrap, _summarize(current, 160)))

    while True:
        result = runner(
            current,
            directory=project_dir,
            model=model,
            session=session_id,
            timeout=timeout,
        )
        sends += 1
        cost += float(result.get("cost") or 0)
        text = result.get("text") or ""

        if result.get("timeout"):
            attempts_module.log_attempt(
                {
                    "project": project_dir,
                    "stage": "send",
                    "model": model or "",
                    "refused": False,
                    "cleaned": False,
                    "timeout": True,
                    "cost": float(result.get("cost") or 0),
                    "text_len": len(text),
                }
            )
            attempts += 1
            if attempts >= max_attempts:
                return {
                    "ok": False, "text": text, "attempts": attempts,
                    "sends": sends, "cost": cost, "session_id": session_id,
                    "backup": backup, "reason": "超时",
                }
            continue

        refused = detector.detect(text)
        if not refused and judge is not None and judge_module.should_judge(text):
            if judge.is_refusal(text) is True:
                judge_module.record_miss(text, source="send")
                refused = True

        attempts_module.log_attempt(
            {
                "project": project_dir,
                "stage": "send",
                "model": model or "",
                "refused": refused,
                "cleaned": False,
                "timeout": False,
                "cost": float(result.get("cost") or 0),
                "text_len": len(text),
            }
        )

        if not refused:
            emit("模型回复（{} 字符）：{}".format(len(text), _summarize(text, 200)))
            return {
                "ok": True, "text": text, "attempts": attempts,
                "sends": sends, "cost": cost, "session_id": session_id,
                "backup": backup, "reason": None,
            }

        emit("检测到拒绝（{} 字符）：{}".format(len(text), _summarize(text, 120)))
        if not auto_clean:
            return {
                "ok": False, "text": text, "attempts": attempts,
                "sends": sends, "cost": cost, "session_id": session_id,
                "backup": backup, "reason": "被拒绝（未清理，auto_clean=false）",
            }
        replacement = None
        if prefill_fn is not None:
            replacement = prefill_fn.generate(prompt, text)
        clean_result = clean_fn(session_id, replacement or "", db_path)
        entry = (clean_result.get("sessions") or [{}])[0]
        backup = entry.get("backup") or backup
        if entry.get("error"):
            emit("清理失败: {}".format(entry["error"]))
        else:
            replaced = entry.get("changes") or []
            emit("已清理：{}；备份：{}".format(
                "；".join(replaced) if replaced else "无变更", backup or "（未创建）"
            ))
            emit("重试并发送：{}".format(retry_prompt))

        attempts += 1
        if attempts >= max_attempts:
            return {
                "ok": False, "text": text, "attempts": attempts,
                "sends": sends, "cost": cost, "session_id": session_id,
                "backup": backup,
                "reason": "连续被拒 {} 次".format(max_attempts),
            }
        current = retry_prompt
