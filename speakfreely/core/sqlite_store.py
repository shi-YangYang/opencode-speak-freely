# -*- coding: utf-8 -*-
"""OpenCode SQLite 存储层。改编自 codex-session-patcher（MIT），见 ATTRIBUTION.md。

相比上游重写了 save_session_messages 的映射逻辑：按 parts 与 content 的出现
顺序显式配对，避免上游 text_idx 循环的隐式状态。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from .file_ops import require_regular_or_missing, reserve_unique_backup_path

logger = logging.getLogger(__name__)

DEFAULT_OPENCODE_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")

_CONVERTED_PART_TYPES = ("tool", "step-start", "step-finish", "file")


class OpenCodeDBAdapter:
    """OpenCode 数据库读写、备份与恢复。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_OPENCODE_DB

    # ─── 连接 ──────────────────────────────────────────────────────────────

    def _connect(self, readonly: bool = True) -> sqlite3.Connection:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError("OpenCode 数据库不存在: {}".format(self.db_path))

        if readonly:
            # WAL 模式且缺少 -shm/-wal（例如 .backup 出来的副本）时，mode=ro 会失败；
            # 回退到普通连接 + query_only，SQLite 可自行创建 WAL 索引且不允许写入数据。
            try:
                conn = sqlite3.connect("file:{}?mode=ro".format(self.db_path), uri=True)
                conn.execute("SELECT 1")
            except sqlite3.OperationalError:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA query_only=1")
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")

        conn.row_factory = sqlite3.Row
        return conn

    # ─── 会话 ──────────────────────────────────────────────────────────────

    def list_sessions(self) -> List[Dict[str, Any]]:
        conn = self._connect(readonly=True)
        try:
            cursor = conn.execute(
                """
                SELECT s.id, s.title, s.directory, s.time_created, s.time_updated
                FROM session s
                ORDER BY s.time_updated DESC
                """
            )
            sessions = []
            for row in cursor:
                updated = row["time_updated"]
                if updated and updated > 1e12:
                    updated = updated / 1000.0
                stamp = datetime.fromtimestamp(updated)
                sessions.append(
                    {
                        "session_id": row["id"],
                        "title": row["title"] or "",
                        "directory": row["directory"] or "",
                        "mtime": updated,
                        "mtime_str": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            return sessions
        finally:
            conn.close()

    def load_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self._connect(readonly=True)
        try:
            message_rows = list(
                conn.execute(
                    """
                    SELECT id, data FROM message
                    WHERE session_id = ?
                    ORDER BY time_created ASC, id ASC
                    """,
                    (session_id,),
                )
            )
            messages = []
            for message_row in message_rows:
                message_data = json.loads(message_row["data"])
                message_id = message_row["id"]
                role = message_data.get("role", "unknown")

                part_rows = list(
                    conn.execute(
                        "SELECT id, data FROM part WHERE message_id = ? ORDER BY id ASC",
                        (message_id,),
                    )
                )

                content: List[Dict[str, Any]] = []
                parts_meta: List[Dict[str, str]] = []
                for part_row in part_rows:
                    part_data = json.loads(part_row["data"])
                    part_type = part_data.get("type", "")
                    parts_meta.append({"id": part_row["id"], "type": part_type})

                    if part_type == "text":
                        content.append({"type": "text", "text": part_data.get("text", "")})
                    elif part_type == "reasoning":
                        content.append({"type": "thinking", "text": part_data.get("text", "")})
                    elif part_type in _CONVERTED_PART_TYPES:
                        content.append({"type": part_type, "_data": part_data})

                messages.append(
                    {
                        "type": role,
                        "message": {"role": role, "content": content},
                        "_oc_msg_id": message_id,
                        "_oc_parts": parts_meta,
                        "_oc_session_id": session_id,
                    }
                )
            return messages
        finally:
            conn.close()

    def save_session_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> int:
        """写回发生变化的 text part；若 content 中不再有 thinking，则删除 reasoning part。"""
        conn = self._connect(readonly=False)
        updated_count = 0
        try:
            for msg in messages:
                if msg.get("type") != "assistant":
                    continue
                message_id = msg.get("_oc_msg_id")
                if not message_id:
                    continue

                content = msg.get("message", {}).get("content", [])
                text_items = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                has_thinking = any(
                    isinstance(item, dict) and item.get("type") == "thinking"
                    for item in content
                )

                parts_meta = msg.get("_oc_parts", [])
                db_parts = {
                    row["id"]: row["data"]
                    for row in conn.execute(
                        "SELECT id, data FROM part WHERE message_id = ?",
                        (message_id,),
                    )
                }

                text_index = 0
                for part in parts_meta:
                    part_id = part["id"]
                    part_type = part["type"]

                    if part_type == "text":
                        if text_index >= len(text_items):
                            continue
                        new_text = text_items[text_index]
                        text_index += 1

                        raw = db_parts.get(part_id)
                        if raw is None:
                            continue
                        old_data = json.loads(raw)
                        if old_data.get("text") != new_text:
                            old_data["text"] = new_text
                            conn.execute(
                                "UPDATE part SET data = ? WHERE id = ?",
                                (json.dumps(old_data, ensure_ascii=False), part_id),
                            )
                            updated_count += 1

                    elif part_type == "reasoning" and not has_thinking:
                        conn.execute("DELETE FROM part WHERE id = ?", (part_id,))
                        updated_count += 1

            conn.commit()
            return updated_count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ─── 备份 / 恢复 ────────────────────────────────────────────────────────

    def backup_database(self) -> str:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError("数据库不存在: {}".format(self.db_path))

        require_regular_or_missing(self.db_path)
        backup_path = reserve_unique_backup_path(self.db_path)
        source = destination = None
        try:
            source = self._connect(readonly=True)
            destination = sqlite3.connect(backup_path)
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("备份数据库完整性检查失败")
            destination.commit()
            logger.info("已创建数据库备份: %s", backup_path)
            return backup_path
        except Exception:
            if destination is not None:
                destination.close()
                destination = None
            if source is not None:
                source.close()
                source = None
            try:
                os.remove(backup_path)
            except FileNotFoundError:
                pass
            raise
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()

    def list_backups(self) -> List[Dict[str, Any]]:
        directory = os.path.dirname(self.db_path)
        name = os.path.basename(self.db_path)
        backups = []
        for entry in os.listdir(directory):
            if not (entry.startswith(name + ".") and entry.endswith(".bak")):
                continue
            full_path = os.path.join(directory, entry)
            try:
                info = require_regular_or_missing(full_path)
            except ValueError:
                continue
            if info is None:
                continue
            backups.append(
                {
                    "filename": entry,
                    "path": full_path,
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                    "mtime_str": datetime.fromtimestamp(info.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
            )
        backups.sort(key=lambda item: item["mtime"], reverse=True)
        return backups

    def restore_database(self, backup_path: str) -> None:
        if not os.path.exists(backup_path):
            raise FileNotFoundError("备份文件不存在: {}".format(backup_path))
        require_regular_or_missing(backup_path)

        source = sqlite3.connect("file:{}?mode=ro".format(backup_path), uri=True)
        try:
            result = source.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("备份数据库完整性检查失败")

            destination = self._connect(readonly=False)
            try:
                source.backup(destination)
                destination.commit()
                result = destination.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise sqlite3.DatabaseError("恢复后的数据库完整性检查失败")
                logger.info("已从备份恢复数据库: %s", backup_path)
            finally:
                destination.close()
        finally:
            source.close()
