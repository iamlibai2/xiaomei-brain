"""ExperienceStream — 统一经验流。

小美经历一切的唯一时间线。所有行为——对话、思考、工具执行、Drive事件——
都写入同一条流。记忆窗口从这里读取最近经历的连续性。

设计原则：
- 只追加，不修改（immutable log）
- 双写阶段：同时写 experience_stream 和旧表（messages/consciousness_stream）
- 专用表（memories/narrative_memories 等）从经验流异步精炼，是物化视图
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# type 枚举
TYPE_USER_MSG = "user_msg"
TYPE_ASSISTANT_MSG = "assistant_msg"
TYPE_TOOL_EXEC = "tool_exec"
TYPE_INTERNAL_THOUGHT = "internal_thought"
TYPE_INTERNAL_ACTION = "internal_action"
TYPE_DRIVE_EVENT = "drive_event"
TYPE_DREAM = "dream"
TYPE_INTERNAL_REFLECTION = "internal_reflection"

# importance 初始值
DEFAULT_IMPORTANCE: dict[str, float] = {
    TYPE_USER_MSG: 0.5,
    TYPE_ASSISTANT_MSG: 0.4,
    TYPE_TOOL_EXEC: 0.3,
    TYPE_INTERNAL_THOUGHT: 0.6,
    TYPE_INTERNAL_ACTION: 0.5,
    TYPE_DRIVE_EVENT: 0.4,
    TYPE_DREAM: 0.5,
    TYPE_INTERNAL_REFLECTION: 0.3,
}

DDL = """
CREATE TABLE IF NOT EXISTS experience_stream (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    created_at REAL NOT NULL,
    session_id TEXT DEFAULT '',
    related_id TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    user_id TEXT DEFAULT 'global'
);

CREATE INDEX IF NOT EXISTS idx_exp_stream_type ON experience_stream(type);
CREATE INDEX IF NOT EXISTS idx_exp_stream_created ON experience_stream(created_at);
CREATE INDEX IF NOT EXISTS idx_exp_stream_session ON experience_stream(session_id, created_at);
"""

DDL_MIGRATED = """
CREATE INDEX IF NOT EXISTS idx_exp_stream_user ON experience_stream(user_id, created_at);
"""


class ExperienceStream(SQLiteStore):
    """统一经验流 — 小美一切经历的唯一时间线。"""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._init_tables()

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA synchronous=NORMAL")

    def _init_tables(self) -> None:
        """创建 experience_stream 表及索引。"""
        conn = self._get_conn()
        conn.executescript(DDL)
        conn.commit()
        self._migrate()
        # 迁移后补充索引（DDL_MIGRATED 依赖 user_id 列存在）
        conn.executescript(DDL_MIGRATED)
        conn.commit()

    def _migrate(self) -> None:
        """增量迁移：添加 user_id 列（如果不存在）。"""
        conn = self._get_conn()
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(experience_stream)").fetchall()]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE experience_stream ADD COLUMN user_id TEXT DEFAULT 'global'")
            conn.commit()
            logger.info("[ExperienceStream] 迁移: 添加 user_id 列")

    # ── 写入 ──────────────────────────────────────────────────

    def log(
        self,
        type: str,
        content: str,
        importance: float | None = None,
        session_id: str = "",
        related_id: str = "",
        metadata: dict[str, Any] | None = None,
        user_id: str = "global",
    ) -> int:
        """写入一条经验。

        Args:
            type: 经验类型（user_msg/assistant_msg/tool_exec/internal_thought/
                  internal_action/drive_event/dream/internal_reflection）
            content: 文本内容
            importance: 初始权重，不传则按类型默认
            session_id: 关联的会话 ID
            related_id: 关联的专用表 ID
            metadata: 类型相关的附加数据
            user_id: 用户标识（默认 global 表示 agent 级别事件）

        Returns:
            新插入行的 id。
        """
        if importance is None:
            importance = DEFAULT_IMPORTANCE.get(type, 0.5)

        # 截断超长内容
        content = content[:2000] if content else ""

        conn = self._get_conn()
        cur = conn.execute(
            """INSERT INTO experience_stream
               (type, content, importance, created_at, session_id, related_id, metadata, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                type,
                content,
                min(1.0, max(0.0, importance)),
                time.time(),
                session_id or "",
                related_id or "",
                json.dumps(metadata or {}, ensure_ascii=False),
                user_id,
            ),
        )
        conn.commit()
        return cur.lastrowid

    # ── 读取 ──────────────────────────────────────────────────

    def get_recent(
        self,
        limit: int = 50,
        session_id: str | None = None,
        types: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取最近 N 条经验。

        Args:
            limit: 最大返回条数
            session_id: 可选，按会话过滤
            types: 可选，按类型过滤
            user_id: 可选，按用户过滤（不传则不过滤）

        Returns:
            [{id, type, content, importance, created_at, session_id, related_id, metadata, user_id}, ...]
            按 created_at 倒序（最新的在前）。
        """
        conn = self._get_conn()
        sql = "SELECT * FROM experience_stream WHERE 1=1"
        params: list[Any] = []

        if user_id:
            sql += " AND (user_id = ? OR user_id = 'global')"
            params.append(user_id)

        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)

        if types:
            placeholders = ",".join("?" * len(types))
            sql += f" AND type IN ({placeholders})"
            params.extend(types)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── 迁移 ──────────────────────────────────────────────────

    def migrate_messages(self, db_path: str) -> int:
        """从 messages 表迁移历史数据。

        注意：这里需要直接操作同一个 brain.db，所以传入的是 db_path
        （不是 ConversationDB 实例，因为 ExperienceStream 和 ConversationDB
        共享同一个 brain.db 文件）。
        """
        logger.info("[ExperienceStream] 开始迁移 messages ...")

        # 检查是否已有数据
        count_before = self._get_conn().execute(
            "SELECT COUNT(*) FROM experience_stream"
        ).fetchone()[0]
        if count_before > 0:
            logger.info("[ExperienceStream] 已有 %d 条记录，跳过迁移", count_before)
            return 0

        conn = self._get_conn()
        # messages 表可能不存在（在同一个 DB 里）
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        ).fetchone()
        if not table_check:
            logger.info("[ExperienceStream] messages 表不存在，跳过")
            return 0

        total = 0
        rows = conn.execute(
            "SELECT role, content, created_at, session_id, id FROM messages ORDER BY created_at ASC"
        ).fetchall()

        for row in rows:
            role = row["role"]
            if role == "user":
                exp_type = TYPE_USER_MSG
                imp = 0.5
            elif role == "assistant":
                exp_type = TYPE_ASSISTANT_MSG
                imp = 0.4
            elif role == "tool":
                exp_type = TYPE_TOOL_EXEC
                imp = 0.3
            else:
                exp_type = TYPE_INTERNAL_THOUGHT
                imp = 0.3

            conn.execute(
                """INSERT INTO experience_stream
                   (type, content, importance, created_at, session_id, related_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    exp_type,
                    row["content"] or "",
                    imp,
                    row["created_at"],
                    row["session_id"] or "",
                    str(row["id"]),
                    "{}",
                ),
            )
            total += 1

        conn.commit()
        logger.info("[ExperienceStream] messages 迁移完成: %d 条", total)
        return total

    def migrate_consciousness_narratives(self) -> int:
        """从 consciousness_stream 表迁移。"""
        conn = self._get_conn()

        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='consciousness_stream'"
        ).fetchone()
        if not table_check:
            logger.info("[ExperienceStream] consciousness_stream 表不存在，跳过")
            return 0

        # 检查是否已迁移过（通过 metadata 中的 source 标记）
        already = conn.execute(
            "SELECT COUNT(*) FROM experience_stream WHERE metadata LIKE '%consciousness_stream%'"
        ).fetchone()[0]
        if already > 0:
            logger.info("[ExperienceStream] consciousness_stream 已迁移 %d 条，跳过", already)
            return 0

        total = 0
        rows = conn.execute(
            "SELECT content, created_at, id FROM consciousness_stream ORDER BY created_at ASC"
        ).fetchall()

        for row in rows:
            conn.execute(
                """INSERT INTO experience_stream
                   (type, content, importance, created_at, session_id, related_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    TYPE_INTERNAL_THOUGHT,
                    (row["content"] or "")[:2000],
                    0.6,
                    row["created_at"],
                    "",
                    str(row["id"]),
                    '{"source": "consciousness_stream"}',
                ),
            )
            total += 1

        conn.commit()
        logger.info("[ExperienceStream] consciousness_stream 迁移完成: %d 条", total)
        return total

    def migrate_tool_history(self) -> int:
        """从 tool_history 表迁移。"""
        conn = self._get_conn()

        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_history'"
        ).fetchone()
        if not table_check:
            logger.info("[ExperienceStream] tool_history 表不存在，跳过")
            return 0

        # 检查是否已迁移过：tool_history 的数据 related_id 不为空且 metadata 含 tool_name
        already = conn.execute(
            "SELECT COUNT(*) FROM experience_stream WHERE type='tool_exec' AND related_id != '' AND metadata LIKE '%tool_name%'"
        ).fetchone()[0]
        if already > 0:
            logger.info("[ExperienceStream] tool_history 已迁移 %d 条，跳过", already)
            return 0

        total = 0
        rows = conn.execute(
            "SELECT tool_name, args, result, created_at, session_id, id FROM tool_history ORDER BY created_at ASC"
        ).fetchall()

        for row in rows:
            content = f"{row['tool_name']}: {row['result'] or ''}"[:2000]
            conn.execute(
                """INSERT INTO experience_stream
                   (type, content, importance, created_at, session_id, related_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    TYPE_TOOL_EXEC,
                    content,
                    0.3,
                    row["created_at"],
                    row["session_id"] or "",
                    str(row["id"]),
                    json.dumps({"tool_name": row["tool_name"]}, ensure_ascii=False),
                ),
            )
            total += 1

        conn.commit()
        logger.info("[ExperienceStream] tool_history 迁移完成: %d 条", total)
        return total

    # ── 管理 ──────────────────────────────────────────────────

    def count(self, types: list[str] | None = None) -> int:
        """统计经验条数。"""
        conn = self._get_conn()
        if types:
            placeholders = ",".join("?" * len(types))
            return conn.execute(
                f"SELECT COUNT(*) FROM experience_stream WHERE type IN ({placeholders})",
                types,
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM experience_stream").fetchone()[0]

