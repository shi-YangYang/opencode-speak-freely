"""安装 / 卸载 / 状态检测。"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import paths

WORKSPACE_CONFIG = (
    "{\n"
    '  "$schema": "https://opencode.ai/config.json",\n'
    '  "instructions": ["AGENTS.md"]\n'
    "}\n"
)


def _template(filename: str) -> str:
    return paths.load_text(os.path.join(paths.prompts_dir(), filename))


def install_global(
    source: Optional[str] = None,
    target: Optional[str] = None,
) -> Dict[str, Any]:
    """安装全局 AGENTS.md。返回 {status, target, backup}。"""
    source = source or os.path.join(paths.prompts_dir(), "opencode-global.md")
    target = target or paths.global_prompt_path()
    content = paths.load_text(source)

    if os.path.islink(target):
        raise ValueError("目标是指向别处的符号链接，已停止: {}".format(target))

    backup = None
    if os.path.exists(target):
        if paths.load_text(target) == content:
            return {"status": "unchanged", "target": target, "backup": None}
        backup = paths.backup_file(target)

    paths.atomic_write(target, content)
    status = "updated" if backup else "installed"
    return {"status": status, "target": target, "backup": backup}


def install_workspace(
    source: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    """安装工作空间（AGENTS.md + opencode.json）。"""
    source = source or os.path.join(paths.prompts_dir(), "opencode-workspace.md")
    directory = directory or paths.workspace_dir()
    prompt_path = os.path.join(directory, "AGENTS.md")
    config_path = os.path.join(directory, "opencode.json")
    content = paths.load_text(source)

    os.makedirs(directory, exist_ok=True)

    backup = None
    prompt_status = "unchanged"
    if os.path.exists(prompt_path):
        if paths.load_text(prompt_path) != content:
            backup = paths.backup_file(prompt_path)
            prompt_status = "updated"
    else:
        prompt_status = "installed"
    paths.atomic_write(prompt_path, content)

    config_status = "unchanged"
    if not os.path.exists(config_path):
        paths.atomic_write(config_path, WORKSPACE_CONFIG)
        config_status = "installed"
    elif paths.load_text(config_path) != WORKSPACE_CONFIG:
        config_status = "kept"

    return {
        "status": prompt_status,
        "target": prompt_path,
        "backup": backup,
        "config": config_path,
        "config_status": config_status,
    }


def uninstall_global(target: Optional[str] = None) -> Dict[str, Any]:
    """仅当内容与本项目模板一致时删除全局文件。"""
    target = target or paths.global_prompt_path()
    template = os.path.join(paths.prompts_dir(), "opencode-global.md")

    if not os.path.exists(target):
        return {"status": "missing", "target": target}

    if paths.same_content(target, template):
        os.remove(target)
        return {"status": "removed", "target": target}

    return {"status": "kept", "target": target, "reason": "内容与模板不一致"}


def uninstall_workspace(directory: Optional[str] = None) -> Dict[str, Any]:
    directory = directory or paths.workspace_dir()
    prompt_path = os.path.join(directory, "AGENTS.md")
    template = os.path.join(paths.prompts_dir(), "opencode-workspace.md")

    if not os.path.exists(prompt_path):
        return {"status": "missing", "target": prompt_path}

    if paths.same_content(prompt_path, template):
        os.remove(prompt_path)
        status = "removed"
    else:
        status = "kept"

    config_path = os.path.join(directory, "opencode.json")
    if os.path.exists(config_path) and paths.load_text(config_path) == WORKSPACE_CONFIG:
        try:
            os.remove(config_path)
        except OSError:
            pass

    try:
        os.rmdir(directory)
    except OSError:
        pass

    return {"status": status, "target": prompt_path}


def _patcher_library_available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("codex_session_patcher") is not None
    except (ImportError, ValueError):
        return False


def status(directory: Optional[str] = None) -> Dict[str, Any]:
    """汇总当前安装状态。"""
    from . import verify

    global_path = paths.global_prompt_path()
    workspace_prompt = paths.workspace_prompt_path()
    project_agents = os.path.join(directory or os.getcwd(), "AGENTS.md")

    return {
        "opencode": verify.find_opencode(),
        "codex_patcher": paths.find_command("codex-patcher"),
        "patcher_library": _patcher_library_available(),
        "global_prompt": {
            "path": global_path,
            "exists": os.path.exists(global_path),
            "managed": paths.same_content(
                global_path, os.path.join(paths.prompts_dir(), "opencode-global.md")
            )
            if os.path.exists(global_path)
            else False,
        },
        "workspace_prompt": {
            "path": workspace_prompt,
            "exists": os.path.exists(workspace_prompt),
        },
        "project_agents": {
            "path": project_agents,
            "exists": os.path.exists(project_agents),
        },
    }
