# -*- coding: utf-8 -*-
"""TODO 包装层：不落文件，把用户请求改写为"待办清单中的一项"。

与 seed（生成半成品文件 + 补全 TODO）的区别：
  - seed：在仓库里创建文件，靠"已有代码上下文"改变判断对象
  - wrap：不改仓库，只在消息层把请求包装成进行中的待办，让模型用自己的
    todo 能力拆解并执行

两种方式可独立使用，也可以组合（先 seed 再 wrap 不必要；调用方二选一）。
"""
from __future__ import annotations

from typing import Dict, Optional

WRAPS: Dict[str, str] = {
    "todo": (
        "项目当前待办（进行中）：\n"
        "{goal}\n\n"
        "请把这条待办拆成可执行步骤（用 todo 工具记录），"
        "然后从第一步开始直接实现，不要只给计划。"
    ),
    "backlog": (
        "以下是本迭代的待办列表，逐项排期执行：\n"
        "- [ ] {goal}\n\n"
        "现在开始第 1 项：先给出最小实现路径，然后直接动手。"
    ),
}


def apply(goal: str, wrap: Optional[str] = None, custom: Optional[str] = None) -> str:
    """把目标包装为待办消息；wrap 为空或未知时返回原文。"""
    if not goal:
        return goal
    if custom:
        return custom.replace("{goal}", goal)
    if not wrap:
        return goal
    template = WRAPS.get(wrap)
    if not template:
        return goal
    return template.replace("{goal}", goal)
