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
| `speakfreely/runner.py` | `opencode run --format json` 调用与事件解析 |
| `speakfreely/auto.py` | 全自动循环（发送→检测→清理→重试→下一阶段） |
| `speakfreely/watch.py` | 后台监视并自动清理新拒绝（Desktop 用） |
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

## 两种自动模式

**A. `watch` — 配合 Desktop 的自动修复（推荐）**

在终端跑一条命令，然后在 Desktop 里正常聊天：

```bash
./scripts/speakfreely watch --project ~/project/<目标项目> --interval 5
```

- 每 5 秒扫描一次该项目的会话，**发现新的拒绝就自动替换成 prefill 文案**（自动备份）
- Desktop 里不用做任何额外操作：被拒后等几秒，直接发"继续"即可，模型读到的是已清理的历史
- 界面若仍显示旧文本，切到别的会话再切回来即可刷新；不影响模型实际读到的内容
- 想后台常驻：`nohup ./scripts/speakfreely watch --project <项目> > /tmp/sf-watch.log 2>&1 &`
- 先预览：`--dry-run`；只扫一轮：`--once`

**B. `auto` — 完全无人值守（CLI）**

```bash
./scripts/speakfreely auto ~/project/<目标项目> \
    --goal "梳理 <目标> 的注册流程接口与参数" \
    --models glm-5.2,kimi-k2.6,qwen3.8-max \
    --max-attempts 3

# 代码上下文模式（实测最有效，见 docs/research.md §0）：
./scripts/speakfreely auto ~/project/<目标项目> --goal "<任务目标>" --seed \
    --seed-template harness            # harness/web/binary/doc

# 预热 + 内容感知替换 + 引用上一轮（默认全开）：
./scripts/speakfreely auto ~/project/<目标项目> --goal "<任务目标>" \
    --prime 3 --prefill auto
```

- 按 recon → enum → analyze → exploit → evidence 自动推进
- 每轮调用 `opencode run`，用拒绝检测器（关键词 + 正则 + 可选 LLM 裁判）判断结果；被拒 → 自动清理该会话 → 自动重试（必要时轮换模型）
- 默认引用上一轮产出（Crescendo）：下一轮以"上一轮你已完成（摘要）：…"开头
- 单个阶段连续被拒达到上限或总发送数超预算就停下报告
- 日志落在 `<项目>/evidence/auto/<时间戳>/`，会话可在 Desktop 里打开继续
- 只打印计划不执行：`--dry-run`；限定阶段：`--stages recon,enum`
- `--seed`：先生成半成品文件（TODO 清单），第一轮改为"补全 TODO"
- `--prime N`：先建一个含 N 对示例问答的预热会话（many-shot）
- `--prefill auto`：被拒时的替换文案由 LLM 生成
- 关闭引用：`--no-crescendo`

**C. `seed` — 代码上下文模式（Desktop 也适用）**

```bash
./scripts/speakfreely seed ~/project/<目标项目> --goal "<任务目标>" --copy
# 在 Desktop 会话里粘贴剪贴板内容（"补全 tools/task_harness.py 的 TODO…"）
```

- 把任务意图写进半成品文件的 TODO，让代理做"就地补全"而不是"回答敏感问题"
- 实测：同一模型直接提问被拒 3 次，改为补全 TODO 后完整实现（glm-5.2 / kimi-k2.6 均可）
- 模板：`--template harness|web|binary|doc`（网络探测 / Web 页面 / 二进制样本 / 文档编辑）
- 真实文件模式：`--file existing.py` 在已有文件里追加带标记的 TODO（JAWS-1，效果更真实）

**D. `prime` / `report` — 预热与数据**

```bash
./scripts/speakfreely prime ~/project/<目标项目> --examples 3   # 注入示例历史的预热会话
./scripts/speakfreely report [--days 7]                          # 模型/阶段拒绝率统计
```

**检测与替换的可选增强（配置 `~/.config/speakfreely/config.json`）**

```json
{
  "judge":   { "enabled": true, "endpoint": "https://.../v1", "api_key": "sk-...", "model": "<便宜模型>" },
  "prefill": { "mode": "auto",  "endpoint": "https://.../v1", "api_key": "sk-...", "model": "<便宜模型>" }
}
```

- `judge`：关键词/正则漏检时用 LLM 兜底判定"是不是拒绝"，漏检样本记录到 `~/.config/speakfreely/misses.jsonl`
- `prefill`：被拒时的替换文案由 LLM 结合上下文生成"答案开头"，失败自动回退模板

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
