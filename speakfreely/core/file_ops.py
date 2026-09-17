# -*- coding: utf-8 -*-
"""原子写入与备份。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

PathLike = Union[str, os.PathLike]


class UnsafeFileError(ValueError):
    """目标不是可安全管理的普通文件。"""


def require_regular_or_missing(path: PathLike) -> Optional[os.stat_result]:
    target = Path(path)
    try:
        info = os.lstat(str(target))
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeFileError("目标不是普通文件: {}".format(target))
    return info


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(str(directory), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(
    path: PathLike,
    content: str,
    mode: Optional[int] = 0o600,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = require_regular_or_missing(target)
    final_mode = mode if mode is not None else (
        stat.S_IMODE(current.st_mode) if current is not None else 0o600
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=".{}.".format(target.name), suffix=".tmp", dir=str(target.parent)
    )
    temp_path = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, final_mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp_path), str(target))
        if os.name != "nt":
            os.chmod(str(target), final_mode)
        _fsync_directory(target.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: PathLike, data: Any, mode: Optional[int] = 0o600) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, payload, mode=mode)


def reserve_unique_backup_path(path: PathLike) -> str:
    """独占预留一个不重名的备份路径（空文件）。"""
    source = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    attempt = 0
    while True:
        extra = "" if attempt == 0 else ".{}".format(attempt)
        backup = Path("{}.{}{}.bak".format(source, timestamp, extra))
        try:
            fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            attempt += 1
            continue
        os.close(fd)
        return str(backup)
