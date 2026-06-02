"""
Purpose 持久化

存储：
- goals 表: 目标树（brain.db）

位置：brain.db（统一 SQLite）
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from ..base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class PurposeStorage(SQLiteStore):
    """Purpose 持久化存储（SQLite）。"""

    def __init__(self, db_path: str = "", agent_id: str = ""):
        self.agent_id = agent_id
        if db_path:
            super().__init__(db_path)
        else:
            import os
            path = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/memory/brain.db")
            super().__init__(path)
        self._ensure_tables()

    # ── Schema ──────────────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        version = self._get_schema_version("purpose_storage")
        if version >= SCHEMA_VERSION:
            return

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                goal_type TEXT NOT NULL DEFAULT 'EXECUTABLE',
                status TEXT NOT NULL DEFAULT 'PENDING',
                parent_id TEXT,
                priority REAL NOT NULL DEFAULT 0.5,
                progress REAL NOT NULL DEFAULT 0.0,
                depth INTEGER NOT NULL DEFAULT 0,
                acceptance_criteria TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                cognitive_log_json TEXT NOT NULL DEFAULT '[]',
                depends_on_json TEXT NOT NULL DEFAULT '[]',
                blocked_by_json TEXT NOT NULL DEFAULT '[]',
                context_cache TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT 0.0,
                updated_at REAL NOT NULL DEFAULT 0.0,
                deadline REAL,
                reinforcement_count INTEGER NOT NULL DEFAULT 0,
                pace_checkpoint_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.commit()
        self._set_schema_version("purpose_storage", SCHEMA_VERSION)
        logger.info("[PurposeStorage] goals 表已创建/确认 (version=%d)", SCHEMA_VERSION)

    # ── Public API ──────────────────────────────────────────────────

    def save_goals(self, goals: dict[str, Any]) -> None:
        """保存目标树到 DB（全量 REPLACE）。"""
        conn = self._get_conn()
        now = time.time()
        count = 0
        for goal_id, g in goals.items():
            d = g.to_dict()
            conn.execute("""
                INSERT OR REPLACE INTO goals (
                    id, description, goal_type, status, parent_id,
                    priority, progress, depth, acceptance_criteria,
                    metadata_json, cognitive_log_json,
                    depends_on_json, blocked_by_json,
                    context_cache, created_at, updated_at,
                    deadline, reinforcement_count, pace_checkpoint_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal_id,
                d.get("description", ""),
                d.get("goal_type", "EXECUTABLE"),
                d.get("status", "PENDING"),
                d.get("parent_id"),
                d.get("priority", 0.5),
                d.get("progress", 0.0),
                d.get("depth", 0),
                d.get("acceptance_criteria", ""),
                json.dumps(d.get("metadata", {}), ensure_ascii=False),
                json.dumps(d.get("cognitive_log", []), ensure_ascii=False),
                json.dumps(d.get("depends_on", []), ensure_ascii=False),
                json.dumps(d.get("blocked_by", []), ensure_ascii=False),
                d.get("context_cache", ""),
                d.get("created_at", now),
                d.get("updated_at", now),
                d.get("deadline"),
                d.get("reinforcement_count", 0),
                json.dumps(d.get("pace_checkpoint", {}), ensure_ascii=False),
            ))
            count += 1
        conn.commit()
        logger.debug("[PurposeStorage] 目标已保存: %d 个", count)

    def load_goals(self) -> dict[str, Any]:
        """从 DB 加载目标树。"""
        from .goal import Goal

        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM goals").fetchall()
        goals = {}
        for row in rows:
            d = dict(row)
            # 还原 JSON 字段
            for json_field in ("metadata_json", "cognitive_log_json",
                               "depends_on_json", "blocked_by_json",
                               "pace_checkpoint_json"):
                raw = d.pop(json_field, "{}")
                try:
                    d[json_field.replace("_json", "")] = json.loads(raw) if raw else (
                        [] if "log" in json_field else {})
                except (json.JSONDecodeError, TypeError):
                    d[json_field.replace("_json", "")] = (
                        [] if "log" in json_field else {})

            # 字段名映射: row_factory=Row 使用列原名，即我们 INSERT 的名字
            goal = Goal()
            goal.from_dict({
                "id": d.get("id", ""),
                "description": d.get("description", ""),
                "goal_type": d.get("goal_type", "EXECUTABLE"),
                "status": d.get("status", "PENDING"),
                "parent_id": d.get("parent_id"),
                "priority": d.get("priority", 0.5),
                "progress": d.get("progress", 0.0),
                "depth": d.get("depth", 0),
                "acceptance_criteria": d.get("acceptance_criteria", ""),
                "metadata": d.get("metadata", {}),
                "cognitive_log": d.get("cognitive_log", []),
                "depends_on": d.get("depends_on", []),
                "blocked_by": d.get("blocked_by", []),
                "context_cache": d.get("context_cache", ""),
                "created_at": d.get("created_at", 0.0),
                "updated_at": d.get("updated_at", 0.0),
                "deadline": d.get("deadline"),
                "reinforcement_count": d.get("reinforcement_count", 0),
                "pace_checkpoint": d.get("pace_checkpoint", {}),
            })
            goals[goal.id] = goal

        logger.info("[PurposeStorage] 目标已加载: %d 个", len(goals))
        return goals

    def exists(self) -> bool:
        """检查是否有目标数据。"""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM goals").fetchone()
        return (row[0] if row else 0) > 0

    def clear(self) -> None:
        """清除所有目标。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM goals")
        conn.commit()
        logger.info("[PurposeStorage] 存储已清除")
