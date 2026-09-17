"""speakfreely 命令行入口。"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import List, Optional

from . import __version__, installer, paths, project, verify, workflow

OK = "✓"
WARN = "!"
FAIL = "✗"


def cmd_install(args: argparse.Namespace) -> int:
    print("== speakfreely 一键安装 ==")
    try:
        result = installer.install_global()
    except (OSError, ValueError) as exc:
        print("{} 全局提示词安装失败: {}".format(FAIL, exc))
        return 1

    label = {
        "installed": "已安装",
        "updated": "已更新（原文件已备份）",
        "unchanged": "已是最新",
    }[result["status"]]
    print("{} 全局提示词: {} — {}".format(OK, result["target"], label))
    if result.get("backup"):
        print("   备份: {}".format(result["backup"]))

    if not args.global_only:
        try:
            ws = installer.install_workspace()
        except (OSError, ValueError) as exc:
            print("{} 工作空间安装失败: {}".format(WARN, exc))
        else:
            print("{} 工作空间: {} — {}".format(OK, ws["target"], ws["status"]))
            print("   启动方式: cd ~/.opencode-ctf-workspace && opencode")

    if args.no_verify:
        print("{} 已跳过校验（--no-verify）".format(WARN))
        return 0

    print("正在校验上下文加载（调用 opencode，约 10-60 秒）...")
    check = verify.check_context(model=args.model)
    if not check["available"]:
        print("{} 未找到 opencode CLI，跳过校验".format(WARN))
        return 0
    if check["ok"]:
        print("{} 校验通过：模型上下文中已包含注入内容".format(OK))
        return 0
    print("{} 校验未通过，模型回答: {}".format(FAIL, check["answer"].strip() or "(空)"))
    print("   排查: 确认 OpenCode 版本、模型可用性，或稍后重试")
    return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    result = installer.uninstall_global()
    mapping = {
        "removed": "{} 已删除全局提示词: {}".format(OK, result["target"]),
        "missing": "{} 全局提示词未安装".format(WARN),
        "kept": "{} 内容与模板不一致，已保留: {}".format(WARN, result["target"]),
    }
    print(mapping[result["status"]])

    if not args.global_only:
        ws = installer.uninstall_workspace()
        if ws["status"] == "removed":
            print("{} 已删除工作空间提示词: {}".format(OK, ws["target"]))
        elif ws["status"] == "kept":
            print("{} 工作空间提示词非本项目内容，已保留: {}".format(WARN, ws["target"]))
        else:
            print("{} 工作空间提示词未安装".format(WARN))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = installer.status()
    print("== speakfreely 状态 ==")
    print("OpenCode CLI:   {}".format(state["opencode"] or "未找到"))
    print("会话核心:       {}（内置，不再依赖上游）".format(OK))

    gp = state["global_prompt"]
    mark = OK if gp["exists"] and gp["managed"] else (WARN if gp["exists"] else FAIL)
    print("{} 全局提示词:   {}{}".format(
        mark, gp["path"], "" if gp["managed"] or not gp["exists"] else "（内容非本项目模板）"
    ))

    wp = state["workspace_prompt"]
    print("{} 工作空间:     {}".format(OK if wp["exists"] else WARN, wp["path"]))

    pa = state["project_agents"]
    print("{} 当前项目 ROE: {}".format(OK if pa["exists"] else WARN, pa["path"]))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    result = project.init_project(
        directory=args.directory or os.getcwd(),
        name=args.name,
        target=args.target,
        authorization=args.authorization,
        force=args.force,
    )
    if result["status"] == "exists":
        print("{} {}".format(WARN, result["reason"]))
        return 1

    print("{} 已生成项目 ROE: {}".format(OK, result["target"]))
    if result.get("backup"):
        print("   原文件备份: {}".format(result["backup"]))
    print("   已创建: tools/ evidence/")
    if result["missing"]:
        print("{} 待填写: {}".format(WARN, ", ".join(result["missing"])))
    print("")
    print("下一步:")
    print("  1. 编辑 AGENTS.md 补全目标与授权信息")
    print("  2. 用桌面/CLI 打开该目录开新会话")
    print("  3. speakfreely next  获取第一轮请求文案")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    if args.list:
        print("工作流阶段:")
        for index, stage in enumerate(workflow.STAGES, 1):
            print("  {}. {} ({})".format(index, stage["key"], stage["name"]))
        return 0

    stage = (
        workflow.next_stage(args.after)
        if args.after
        else workflow.get_stage(args.stage or "recon")
    )
    if stage is None:
        print("{} 没有下一个阶段，或阶段不存在".format(WARN))
        return 1

    text = stage["replacement"] if args.replacement else stage["request"]
    print("== {} 阶段（{}） ==".format(stage["name"], stage["key"]))
    print(text)

    if args.copy:
        copied = _copy_to_clipboard(text)
        print("")
        print("{} 已复制到剪贴板".format(OK) if copied else "{} 复制失败".format(WARN))
    return 0


def _copy_to_clipboard(text: str) -> bool:
    for command in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b"]):
        if shutil.which(command[0]):
            try:
                subprocess.run(command, input=text.encode("utf-8"), check=True)
                return True
            except (OSError, subprocess.CalledProcessError):
                continue
    return False


def cmd_verify(args: argparse.Namespace) -> int:
    check = verify.check_context(
        marker=args.marker,
        directory=args.directory,
        model=args.model,
    )
    if not check["available"]:
        print("{} 未找到 opencode CLI".format(FAIL))
        return 1
    if check["ok"]:
        print("{} 校验通过".format(OK))
    else:
        print("{} 校验未通过".format(FAIL))
    print("模型回答: {}".format(check["answer"].strip() or "(空)"))
    return 0 if check["ok"] else 1


def cmd_clean(args: argparse.Namespace) -> int:
    from . import cleaner

    try:
        result = cleaner.clean_opencode(
            all_sessions=args.all,
            session=args.session,
            dry_run=args.dry_run,
            show_content=args.dry_run,
            clean_reasoning=True if args.clean_reasoning else None,
            replacement=args.replacement,
            stage=args.stage,
            db_path=args.db,
        )
    except Exception as exc:  # noqa: BLE001 - 顶层命令需要把错误变成可读输出
        if os.environ.get("SPEAKFREELY_DEBUG"):
            import traceback

            traceback.print_exc()
        print("{} 清理失败: {}".format(FAIL, exc))
        return 1

    if not result["sessions"]:
        print("{} {}".format(WARN, result["reason"] or "没有可处理的会话"))
        return 0

    for session in result["sessions"]:
        if session.get("error"):
            print("{} 会话 {}: 读取失败 — {}".format(WARN, session["id"], session["error"]))
            continue
        if not session["modified"]:
            print("{} 会话 {}: 无需修改".format(OK, session["id"]))
            continue

        print("{} 会话 {}: 检测到 {} 处修改".format(OK, session["id"], len(session["changes"])))
        for line in session["changes"]:
            print("   - {}".format(line))
        if args.dry_run:
            print("   (预览模式，未修改数据库)")
        else:
            print("   备份: {}".format(session.get("backup")))

    if args.dry_run:
        print("")
        print("确认无误后执行: speakfreely clean{}".format(" --all" if args.all else ""))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    from . import cleaner

    if args.backup:
        try:
            cleaner.restore_backup(args.backup, db_path=args.db)
        except Exception as exc:  # noqa: BLE001
            print("{} 恢复失败: {}".format(FAIL, exc))
            return 1
        print("{} 已从备份恢复: {}".format(OK, args.backup))
        return 0

    try:
        backups = cleaner.list_backups(db_path=args.db)
    except Exception as exc:  # noqa: BLE001
        print("{} 读取备份失败: {}".format(FAIL, exc))
        return 1

    if not backups:
        print("{} 没有可用备份".format(WARN))
        return 0

    print("可用备份（新→旧）:")
    for item in backups:
        print("  {}  {}  {}".format(item["mtime_str"], item["filename"], item["size"]))
    print("")
    print("恢复: speakfreely restore --backup <路径>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="speakfreely",
        description="OpenCode 低拒答一键配置（提示词分层 + 工作流 + 会话清理）",
    )
    parser.add_argument("--version", action="version", version="speakfreely {}".format(__version__))
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser("install", help="一键安装（全局 + 工作空间 + 校验）")
    p_install.add_argument("--global-only", action="store_true", help="只安装全局提示词")
    p_install.add_argument("--no-verify", action="store_true", help="跳过上下文校验")
    p_install.add_argument("--model", help="校验使用的模型（默认取 OpenCode 配置）")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="卸载本项目安装的提示词")
    p_uninstall.add_argument("--global-only", action="store_true")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_status = sub.add_parser("status", help="查看安装状态")
    p_status.set_defaults(func=cmd_status)

    p_init = sub.add_parser("init", help="为目标项目生成 ROE 脚手架")
    p_init.add_argument("directory", nargs="?", default=None, help="项目目录（默认当前目录）")
    p_init.add_argument("--name", help="项目名（默认目录名）")
    p_init.add_argument("--target", help="目标（域名/服务/样本路径）")
    p_init.add_argument("--authorization", help="授权依据")
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的 AGENTS.md（先备份）")
    p_init.set_defaults(func=cmd_init)

    p_next = sub.add_parser("next", help="输出工作流下一轮的请求文案")
    p_next.add_argument("stage", nargs="?", default=None, help="阶段: recon/enum/analyze/exploit/evidence")
    p_next.add_argument("--after", help="取该阶段之后的一轮")
    p_next.add_argument("--replacement", action="store_true", help="输出清理替换文案而不是请求文案")
    p_next.add_argument("--copy", action="store_true", help="复制到剪贴板")
    p_next.add_argument("--list", action="store_true", help="列出全部阶段")
    p_next.set_defaults(func=cmd_next)

    p_verify = sub.add_parser("verify", help="校验上下文加载")
    p_verify.add_argument("--marker", default=verify.DEFAULT_MARKER)
    p_verify.add_argument("--directory")
    p_verify.add_argument("--model")
    p_verify.set_defaults(func=cmd_verify)

    p_clean = sub.add_parser("clean", help="清理被拒会话（内置核心）")
    p_clean.add_argument("--all", action="store_true", help="处理全部会话")
    p_clean.add_argument("--session", help="只处理指定会话 ID")
    p_clean.add_argument("--dry-run", action="store_true", help="仅预览")
    p_clean.add_argument("--stage", help="使用工作流阶段的替换文案: recon/enum/analyze/exploit/evidence")
    p_clean.add_argument("--replacement", help="自定义替换文本")
    p_clean.add_argument("--clean-reasoning", action="store_true", help="同时移除 thinking/reasoning 内容")
    p_clean.add_argument("--db", help="指定 OpenCode 数据库路径（默认 ~/.local/share/opencode/opencode.db）")
    p_clean.set_defaults(func=cmd_clean)

    p_restore = sub.add_parser("restore", help="列出/恢复数据库备份")
    p_restore.add_argument("--list", action="store_true", help="列出全部备份")
    p_restore.add_argument("--backup", help="要恢复的备份路径")
    p_restore.add_argument("--db", help="指定 OpenCode 数据库路径")
    p_restore.set_defaults(func=cmd_restore)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
