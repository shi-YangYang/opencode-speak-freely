# -*- coding: utf-8 -*-
"""本地 Web UI（纯标准库，零依赖）。

- 只监听回环地址，无鉴权：仅本机使用
- 前端在 speakfreely/static/index.html
- 运行任务放在后台线程，前端轮询 /api/job 拿日志
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import auto as auto_module
from . import cleaner as cleaner_module
from . import installer
from . import paths
from . import seed as seed_module
from . import watch as watch_module
from .core import DEFAULT_OPENCODE_DB, OpenCodeDBAdapter, OpenCodeFormat, RefusalDetector

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_WRITE_LOCK = threading.Lock()


# ─── 任务管理 ────────────────────────────────────────────────────────────────

class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, params: Dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "params": params,
                "status": "running",
                "log": [],
                "result": None,
                "started": time.strftime("%H:%M:%S"),
                "finished": None,
            }
        return job_id

    def log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["log"].append("[{}] {}".format(time.strftime("%H:%M:%S"), message))

    def finish(self, job_id: str, status: str, result: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["status"] = status
                job["result"] = result
                job["finished"] = time.strftime("%H:%M:%S")

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item["started"], reverse=True)
            return [
                {k: v for k, v in job.items() if k != "log"} for job in jobs[:limit]
            ]


JOBS = JobManager()
WATCH_STOPS: Dict[str, threading.Event] = {}


# ─── 数据接口 ────────────────────────────────────────────────────────────────

def _adapter(db_path: Optional[str]) -> OpenCodeDBAdapter:
    return OpenCodeDBAdapter(db_path or DEFAULT_OPENCODE_DB)


def list_projects(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    sessions = _adapter(db_path).list_sessions()
    grouped: Dict[str, Dict[str, Any]] = {}
    for session in sessions:
        directory = session.get("directory") or ""
        if not directory or not os.path.isdir(directory):
            continue
        entry = grouped.setdefault(
            directory,
            {"directory": directory, "sessions": 0, "last": session.get("mtime_str", ""), "exists": os.path.isdir(directory)},
        )
        entry["sessions"] += 1
    return sorted(grouped.values(), key=lambda item: item["last"], reverse=True)


def list_sessions(project: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    target = os.path.realpath(os.path.expanduser(project))
    sessions = _adapter(db_path).list_sessions()
    return [
        {
            "id": session["session_id"],
            "title": session.get("title") or "(无标题)",
            "updated": session.get("mtime_str", ""),
        }
        for session in sessions
        if os.path.realpath(session.get("directory") or "") == target
    ]


_MODELS_CACHE: Dict[str, Any] = {"time": 0.0, "models": []}
_MODELS_TTL = 60.0


def list_models(path: Optional[str] = None) -> List[str]:
    """优先用 `opencode models`（含内置 opencode-go），失败回退配置文件。"""
    now = time.time()
    if _MODELS_CACHE["models"] and now - _MODELS_CACHE["time"] < _MODELS_TTL:
        return list(_MODELS_CACHE["models"])

    models = _models_from_cli()
    if not models:
        models = _models_from_config(path)

    if models:
        _MODELS_CACHE["time"] = now
        _MODELS_CACHE["models"] = list(models)
    return models


def _models_from_cli() -> List[str]:
    binary = paths.find_command("opencode")
    if not binary:
        return []
    try:
        completed = subprocess.run(
            [binary, "models"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    models = set()
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if "/" in line and " " not in line:
            models.add(line)
    return sorted(models)


def _models_from_config(path: Optional[str] = None) -> List[str]:
    candidates = [
        path,
        os.path.expanduser("~/.config/opencode/opencode.jsonc"),
        os.path.expanduser("~/.config/opencode/opencode.json"),
    ]
    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as stream:
                raw = stream.read()
        except OSError:
            continue
        data = _parse_jsonc(raw)
        if not isinstance(data, dict):
            continue
        models = []
        for provider_id, provider in (data.get("provider") or {}).items():
            for model_id in (provider.get("models") or {}).keys():
                models.append("{}/{}".format(provider_id, model_id))
        if models:
            return sorted(set(models))
    return []


def list_stages() -> List[Dict[str, str]]:
    from . import workflow

    return [
        {
            "key": stage["key"],
            "name": stage.get("name", stage["key"]),
            "description": stage.get("description", ""),
        }
        for stage in workflow.STAGES
    ]


def _parse_jsonc(raw: str) -> Optional[Any]:
    text = _strip_jsonc(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _strip_jsonc(raw: str) -> str:
    """去掉 // 与 /* */ 注释、行尾多余逗号；字符串内的内容不处理。"""
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


def session_preview(session_id: str, db_path: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    adapter = _adapter(db_path)
    messages = adapter.load_session_messages(session_id)
    strategy = OpenCodeFormat()
    detector = RefusalDetector()

    refusals = 0
    preview = []
    for index, message in enumerate(messages):
        role = message.get("type")
        text = _message_text(message, strategy)
        if not text.strip():
            continue  # 工具调用/推理/步骤等无文本消息不展示
        is_refusal = role == "assistant" and detector.detect(text)
        if is_refusal:
            refusals += 1
        preview.append({"index": index, "role": role, "text": text[:1500], "refusal": is_refusal})

    return {
        "refusals": refusals,
        "messages": preview[-limit:],
        "total": len(messages),
        "shown": len(preview),
    }


def session_refusals(session_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """列出某会话里所有被判定为拒绝的助手消息。"""
    adapter = _adapter(db_path)
    messages = adapter.load_session_messages(session_id)
    strategy = OpenCodeFormat()
    detector = RefusalDetector()

    refusals = []
    for index, message in enumerate(messages):
        if message.get("type") != "assistant":
            continue
        text = _message_text(message, strategy)
        if text and detector.detect(text):
            refusals.append(
                {
                    "index": index,
                    "line": index + 1,
                    "excerpt": text[:300],
                    "length": len(text),
                }
            )
    return {"session": session_id, "refusals": refusals, "total": len(messages)}


def scan_project_refusals(project: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """扫描某项目下所有会话，返回含拒绝的会话及条数。"""
    results = []
    for session in list_sessions(project, db_path):
        try:
            data = session_refusals(session["id"], db_path)
        except Exception:  # noqa: BLE001 - 单个会话失败不影响扫描
            continue
        if data["refusals"]:
            results.append(
                {
                    "id": session["id"],
                    "title": session["title"],
                    "updated": session["updated"],
                    "count": len(data["refusals"]),
                }
            )
    return results


def session_message(session_id, index, db_path=None):
    """按绝对索引取单条消息的完整文本（供前端模态框）。"""
    adapter = _adapter(db_path)
    messages = adapter.load_session_messages(session_id)
    if index < 0 or index >= len(messages):
        raise IndexError("消息索引超出范围: {}".format(index))

    message = messages[index]
    role = message.get("type")
    strategy = OpenCodeFormat()
    text = _message_text(message, strategy)
    display = _message_display(message, strategy)
    refusal = role == "assistant" and bool(text) and RefusalDetector().detect(text)
    return {"index": index, "role": role, "text": text, "display": display, "refusal": refusal}


_PART_LABELS = {
    "thinking": "推理",
    "tool": "工具调用",
    "step-start": "步骤开始",
    "step-finish": "步骤结束",
    "file": "文件",
    "reasoning": "推理",
}


def _message_display(message: Dict[str, Any], strategy: OpenCodeFormat) -> str:
    """有文本返回文本；没有文本（工具调用/推理/步骤）返回内容摘要。"""
    text = _message_text(message, strategy)
    if text.strip():
        return text

    content = message.get("message", {}).get("content", [])
    if not isinstance(content, list) or not content:
        return "（空消息）"

    counts: Dict[str, int] = {}
    for item in content:
        if isinstance(item, dict):
            kind = item.get("type", "?")
            counts[kind] = counts.get(kind, 0) + 1

    if not counts:
        return "（空消息）"
    parts = []
    for key, label in _PART_LABELS.items():
        if counts.get(key):
            parts.append("{} ×{}".format(label, counts[key]))
    for key, value in counts.items():
        if key not in _PART_LABELS:
            parts.append("{} ×{}".format(key, value))
    return "（无文本：" + " · ".join(parts) + "）"


def _message_text(message: Dict[str, Any], strategy: OpenCodeFormat) -> str:
    if message.get("type") == "assistant":
        return strategy.extract_text_content(message)
    content = message.get("message", {}).get("content", [])
    if isinstance(content, str):
        return content
    return "\n".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


# ─── 任务执行 ────────────────────────────────────────────────────────────────

def start_run(params: Dict[str, Any], db_path: Optional[str] = None) -> str:
    job_id = JOBS.create("run", params)

    def target() -> None:
        try:
            mode = params.get("mode") or "vibe"
            project = params.get("project") or os.getcwd()
            model = params.get("model") or None
            goal = (params.get("goal") or "").strip()
            stages = params.get("stages") or None
            if isinstance(stages, str):
                stages = [item.strip() for item in stages.split(",") if item.strip()] or None

            if not goal:
                raise ValueError("目标不能为空")

            if mode == "vibe":
                result = auto_module.run_auto(
                    project_dir=project,
                    goal=goal,
                    stages=stages,
                    models=[model] if model else None,
                    max_attempts=int(params.get("max_attempts") or 3),
                    timeout=int(params.get("timeout") or 900),
                    dry_run=bool(params.get("dry_run")),
                    seed=True,
                    seed_template=seed_module.pick_template(goal),
                    prime=int(params.get("prime") or 0),
                    prefill_mode=params.get("prefill") or None,
                    crescendo=not bool(params.get("no_crescendo")),
                    on_event=lambda line: JOBS.log(job_id, line),
                )
            elif mode == "send":
                session_id = params.get("session") or ""
                if not session_id:
                    raise ValueError("未选择会话")
                result = auto_module.send_to_session(
                    project_dir=project,
                    session_id=session_id,
                    prompt=goal,
                    model=model,
                    max_attempts=int(params.get("max_attempts") or 3),
                    timeout=int(params.get("timeout") or 900),
                    on_event=lambda line: JOBS.log(job_id, line),
                )
            elif mode == "seed":
                seeded = seed_module.scaffold(
                    project_dir=project,
                    goal=goal,
                    template=seed_module.pick_template(goal),
                )
                JOBS.log(job_id, "已生成: {}".format(seeded["path"]))
                JOBS.log(job_id, "发送这段：{}".format(seeded["prompt"]))
                result = seeded
            else:
                raise ValueError("未知模式: {}".format(mode))

            JOBS.log(job_id, "完成")
            JOBS.finish(job_id, "done", result)
        except Exception as exc:  # noqa: BLE001 - 任务失败只影响该任务
            JOBS.log(job_id, "失败: {}".format(exc))
            JOBS.finish(job_id, "error", {"error": str(exc)})

    threading.Thread(target=target, name="speakfreely-job", daemon=True).start()
    return job_id


def start_clean(
    session_id: str,
    project: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
    selected: Optional[List[int]] = None,
    replacement: Optional[str] = None,
    stage: Optional[str] = None,
    prefill: Optional[str] = None,
) -> Dict[str, Any]:
    kwargs = {
        "dry_run": dry_run,
        "db_path": db_path,
        "show_content": True,
        "selected_lines": [int(item) for item in selected] if selected else None,
        "replacement": replacement,
        "stage": stage,
        "prefill_mode": prefill,
    }
    if session_id:
        return cleaner_module.clean_opencode(session=session_id, **kwargs)
    if project:
        return cleaner_module.clean_opencode(all_sessions=True, **kwargs)
    raise ValueError("需要会话或项目")


def start_watch(project: str, db_path: Optional[str] = None) -> str:
    target = os.path.realpath(os.path.expanduser(project))
    if target in WATCH_STOPS:
        return "already-running"
    stop_event = threading.Event()
    WATCH_STOPS[target] = stop_event

    def target_fn() -> None:
        try:
            watch_module.watch(
                project_dir=target,
                db_path=db_path,
                should_stop=stop_event.is_set,
            )
        finally:
            WATCH_STOPS.pop(target, None)

    threading.Thread(target=target_fn, name="speakfreely-watch", daemon=True).start()
    return "started"


def stop_watch(project: str) -> str:
    target = os.path.realpath(os.path.expanduser(project))
    stop_event = WATCH_STOPS.get(target)
    if not stop_event:
        return "not-running"
    stop_event.set()
    return "stopping"


# ─── HTTP ────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "speakfreely"
    db_path: Optional[str] = None

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 静默默认日志
        pass

    # 工具 ────────────────────────────────

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status=status)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _static(self, name: str) -> None:
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            self._error("not found", status=404)
            return
        with open(path, "rb") as stream:
            body = stream.read()
        content_type = "text/html; charset=utf-8" if name.endswith(".html") else "application/octet-stream"
        self._send(200, body, content_type)

    # GET ────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                return self._static("index.html")
            if parsed.path == "/api/status":
                state = installer.status()
                return self._json(
                    {
                        "opencode": state["opencode"],
                        "global_prompt": state["global_prompt"],
                        "workspace_prompt": state["workspace_prompt"],
                        "watch": sorted(WATCH_STOPS.keys()),
                    }
                )
            if parsed.path == "/api/projects":
                return self._json(list_projects(self.db_path))
            if parsed.path == "/api/sessions":
                project = (query.get("project") or [""])[0]
                if not project:
                    return self._error("缺少 project 参数")
                return self._json(list_sessions(project, self.db_path))
            if parsed.path == "/api/models":
                return self._json(list_models())
            if parsed.path == "/api/stages":
                return self._json(list_stages())
            if parsed.path == "/api/session":
                session_id = (query.get("id") or [""])[0]
                if not session_id:
                    return self._error("缺少 id 参数")
                return self._json(session_preview(session_id, self.db_path))
            if parsed.path == "/api/refusals":
                session_id = (query.get("session") or [""])[0]
                project = (query.get("project") or [""])[0]
                if session_id:
                    return self._json(session_refusals(session_id, self.db_path))
                if project:
                    return self._json(scan_project_refusals(project, self.db_path))
                return self._error("需要 session 或 project 参数")
            if parsed.path == "/api/backups":
                from . import cleaner as cleaner_module

                return self._json(cleaner_module.list_backups(db_path=self.db_path))
            if parsed.path == "/api/message":
                session_id = (query.get("id") or [""])[0]
                index_raw = (query.get("index") or [""])[0]
                if not session_id or not index_raw.isdigit():
                    return self._error("需要 id 和数字 index 参数")
                return self._json(session_message(session_id, int(index_raw), self.db_path))
            if parsed.path == "/api/job":
                job_id = (query.get("id") or [""])[0]
                job = JOBS.get(job_id)
                if job is None:
                    return self._error("任务不存在", status=404)
                return self._json(job)
            if parsed.path == "/api/jobs":
                return self._json(JOBS.list())
            return self._error("not found", status=404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=500)

    # POST ───────────────────────────────

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json()
        try:
            if parsed.path == "/api/run":
                with _WRITE_LOCK:
                    job_id = start_run(body, self.db_path)
                return self._json({"job": job_id})
            if parsed.path == "/api/clean":
                result = start_clean(
                    session_id=(body.get("session") or "").strip(),
                    project=(body.get("project") or "").strip() or None,
                    dry_run=bool(body.get("dry_run")),
                    db_path=self.db_path,
                    selected=body.get("selected") or None,
                    replacement=(body.get("replacement") or "").strip() or None,
                    stage=(body.get("stage") or "").strip() or None,
                    prefill=(body.get("prefill") or "").strip() or None,
                )
                return self._json(result)
            if parsed.path == "/api/restore":
                from . import cleaner as cleaner_module

                backup = (body.get("backup") or "").strip()
                if not backup:
                    return self._error("缺少 backup 路径")
                cleaner_module.restore_backup(backup, db_path=self.db_path)
                return self._json({"ok": True, "restored": backup})
            if parsed.path == "/api/watch":
                project = (body.get("project") or "").strip()
                if not project:
                    return self._error("缺少 project")
                action = body.get("action") or "start"
                return self._json({"status": start_watch(project, self.db_path) if action == "start" else stop_watch(project)})
            return self._error("not found", status=404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=500)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8788,
    db_path: Optional[str] = None,
) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"db_path": db_path})
    return ThreadingHTTPServer((host, port), handler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8788,
    db_path: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    server = create_server(host=host, port=port, db_path=db_path)
    url = "http://{}:{}".format(host, server.server_address[1])
    print("speakfreely Web UI: {}".format(url))
    print("按 Ctrl+C 停止")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
