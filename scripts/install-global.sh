#!/bin/bash
# 安装全局 AGENTS.md 到 OpenCode 配置目录（macOS/Linux）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE="$PROJECT_DIR/prompts/opencode-global.md"
TARGET_DIR="$HOME/.config/opencode"
TARGET="$TARGET_DIR/AGENTS.md"

if [ ! -f "$SOURCE" ]; then
    echo "错误: 找不到源文件 $SOURCE"
    exit 1
fi

mkdir -p "$TARGET_DIR"

if [ -f "$TARGET" ]; then
    if cmp -s "$SOURCE" "$TARGET"; then
        echo "已是最新，无需更新: $TARGET"
        exit 0
    fi
    BACKUP="$TARGET.$(date +%Y%m%d_%H%M%S).bak"
    cp "$TARGET" "$BACKUP"
    echo "已备份原文件: $BACKUP"
fi

cp "$SOURCE" "$TARGET"
echo "已安装: $TARGET"
echo ""
echo "提示: 新会话自动生效；已在进行的会话在下次发消息时检测到变更并更新。"
echo "卸载: ./scripts/uninstall-global.sh"
