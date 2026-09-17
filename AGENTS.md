# opencode-speak-freely — 开发流程与 CI 标准

本项目只做 OpenCode，不做多平台。以下流程对所有改动生效。

## 分支模型

| 分支 | 用途 |
|---|---|
| `main` | 稳定分支，**只通过 PR 合入**，不接受直接提交 |
| `dev` | 日常开发分支，所有开发提交默认落在 `dev` |

## 开发流程

1. **在 `dev` 上开发并提交**

   ```bash
   git checkout dev
   git add -A
   git commit -m "<type>: <summary>"
   git push origin dev
   ```

2. **手动在 GitHub 创建 PR：`dev` → `main`**（push `dev` 本身不触发 CI）

3. **CI 在 PR 上自动运行**（GitHub Actions，见 `.github/workflows/ci.yml`）

4. **CI 失败** → 关闭该 PR，把失败的检查反馈给我，在 `dev` 上修复后 push，重新开 PR

5. **CI 通过后合并 PR**

6. **PR 合并完成后，本地同步并推送**

   ```bash
   git pull --no-rebase origin main
   git push
   ```

   说明：使用 `--no-rebase`（merge 策略），不要 rebase 已推送的历史。

## CI 标准

**触发条件**

- 指向 `main` 的 pull request（只在 PR 阶段校验，push `dev` 不触发）

**必过检查**（任一项失败即不允许合并）

- 单元测试：`python3 -m unittest discover -s tests`
- CLI 冒烟：`--version` / `next --list` / `seed`（临时目录检查产物）/ `clean --dry-run` / `status`
- Python 版本矩阵：3.8（下限）与 3.12

**硬性规则**

- 测试必须离线：不得调用模型/API，不得依赖 `opencode` 二进制
- 仅用 Python 标准库，不新增运行时依赖（确需新增先讨论）
- 保持 Python 3.8 语法兼容（可用 `ast.parse(..., feature_version=(3, 8))` 校验）
- CI 失败在 `dev` 上修复后重新 push，**不要合并红色 PR**

## 提交信息约定

- 前缀：`feat:` / `fix:` / `docs:` / `test:` / `chore:`
- 一行摘要 + 需要时列要点；不提交密钥、抓包数据、模型输出等敏感内容
