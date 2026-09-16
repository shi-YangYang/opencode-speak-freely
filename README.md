# opencode-speak-freely

OpenCode / 编码代理的**低拒答工作流实践**沉淀：提示词分层、多轮工作流、会话修复策略。

> 目标：把"AI 拒绝安全测试请求"这件事从"玄学"变成可复现的工程流程。

## 背景

在安全测试、CTF、漏洞研究场景中，编码代理（OpenCode、Codex CLI、Claude Code）会拒绝涉及安全操作的请求，并且同一个请求、同一份上下文，**有时通过、有时被拒**。本项目沉淀了以下结论和产物：

1. 拒绝是模型采样层的概率决策，不是确定性规则 —— 提示词只能提高概率
2. 提示词的"注入强度"和"可信度"互斥：权威声明容易被识破为注入，中性文档可信但没有授权钩子
3. 工作流框架（把目标请求变成正在进行的工作的一步）比单轮请求有效得多
4. 模型选择是最大杠杆，其次是上下文分层（全局 / 项目 / 会话）
5. 恢复管线（注入 → 改写 → 清理续聊）保证的是"总能继续"，不是"永不被拒"

详细论证与论文数据见 [docs/](docs/)。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/principles.md` | 原理：拒绝的机制、注入强度与可信度的权衡、提通过率的手段 |
| `docs/research.md` | 调研笔记：工作流越狱、prefill 注入、Policy Puppetry、Crescendo 等（含数据与出处） |
| `docs/workflow.md` | 多轮工作流方法论：把敏感目标拆进普通工程步骤（7 阶段） |
| `docs/tooling.md` | 对 codex-session-patcher 的改造方案：prefill 式替换、AI 改写提示词、多轮引导 |
| `prompts/opencode-global.md` | 全局提示词（OpenCode 桌面/CLI 通用），当前线上版本 |
| `prompts/opencode-workspace.md` | 工作空间版提示词（带 `managed-by` 标记，兼容 codex-session-patcher 卸载） |
| `prompts/project-roe.md` | 项目级 engagement/ROE 模板（放到目标项目根目录作为 AGENTS.md） |
| `prompts/prefill-replacements.md` | 会话清理的替换文本模板（按阶段） |
| `scripts/install-global.sh` | 安装全局提示词到 `~/.config/opencode/AGENTS.md`（带备份） |
| `scripts/uninstall-global.sh` | 卸载全局提示词（校验标记，不碰用户文件） |

## 快速开始

```bash
# 1. 安装全局提示词（对所有项目和会话生效）
./scripts/install-global.sh

# 2. 在目标项目里启用项目级 ROE（把 {{...}} 换成真实信息）
cp prompts/project-roe.md ~/project/<目标项目>/AGENTS.md
$EDITOR ~/project/<目标项目>/AGENTS.md

# 3. 用 codex-session-patcher 处理被拒会话
codex-patcher --format opencode --latest --dry-run --show-content   # 预览
codex-patcher --format opencode --latest                            # 执行（自动备份）
```

## 分层策略

```
┌─────────────────────────────────────────┐
│ 全局 AGENTS.md   中性工作文档，防识破     │  ~/.config/opencode/AGENTS.md
├─────────────────────────────────────────┤
│ 项目 AGENTS.md   engagement/ROE，具体授权 │  <项目>/AGENTS.md
├─────────────────────────────────────────┤
│ 会话内容         按工作流逐轮推进          │  聊天 + 会话清理工具
├─────────────────────────────────────────┤
│ 模型选择         拒审阈值差异最大的一层     │  OpenCode 模型切换
└─────────────────────────────────────────┘
```

## 边界

- 仅用于**授权范围内**的安全测试（CTF、委托测试、自有服务、比赛靶场）
- 这套方法提高的是通过率，不保证任何单次请求一定通过
- 上游模型和平台会持续修补已知注入话术，效果随版本变化
