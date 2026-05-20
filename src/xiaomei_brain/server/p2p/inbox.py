"""收件箱 — SQLite 存储收到的 agent 间消息。"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from .protocol import AgentMessage, MsgType

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT UNIQUE NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    in_reply_to TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    received_at REAL NOT NULL,
    processed INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inbox_processed ON agent_inbox(processed, received_at);
"""


class AgentInbox:
    """管理 agent 收件箱。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                conn.executescript(SCHEMA)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("[Inbox] 初始化失败: %s", e)

    def store(self, msg: AgentMessage) -> bool:
        """存入收件箱。已有相同 msg_id 则忽略。"""
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                cur = conn.execute(
                    """INSERT OR IGNORE INTO agent_inbox
                       (msg_id, from_agent, to_agent, type, content,
                        in_reply_to, metadata, created_at, received_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        msg.msg_id,
                        msg.from_agent,
                        msg.to_agent,
                        msg.type.value,
                        msg.content,
                        msg.in_reply_to,
                        json.dumps(msg.metadata, ensure_ascii=False),
                        msg.created_at,
                        time.time(),
                    ),
                )
                affected = cur.rowcount
                conn.commit()
                conn.close()
                return affected > 0
            except Exception as e:
                logger.error("[Inbox] 存储失败: %s", e)
                return False

    def get_unprocessed(self, limit: int = 10) -> list[AgentMessage]:
        """获取未处理消息。"""
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM agent_inbox
                       WHERE processed = 0
                       ORDER BY received_at ASC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
                conn.close()
                return [_row_to_msg(r) for r in rows]
            except Exception as e:
                logger.error("[Inbox] 查询失败: %s", e)
                return []

    def mark_processed(self, msg_id: str) -> None:
        """标记消息已处理。"""
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    "UPDATE agent_inbox SET processed = 1 WHERE msg_id = ?",
                    (msg_id,),
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error("[Inbox] 标记失败: %s", e)

    def count_unprocessed(self) -> int:
        """未处理消息数。"""
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                count = conn.execute(
                    "SELECT COUNT(*) FROM agent_inbox WHERE processed = 0"
                ).fetchone()[0]
                conn.close()
                return count
            except Exception:
                return 0


def _row_to_msg(row) -> AgentMessage:
    return AgentMessage(
        type=MsgType(row["type"]),
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        content=row["content"],
        msg_id=row["msg_id"],
        in_reply_to=row["in_reply_to"],
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
    )
