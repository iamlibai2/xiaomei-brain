"""Persistent per-Agent ledger for LLM token usage."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .usage import LLMUsageRecord


class UsageStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'other',
                    person_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    message_input_tokens INTEGER NOT NULL DEFAULT 0,
                    system_input_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_input_tokens INTEGER NOT NULL DEFAULT 0,
                    skill_input_tokens INTEGER NOT NULL DEFAULT 0,
                    workspace_input_tokens INTEGER NOT NULL DEFAULT 0,
                    exact INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    raw_usage TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_llm_usage_created
                    ON llm_usage(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_llm_usage_session_turn
                    ON llm_usage(session_id, turn_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_llm_usage_model
                    ON llm_usage(provider, model, created_at DESC);
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(llm_usage)").fetchall()
            }
            for name in (
                "message_input_tokens", "system_input_tokens", "tool_input_tokens",
                "skill_input_tokens", "workspace_input_tokens",
            ):
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE llm_usage ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                    )

    def record(self, record: LLMUsageRecord) -> str:
        record_id = f"usage_{uuid.uuid4().hex}"
        breakdown = record.input_breakdown or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO llm_usage (
                    id, created_at, provider, model, category, person_id,
                    session_id, turn_id, input_tokens, output_tokens,
                    cached_input_tokens, reasoning_tokens, total_tokens,
                    message_input_tokens, system_input_tokens, tool_input_tokens,
                    skill_input_tokens, workspace_input_tokens,
                    exact, latency_ms, raw_usage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id,
                    time.time(),
                    record.provider,
                    record.model,
                    record.category,
                    record.person_id,
                    record.session_id,
                    record.turn_id,
                    max(0, int(record.input_tokens)),
                    max(0, int(record.output_tokens)),
                    max(0, int(record.cached_input_tokens)),
                    max(0, int(record.reasoning_tokens)),
                    max(0, int(record.total_tokens)),
                    max(0, int(breakdown.get("messages", 0) or 0)),
                    max(0, int(breakdown.get("system", 0) or 0)),
                    max(0, int(breakdown.get("tools", 0) or 0)),
                    max(0, int(breakdown.get("skills", 0) or 0)),
                    max(0, int(breakdown.get("workspace", 0) or 0)),
                    1 if record.exact else 0,
                    max(0.0, float(record.latency_ms)),
                    json.dumps(record.raw_usage or {}, ensure_ascii=False),
                ),
            )
        return record_id

    @staticmethod
    def _period_start(period: str) -> float:
        now = datetime.now()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = (now - timedelta(days=6)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
        return start.timestamp()

    @staticmethod
    def _totals(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {
                "input_tokens": 0, "output_tokens": 0,
                "cached_input_tokens": 0, "reasoning_tokens": 0,
                "total_tokens": 0, "calls": 0, "exact_calls": 0,
                "estimated_calls": 0, "latency_ms": 0,
                "message_input_tokens": 0, "system_input_tokens": 0,
                "tool_input_tokens": 0, "skill_input_tokens": 0,
                "workspace_input_tokens": 0,
            }
        calls = int(row["calls"] or 0)
        exact_calls = int(row["exact_calls"] or 0)
        return {
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "cached_input_tokens": int(row["cached_input_tokens"] or 0),
            "reasoning_tokens": int(row["reasoning_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "message_input_tokens": int(row["message_input_tokens"] or 0),
            "system_input_tokens": int(row["system_input_tokens"] or 0),
            "tool_input_tokens": int(row["tool_input_tokens"] or 0),
            "skill_input_tokens": int(row["skill_input_tokens"] or 0),
            "workspace_input_tokens": int(row["workspace_input_tokens"] or 0),
            "calls": calls,
            "exact_calls": exact_calls,
            "estimated_calls": max(0, calls - exact_calls),
            "latency_ms": float(row["latency_ms"] or 0),
        }

    @staticmethod
    def _aggregate_sql(where: str = "") -> str:
        return f"""SELECT
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(message_input_tokens), 0) AS message_input_tokens,
            COALESCE(SUM(system_input_tokens), 0) AS system_input_tokens,
            COALESCE(SUM(tool_input_tokens), 0) AS tool_input_tokens,
            COALESCE(SUM(skill_input_tokens), 0) AS skill_input_tokens,
            COALESCE(SUM(workspace_input_tokens), 0) AS workspace_input_tokens,
            COUNT(*) AS calls,
            COALESCE(SUM(exact), 0) AS exact_calls,
            COALESCE(SUM(latency_ms), 0) AS latency_ms
            FROM llm_usage {where}"""

    def summary(self, *, session_id: str = "", turn_limit: int = 100) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            periods = {}
            breakdowns = {}
            for period in ("today", "seven_days", "month"):
                period_start = self._period_start(period)
                row = conn.execute(
                    self._aggregate_sql("WHERE created_at >= ?"),
                    (period_start,),
                ).fetchone()
                periods[period] = self._totals(row)
                breakdowns[period] = {
                    "models": [dict(item) for item in conn.execute(
                        """SELECT provider, model, SUM(total_tokens) AS total_tokens,
                            SUM(input_tokens) AS input_tokens,
                            SUM(output_tokens) AS output_tokens, COUNT(*) AS calls
                           FROM llm_usage WHERE created_at >= ?
                           GROUP BY provider, model ORDER BY total_tokens DESC""",
                        (period_start,),
                    ).fetchall()],
                    "categories": [dict(item) for item in conn.execute(
                        """SELECT category, SUM(total_tokens) AS total_tokens,
                            SUM(input_tokens) AS input_tokens,
                            SUM(output_tokens) AS output_tokens, COUNT(*) AS calls
                           FROM llm_usage WHERE created_at >= ?
                           GROUP BY category ORDER BY total_tokens DESC""",
                        (period_start,),
                    ).fetchall()],
                }

            current_session = self._totals(
                conn.execute(
                    self._aggregate_sql("WHERE session_id = ?"),
                    (session_id,),
                ).fetchone()
            ) if session_id else self._totals(None)

            turns: list[dict[str, Any]] = []
            if session_id:
                turns = [dict(row) for row in conn.execute(
                    """SELECT turn_id,
                        SUM(input_tokens) AS input_tokens,
                        SUM(output_tokens) AS output_tokens,
                        SUM(cached_input_tokens) AS cached_input_tokens,
                        SUM(reasoning_tokens) AS reasoning_tokens,
                        SUM(total_tokens) AS total_tokens,
                        SUM(message_input_tokens) AS message_input_tokens,
                        SUM(system_input_tokens) AS system_input_tokens,
                        SUM(tool_input_tokens) AS tool_input_tokens,
                        SUM(skill_input_tokens) AS skill_input_tokens,
                        SUM(workspace_input_tokens) AS workspace_input_tokens,
                        COUNT(*) AS calls,
                        SUM(exact) AS exact_calls,
                        SUM(latency_ms) AS latency_ms,
                        MAX(created_at) AS updated_at
                       FROM llm_usage
                       WHERE session_id = ? AND turn_id <> ''
                       GROUP BY turn_id ORDER BY updated_at DESC LIMIT ?""",
                    (session_id, max(1, min(int(turn_limit), 500))),
                ).fetchall()]
                for item in turns:
                    item["estimated_calls"] = max(
                        0, int(item["calls"] or 0) - int(item["exact_calls"] or 0)
                    )

            first = conn.execute(
                "SELECT MIN(created_at) AS first_recorded_at FROM llm_usage"
            ).fetchone()
        return {
            "periods": periods,
            "current_session": current_session,
            "breakdowns": breakdowns,
            # Kept as a convenient default for clients that only show today.
            "models": breakdowns["today"]["models"],
            "categories": breakdowns["today"]["categories"],
            "turns": turns,
            "first_recorded_at": (
                float(first["first_recorded_at"])
                if first and first["first_recorded_at"] is not None else None
            ),
        }

    def list_records(
        self,
        *,
        session_id: str = "",
        category: str = "",
        model: str = "",
        since: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        values: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            values.append(session_id)
        if category:
            clauses.append("category = ?")
            values.append(category)
        if model:
            clauses.append("model = ?")
            values.append(model)
        if since is not None:
            clauses.append("created_at >= ?")
            values.append(float(since))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        page_limit = max(1, min(int(limit), 500))
        page_offset = max(0, int(offset))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""SELECT id, created_at, provider, model, category,
                    person_id, session_id, turn_id, input_tokens, output_tokens,
                    cached_input_tokens, reasoning_tokens, total_tokens, exact,
                    message_input_tokens, system_input_tokens, tool_input_tokens,
                    skill_input_tokens, workspace_input_tokens, latency_ms
                    FROM llm_usage {where}
                    ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (*values, page_limit + 1, page_offset),
            ).fetchall()
        has_more = len(rows) > page_limit
        items = [dict(row) for row in rows[:page_limit]]
        for item in items:
            item["exact"] = bool(item["exact"])
        return {
            "items": items,
            "has_more": has_more,
            "next_offset": page_offset + page_limit if has_more else None,
        }
