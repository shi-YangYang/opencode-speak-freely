"""路径解析与安全文件操作。"""
from __future__ import annotations

import os
import tempfile
import time
from typing import Optional


def project_root() -> str:
    """仓库根目录（本包所在目录的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def prompts_dir() -> str:
    return os.path.join(project_root(), "prompts")


def global_prompt_path() -> str:
    return os.path.expanduser("~/.config/opencode/AGENTS.md")


def workspace_dir() -> str:
    return os.path.expanduser("~/.opencode-ctf-workspace")


def workspace_prompt_path() -> str:
    return os.path.join(workspace_dir(), "AGENTS.md")


def workspace_config_path() -> str:
    return os.path.join(workspace_dir(), "opencode.json")


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def backup_file(path: str) -> str:
    """时间戳备份，返回备份路径。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    candidate = "{}.{}.bak".format(path, stamp)
    counter = 1
    while os.path.exists(candidate):
        candidate = "{}.{}.{}.bak".format(path, stamp, counter)
        counter += 1
    with open(path, "rb") as source, open(candidate, "wb") as target:
        target.write(source.read())
    return candidate


def atomic_write(path: str, content: str, mode: int = 0o600) -> None:
    """写临时文件后原子替换，权限默认 0600。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix=".speakfreely.", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def same_content(a: str, b: str) -> bool:
    try:
        with open(a, "r", encoding="utf-8") as f1, open(b, "r", encoding="utf-8") as f2:
            return f1.read() == f2.read()
    except OSError:
        return False


def find_command(name: str) -> Optional[str]:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    fallback = os.path.expanduser(os.path.join("~/.local/bin", name))
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    return None
