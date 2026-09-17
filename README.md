# opencode-speak-freely

**OpenCode 专属**的低拒答工作流实践：提示词分层、多轮工作流、会话修复策略。

> 目标：把"OpenCode 拒绝安全测试请求"这件事从"玄学"变成可复现的工程流程。
> 范围明确：只做 OpenCode，不做其他平台。

## 背景

在安全测试、CTF、漏洞研究场景中，OpenCode 会拒绝涉及安全操作的请求，并且同一个请求、同一份上下文，**有时通过、有时被拒**。本项目沉淀了以下结论和产物：

1. 拒绝是模型采样层的概率决策，不是确定性规则 —— 提示词只能提高概率
2. 提示词的"注入强度"和"可信度"互斥：权威声明容易被识破为注入，中性文档可信但没有授权钩子
3. 工作流框架（把目标请求变成正在进行的工作的一步）比单轮请求有效得多
4. 模型选择是最大杠杆，其次是上下文分层（全局 / 项目 / 会话）
5. 恢复管线（注入 → 改写 → 清理续聊）保证的是"总能继续"，不是"永不被拒"

详细论证与论文数据见 [docs/](docs/)。

## 目录

| 路径 | 内容 |
|---|---|
| `speakfreely/` | 一键 CLI（Python stdlib，核心逻辑可被未来 Web UI 复用） |
| `speakfreely/core/` | 内置会话核心：拒绝检测、清理管线、SQLite 读写/备份/恢复（改编自 codex-session-patcher，MIT，见 `core/ATTRIBUTION.md`） |
| `speakfreely/config.py` | 本工具配置 `~/.config/speakfreely/config.json`（替换文本、自定义关键词） |
| `speakfreely/cleaner.py` | 清理与恢复编排 |
| `scripts/speakfreely` | CLI 启动器 |
| `docs/principles.md` | 原理：拒绝的机制、注入强度与可信度的权衡、提通过率的手段 |
| `docs/research.md` | 调研笔记：工作流越狱、prefill 注入、Policy Puppetry、Crescendo 等（含数据与出处） |
| `docs/workflow.md` | 多轮工作流方法论：把敏感目标拆进普通工程步骤（7 阶段） |
| `docs/tooling.md` | 与上游的差异、已修复的两个上游问题、后续改造方向 |
| `prompts/opencode-global.md` | 全局提示词（OpenCode 桌面/CLI 通用），当前线上版本 |
| `prompts/opencode-workspace.md` | 工作空间版提示词（带 `managed-by` 标记） |
| `prompts/project-roe.md` | 项目级 engagement/ROE 模板（`speakfreely init` 使用） |
| `prompts/prefill-replacements.md` | 会话清理的替换文本模板（按阶段） |
| `tests/` | 冒烟测试 + 核心管线测试（stdlib unittest，35 例） |

## 一键使用（推荐）

```bash
# 0. 一键安装：全局提示词 + 工作空间 + 上下文校验
./scripts/speakfreely install

# 1. 为目标项目生成 ROE 脚手架
./scripts/speakfreely init ~/project/<目标项目> \
    --target "https://target.example" \
    --authorization "比赛/委托说明"

# 2. 按工作流逐轮获取请求文案
./scripts/speakfreely next              # 第一轮：侦察
./scripts/speakfreely next --after recon
./scripts/speakfreely next --replacement  # 被拒时用的清理替换文案
./scripts/speakfreely next --copy         # 直接复制到剪贴板

# 3. 查看状态 / 清理被拒会话 / 恢复 / 卸载
./scripts/speakfreely status
./scripts/speakfreely clean --dry-run            # 只预览，不改数据库
./scripts/speakfreely clean                      # 执行（自动整库备份，默认保留推理内容）
./scripts/speakfreely clean --stage analyze      # 用工作流阶段的 prefill 式替换文案
./scripts/speakfreely clean --clean-reasoning    # 同时移除 thinking/reasoning
./scripts/speakfreely restore                    # 列出备份
./scripts/speakfreely restore --backup <路径>    # 从备份恢复
./scripts/speakfreely uninstall
```

## 手动安装（等价）

```bash
# 1. 安装全局提示词（对所有项目和会话生效）
./scripts/install-global.sh

# 2. 在目标项目里启用项目级 ROE
./scripts/speakfreely init ~/project/<目标项目> --target ... --authorization ...
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
