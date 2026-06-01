"""TaskQueueStorage — intent_buffer 和 learning_queue 的 SQLite 持久化。

两张表共用同一个 db_path（brain.db），和 Essence/LongTermMemory 等同库。

模式：内存为主，DB 为备份。
- 写入时：内存操作 + 立即写 DB（单条 INSERT，WAL 模式下微秒级）
- 60秒同步：全量同步 pending 状态（防止内存和 DB 不一致）
- 启动时：从 DB 加载 pending 记录到内存
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS intent_buffer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    content TEXT DEFAULT '',
    trigger_time REAL NOT NULL,
    source TEXT DEFAULT 'consciousness',
    params TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ib_status ON intent_buffer(status);
CREATE INDEX IF NOT EXISTS idx_ib_type_status ON intent_buffer(type, status);

CREATE TABLE IF NOT EXISTS learning_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    reason TEXT DEFAULT '',
    priority REAL DEFAULT 0.5,
    source TEXT DEFAULT 'unknown',
    status TEXT DEFAULT 'pending',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lq_status ON learning_queue(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lq_topic_pending
ON learning_queue(topic) WHERE status = 'pending';
"""


class TaskQueueStorage(SQLiteStore):
    """intent_buffer + learning_queue 的 SQLite 持久化。"""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._init_tables()

    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript(DDL)
        conn.commit()

    # ── intent_buffer ──────────────────────────────────────

    def add_intent(self, intent_dict: dict) -> int:
        """写入一条 intent 记录。返回 row id。"""
        conn = self._get_conn()
        now = time.time()
        params_json = json.dumps(intent_dict.get("params", {}), ensure_ascii=False)
        cursor = conn.execute(
            """INSERT INTO intent_buffer (type, priority, content, trigger_time, source, params, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                intent_dict.get("type", ""),
                intent_dict.get("priority", 50),
                intent_dict.get("content", ""),
                intent_dict.get("trigger_time", now),
                intent_dict.get("source", "consciousness"),
                params_json,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def load_pending_intents(self) -> list[dict]:
        """加载所有 pending 的 intent，按 created_at 排序。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM intent_buffer WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [self._row_to_intent(r) for r in rows]

    def mark_intent_consumed(self, intent_type: str) -> int:
        """标记指定类型的 pending intent 为 consumed。返回影响行数。"""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE intent_buffer SET status = 'consumed' WHERE type = ? AND status = 'pending'",
            (intent_type,),
        )
        conn.commit()
        return cursor.rowcount

    def sync_intents(self, buffer_list: list[dict]) -> None:
        """全量同步：清除 pending → 插入当前内存中的 intent。

        60 秒周期调用，防止内存和 DB 不一致。
        """
        conn = self._get_conn()
        conn.execute("DELETE FROM intent_buffer WHERE status = 'pending'")
        now = time.time()
        for item in buffer_list:
            params_json = json.dumps(item.get("params", {}), ensure_ascii=False)
            conn.execute(
                """INSERT INTO intent_buffer (type, priority, content, trigger_time, source, params, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    item.get("type", ""),
                    item.get("priority", 50),
                    item.get("content", ""),
                    item.get("trigger_time", now),
                    item.get("source", "consciousness"),
                    params_json,
                    now,
                ),
            )
        conn.commit()

    def _row_to_intent(self, row: Any) -> dict:
        """将 DB 行转为 intent dict（和 Intent.to_dict() 格式一致）。"""
        d = dict(row)
        try:
            d["params"] = json.loads(d.get("params", "{}"))
        except (json.JSONDecodeError, TypeError):
            d["params"] = {}
        # 去掉 DB 内部字段
        d.pop("id", None)
        d.pop("status", None)
        d.pop("created_at", None)
        return d

    # ── learning_queue ─────────────────────────────────────

    def add_learning(self, topic: str, reason: str = "",
                     priority: float = 0.5, source: str = "unknown") -> int | None:
        """写入一条学习主题（topic UNIQUE 去重）。返回 row id 或 None（已存在）。"""
        conn = self._get_conn()
        now = time.time()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO learning_queue (topic, reason, priority, source, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (topic, reason, priority, source, now),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None  # 已存在，被 IGNORE
            return cursor.lastrowid
        except Exception as e:
            logger.warning("[TaskQueueStorage] add_learning 失败: %s", e)
            return None

    def load_pending_learning(self) -> list[dict]:
        """加载所有 pending 的学习主题，按 priority 降序。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM learning_queue WHERE status = 'pending' ORDER BY priority DESC, created_at"
        ).fetchall()
        return [
            {
                "topic": r["topic"],
                "reason": r["reason"],
                "priority": r["priority"],
                "source": r["source"],
            }
            for r in rows
        ]

    def mark_learning_done(self, topic: str) -> int:
        """标记学习主题为 done。返回影响行数。"""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE learning_queue SET status = 'done' WHERE topic = ? AND status = 'pending'",
            (topic,),
        )
        conn.commit()
        return cursor.rowcount

    def sync_learning(self, queue_list: list[dict]) -> None:
        """全量同步：清除 pending → 插入当前内存中的学习主题。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM learning_queue WHERE status = 'pending'")
        now = time.time()
        for item in queue_list:
            conn.execute(
                """INSERT OR IGNORE INTO learning_queue (topic, reason, priority, source, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (
                    item.get("topic", ""),
                    item.get("reason", ""),
                    item.get("priority", 0.5),
                    item.get("source", "unknown"),
                    now,
                ),
            )
        conn.commit()

    # ── 统计 ───────────────────────────────────────────────

    def stats(self) -> dict:
        """返回两张表的统计信息。"""
        conn = self._get_conn()
        ib_pending = conn.execute(
            "SELECT COUNT(*) FROM intent_buffer WHERE status = 'pending'"
        ).fetchone()[0]
        lq_pending = conn.execute(
            "SELECT COUNT(*) FROM learning_queue WHERE status = 'pending'"
        ).fetchone()[0]
        return {
            "intent_pending": ib_pending,
            "learning_pending": lq_pending,
        }
