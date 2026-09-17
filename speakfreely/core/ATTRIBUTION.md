# Attribution

`speakfreely/core` 的部分代码改编自 **codex-session-patcher**（MIT License）：
<https://github.com/ryfineZ/codex-session-patcher>

被改编的模块：

| 本仓库 | 上游对应 | 说明 |
|---|---|---|
| `core/detector.py` | `core/detector.py` | 拒绝检测的两级策略 |
| `core/patcher.py` | `core/patcher.py` | 清理管线（已针对 OpenCode 结构简化） |
| `core/sqlite_store.py` | `core/sqlite_adapter.py` | OpenCode SQLite 读写、备份、恢复 |
| `core/file_ops.py` | `file_ops.py` | 原子写入与备份 |
| `core/constants.py` | `core/constants.py` | 关键词表（默认替换文本已改为 prefill 式） |

上游 MIT 声明（`pyproject.toml`: `license = {text = "MIT"}`，无署名版权行）。
后续修改与缺陷修复由本仓库维护。

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
