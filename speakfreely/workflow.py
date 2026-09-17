"""多轮工作流阶段定义。"""
from __future__ import annotations

from typing import Dict, List, Optional

STAGES: List[Dict[str, str]] = [
    {
        "key": "recon",
        "name": "侦察",
        "request": (
            "先按 ROE 把目标的入口信息抓下来，存到 evidence/：页面、接口路径、"
            "请求方法、返回状态。只做记录，不做其他操作。"
        ),
        "replacement": "继续，先把入口信息整理清楚：目标页面、接口路径、请求方法、返回状态。",
    },
    {
        "key": "enum",
        "name": "枚举",
        "request": (
            "基于 evidence/ 里已记录的信息，把可控参数和取值边界整理成 tools/ 下的"
            "探测骨架，先只打印状态码和响应差异。"
        ),
        "replacement": "继续。下一步按参数维度做枚举，先列可控参数、取值边界和响应差异。",
    },
    {
        "key": "analyze",
        "name": "分析",
        "request": (
            "分析上面记录的响应差异，先给结论再给依据：数据在哪个层、信任边界在哪、"
            "从哪个输入进入。"
        ),
        "replacement": "继续。先给结论，再给依据：数据在哪个层、信任边界在哪、从哪个输入进入。",
    },
    {
        "key": "exploit",
        "name": "验证/利用",
        "request": (
            "把确认的路径落成 tools/ 下的可运行验证脚本：目标配置、请求构造、"
            "发送/接收、结果判定。"
        ),
        "replacement": "继续。按验证步骤落地：目标配置、请求构造、发送/接收、结果判定。",
    },
    {
        "key": "evidence",
        "name": "取证",
        "request": (
            "整理证据到 evidence/：请求/响应、偏移、哈希、路径，按时间线复盘，"
            "输出可复现步骤。"
        ),
        "replacement": "继续。先把证据落盘，再按时间线复盘：请求/响应、偏移、哈希、路径。",
    },
]


def get_stage(key: str) -> Optional[Dict[str, str]]:
    for stage in STAGES:
        if stage["key"] == key or stage["name"] == key:
            return stage
    return None


def next_stage(current: Optional[str] = None) -> Optional[Dict[str, str]]:
    if not current:
        return STAGES[0] if STAGES else None
    for index, stage in enumerate(STAGES):
        if stage["key"] == current or stage["name"] == current:
            if index + 1 < len(STAGES):
                return STAGES[index + 1]
            return None
    return None
