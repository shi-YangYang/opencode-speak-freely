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
            prefill_mode=args.prefill,
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


def cmd_auto(args: argparse.Namespace) -> int:
    from . import auto as auto_module

    stages = [item.strip() for item in args.stages.split(",")] if args.stages else None
    models = [item.strip() for item in args.models.split(",")] if args.models else None

    try:
        result = auto_module.run_auto(
            project_dir=args.directory or os.getcwd(),
            goal=args.goal,
            stages=stages,
            models=models,
            max_attempts=args.max_attempts,
            max_sends=args.max_sends,
            timeout=args.timeout,
            dry_run=args.dry_run,
            seed=args.seed,
            seed_template=args.seed_template,
            prefill_mode=args.prefill,
            crescendo=not args.no_crescendo,
            prime=args.prime,
            on_event=lambda line: print(line, flush=True),
        )
    except KeyboardInterrupt:
        print("")
        print("{} 已中断".format(WARN))
        return 130

    print("")
    if result.get("dry_run"):
        for key, value in result["plan"].items():
            print("{}: {}".format(key, value))
        return 0

    for stage in result["stages"]:
        print(
            "  阶段 {}: {} 次尝试，{} 处日志".format(
                stage["stage"], stage["attempts"] + 1, len(stage["logs"])
            )
        )
    if result["ok"]:
        print("{} 全部完成：{} 次发送，花费 {:.4f}".format(OK, result["sends"], result["cost"]))
        if result.get("session_id"):
            print("   会话: {}（可在 Desktop 打开继续）".format(result["session_id"]))
        return 0

    print("{} 中止: {}".format(FAIL, result["reason"]))
    print("   已发送 {} 次，花费 {:.4f}".format(result["sends"], result["cost"]))
    if result.get("session_id"):
        print("   会话: {}（可在 Desktop 查看/接管）".format(result["session_id"]))
    return 1


def cmd_watch(args: argparse.Namespace) -> int:
    from . import watch as watch_module

    print("监视中（{}）... Ctrl+C 停止".format(args.project or "全部项目"))
    try:
        result = watch_module.watch(
            project_dir=args.project,
            interval=args.interval,
            settle_seconds=args.settle,
            once=args.once,
            dry_run=args.dry_run,
            clean_reasoning=args.clean_reasoning,
            on_event=lambda line: print(line, flush=True),
        )
    except KeyboardInterrupt:
        print("")
        print("{} 已停止".format(WARN))
        return 0

    print("扫描 {} 轮，{} {} 条".format(
        result["scans"],
        "检测到" if args.dry_run else "替换",
        len(result["cleaned"]),
    ))
    for item in result["cleaned"]:
        print("  {} -> {}".format(item["session"], item.get("backup")))
    for error in result["errors"]:
        print("{} {}".format(WARN, error))
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from . import seed as seed_module

    if args.file:
        result = seed_module.scaffold_file(
            project_dir=args.directory or os.getcwd(),
            file_path=args.file,
            goal=args.goal or "Task harness",
            name=args.name,
        )
    else:
        result = seed_module.scaffold(
            project_dir=args.directory or os.getcwd(),
            goal=args.goal or "Task harness",
            name=args.name,
            force=args.force,
            template=args.template,
        )
    if result["status"] == "exists":
        print("{} 已存在，未覆盖（--force 可重建）: {}".format(WARN, result["path"]))
    else:
        print("{} 已生成半成品: {}".format(OK, result["path"]))

    print("")
    print("在会话里发送这段（代码上下文模式）：")
    print(result["prompt"])
    if args.copy:
        copied = _copy_to_clipboard(result["prompt"])
        print("")
        print("{} 已复制到剪贴板".format(OK) if copied else "{} 复制失败".format(WARN))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from . import attempts as attempts_module

    summary = attempts_module.summarize(days=args.days)
    total = summary["total"]
    if not total["sends"]:
        print("{} 还没有尝试记录（跑一次 auto 后就有了）".format(WARN))
        return 0

    rate = total["refusals"] / total["sends"]
    print("== 尝试统计（最近 {}）==".format("{} 天".format(args.days) if args.days else "全部"))
    print("发送 {} 次 | 拒绝 {} 次（{:.0%}）| 超时 {} | 花费 {:.4f}".format(
        total["sends"], total["refusals"], rate, total["timeouts"], total["cost"]
    ))
    print("")
    print("按模型:")
    for model, entry in sorted(
        summary["models"].items(), key=lambda item: -item[1]["sends"]
    ):
        print("  {:<28} 发送 {:>3}  拒绝 {:>3}（{:.0%}）".format(
            model, entry["sends"], entry["refusals"], entry["refusal_rate"]
        ))
    print("")
    print("按阶段:")
    for stage, entry in sorted(summary["stages"].items()):
        print("  {:<10} 发送 {:>3}  拒绝 {:>3}（{:.0%}）".format(
            stage, entry["sends"], entry["refusals"], entry["refusal_rate"]
        ))
    return 0


def cmd_prime(args: argparse.Namespace) -> int:
    from . import prime as prime_module

    try:
        result = prime_module.create_primed_session(
            project_dir=args.directory or os.getcwd(),
            examples=args.examples,
            ask=args.ask,
            db_path=args.db,
        )
    except Exception as exc:  # noqa: BLE001
        print("{} 创建预热会话失败: {}".format(FAIL, exc))
        return 1

    print("{} 已创建预热会话: {}".format(OK, result["session_id"]))
    print("   目录: {}".format(result["directory"]))
    print("   消息: {} 条（示例 {} 对{}）".format(
        result["messages"], args.examples,
        " + 你的请求" if args.ask else "",
    ))
    print("")
    print("继续方式：")
    print("  Desktop: 打开该目录即可看到该会话")
    print("  CLI:     opencode run --dir <目录> -s {} \"<你的请求>\"".format(result["session_id"]))
    return 0


def cmd_vibe(args: argparse.Namespace) -> int:
    """一句话目标 -> 全自动跑完（seed 骨架 + 全阶段 + 自动清理重试）。"""
    from . import auto as auto_module
    from . import seed as seed_module

    goal = args.goal
    template = args.template or seed_module.pick_template(goal)
    models = [item.strip() for item in args.models.split(",")] if args.models else None

    print("== vibe 模式 ==")
    print("目标: {}".format(goal))
    print("模板: {}".format(template))
    print("模型: {}".format(", ".join(models) if models else "配置默认"))
    print("")

    try:
        result = auto_module.run_auto(
            project_dir=args.project or os.getcwd(),
            goal=goal,
            stages=[item.strip() for item in args.stages.split(",")] if args.stages else None,
            models=models,
            max_attempts=args.max_attempts,
            max_sends=args.max_sends,
            timeout=args.timeout,
            dry_run=args.dry_run,
            seed=True,
            seed_template=template,
            prime=args.prime,
            prefill_mode=args.prefill,
            crescendo=not args.no_crescendo,
            on_event=lambda line: print(line, flush=True),
        )
    except KeyboardInterrupt:
        print("")
        print("{} 已中断".format(WARN))
        return 130

    print("")
    if result.get("dry_run"):
        for key, value in result["plan"].items():
            print("{}: {}".format(key, value))
        return 0

    if result["ok"]:
        print("{} vibe 完成：{} 次发送，花费 {:.4f}".format(
            OK, result["sends"], result["cost"]
        ))
        if result.get("session_id"):
            print("   会话: {}（Desktop 打开项目即可继续）".format(result["session_id"]))
        return 0

    print("{} 中止: {}".format(FAIL, result["reason"]))
    print("   已发送 {} 次，花费 {:.4f}".format(result["sends"], result["cost"]))
    if result.get("session_id"):
        print("   会话: {}（可换模型重试）".format(result["session_id"]))
    return 1


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
    p_clean.add_argument("--prefill", choices=["template", "auto"], help="替换文案来源：template 模板 / auto 由 LLM 生成")
    p_clean.set_defaults(func=cmd_clean)

    p_restore = sub.add_parser("restore", help="列出/恢复数据库备份")
    p_restore.add_argument("--list", action="store_true", help="列出全部备份")
    p_restore.add_argument("--backup", help="要恢复的备份路径")
    p_restore.add_argument("--db", help="指定 OpenCode 数据库路径")
    p_restore.set_defaults(func=cmd_restore)

    p_seed = sub.add_parser("seed", help="生成半成品代码文件（补全 TODO 模式）")
    p_seed.add_argument("directory", nargs="?", default=None, help="项目目录（默认当前目录）")
    p_seed.add_argument("--goal", required=True, help="任务目标，写入文件 docstring")
    p_seed.add_argument("--name", help="模块名（默认取模板名）")
    p_seed.add_argument("--template", choices=["harness", "web", "binary", "doc"],
                        default="harness", help="模板类型（默认 harness）")
    p_seed.add_argument("--file", help="在真实文件里追加 TODO 块（JAWS-1 模式）")
    p_seed.add_argument("--force", action="store_true", help="已存在时重建")
    p_seed.add_argument("--copy", action="store_true", help="复制补全提示到剪贴板")
    p_seed.set_defaults(func=cmd_seed)

    p_auto = sub.add_parser("auto", help="全自动推进工作流（被拒自动清理重试）")
    p_auto.add_argument("directory", nargs="?", default=None, help="项目目录（默认当前目录）")
    p_auto.add_argument("--goal", help="本次目标，注入第一轮文案")
    p_auto.add_argument("--stages", help="逗号分隔的阶段，如 recon,enum（默认全部）")
    p_auto.add_argument("--models", help="逗号分隔的模型轮换表，如 glm-5.2,kimi-k2.6")
    p_auto.add_argument("--max-attempts", type=int, default=3, help="每阶段最多尝试次数（默认 3）")
    p_auto.add_argument("--max-sends", type=int, default=30, help="总发送上限（默认 30）")
    p_auto.add_argument("--timeout", type=int, default=900, help="单次调用超时秒数（默认 900）")
    p_auto.add_argument("--dry-run", action="store_true", help="只打印计划")
    p_auto.add_argument("--seed", action="store_true", help="先生成半成品文件，用补全 TODO 作为第一轮")
    p_auto.add_argument("--seed-template", choices=["harness", "web", "binary", "doc"],
                        default="harness", help="seed 使用的模板")
    p_auto.add_argument("--prefill", choices=["template", "auto"], help="被拒时的替换文案来源")
    p_auto.add_argument("--no-crescendo", action="store_true", help="不引用上一轮产出（默认引用）")
    p_auto.add_argument("--prime", type=int, default=0, help="先创建 N 对示例的预热会话（many-shot）")
    p_auto.set_defaults(func=cmd_auto)

    p_prime = sub.add_parser("prime", help="创建预热会话（many-shot 示例历史）")
    p_prime.add_argument("directory", nargs="?", default=None, help="项目目录（默认当前目录）")
    p_prime.add_argument("--examples", type=int, default=3, help="示例问答对数（默认 3，最多 4）")
    p_prime.add_argument("--ask", help="在预热历史末尾附上你的请求")
    p_prime.add_argument("--db", help="指定 OpenCode 数据库路径")
    p_prime.set_defaults(func=cmd_prime)

    p_vibe = sub.add_parser("vibe", help="一句话目标：自动 seed + 全阶段推进 + 清理重试")
    p_vibe.add_argument("goal", help="自然语言目标（写进半成品文件，不直接发给模型）")
    p_vibe.add_argument("--project", help="项目目录（默认当前目录）")
    p_vibe.add_argument("--template", choices=["harness", "web", "binary", "doc"],
                        help="骨架模板（默认按目标自动选择）")
    p_vibe.add_argument("--models", help="逗号分隔的模型轮换表")
    p_vibe.add_argument("--prime", type=int, default=0, help="预热示例对数（many-shot）")
    p_vibe.add_argument("--prefill", choices=["template", "auto"], help="替换文案来源")
    p_vibe.add_argument("--stages", help="逗号分隔的阶段（默认全部 5 个）")
    p_vibe.add_argument("--no-crescendo", action="store_true", help="不引用上一轮产出")
    p_vibe.add_argument("--max-attempts", type=int, default=3, help="每阶段最多尝试次数")
    p_vibe.add_argument("--max-sends", type=int, default=30, help="总发送上限")
    p_vibe.add_argument("--timeout", type=int, default=900, help="单次调用超时秒数")
    p_vibe.add_argument("--dry-run", action="store_true", help="只打印计划")
    p_vibe.set_defaults(func=cmd_vibe)

    p_report = sub.add_parser("report", help="尝试统计：模型/阶段的发送与拒绝率")
    p_report.add_argument("--days", type=int, help="只看最近 N 天")
    p_report.set_defaults(func=cmd_report)

    p_watch = sub.add_parser("watch", help="后台监视并自动清理新拒绝（Desktop 用）")
    p_watch.add_argument("--project", help="只监视该目录的项目（默认全部）")
    p_watch.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒（默认 5）")
    p_watch.add_argument("--settle", type=float, default=3.0, help="消息静默多久才处理（默认 3）")
    p_watch.add_argument("--once", action="store_true", help="只扫一轮")
    p_watch.add_argument("--dry-run", action="store_true", help="只报告不修改")
    p_watch.add_argument("--clean-reasoning", action="store_true", help="同时移除推理内容")
    p_watch.set_defaults(func=cmd_watch)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
