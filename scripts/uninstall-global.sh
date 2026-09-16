#!/bin/bash
# 卸载全局 AGENTS.md（仅当内容与本项目模板一致时删除）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE="$PROJECT_DIR/prompts/opencode-global.md"
TARGET="$HOME/.config/opencode/AGENTS.md"

if [ ! -f "$TARGET" ]; then
    echo "未安装: $TARGET"
    exit 0
fi

if [ -f "$SOURCE" ] && cmp -s "$SOURCE" "$TARGET"; then
    rm "$TARGET"
    echo "已删除: $TARGET"
else
    echo "内容与项目模板不一致，已保留: $TARGET"
    echo "（确认要删除请手动执行: rm \"$TARGET\"）"
    exit 1
fi
