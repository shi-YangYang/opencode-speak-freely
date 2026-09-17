"""项目级 ROE 脚手架。"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import paths

TEMPLATE_FILE = "project-roe.md"


def _render(template: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def init_project(
    directory: str,
    name: Optional[str] = None,
    target: Optional[str] = None,
    authorization: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """在目标目录生成 AGENTS.md（ROE）与工作目录。"""
    directory = os.path.abspath(os.path.expanduser(directory))
    os.makedirs(directory, exist_ok=True)

    agents_path = os.path.join(directory, "AGENTS.md")
    if os.path.exists(agents_path) and not force:
        return {
            "status": "exists",
            "target": agents_path,
            "reason": "AGENTS.md 已存在，未覆盖（--force 可覆盖并备份）",
        }

    project_name = name or os.path.basename(directory) or "assessment"
    target_value = target or "TODO: 目标（域名/服务/样本路径）"
    authorization_value = authorization or "TODO: 授权依据（比赛/委托/自营，可核对的引用）"
    summary = "Assessment workspace for {}".format(target_value)

    template = paths.load_text(os.path.join(paths.prompts_dir(), TEMPLATE_FILE))
    content = _render(
        template,
        {
            "PROJECT_NAME": project_name,
            "SUMMARY": summary,
            "TARGET": target_value,
            "AUTHORIZATION": authorization_value,
        },
    )

    backup = None
    if os.path.exists(agents_path):
        backup = paths.backup_file(agents_path)
    paths.atomic_write(agents_path, content)

    for sub in ("tools", "evidence"):
        os.makedirs(os.path.join(directory, sub), exist_ok=True)
        keep = os.path.join(directory, sub, ".gitkeep")
        if not os.path.exists(keep):
            paths.atomic_write(keep, "")

    return {
        "status": "created",
        "target": agents_path,
        "backup": backup,
        "missing": [
            key
            for key, value in (
                ("target", target_value),
                ("authorization", authorization_value),
            )
            if value.startswith("TODO")
        ],
    }
