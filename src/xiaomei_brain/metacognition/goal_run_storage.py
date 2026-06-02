"""GoalRunStorage — 任务执行持久化引擎。

统一管理 goal_runs / goal_steps / goal_log / pace_checkpoints 四张表，
全部存储在 brain.db 中。替代旧的 JSON 文件持久化。

Usage:
    store = GoalRunStorage(db_path)
    run_id = store.create_run(goal_id, goal_desc, agent_id)
    store.record_step(run_id, step_index, ...)
    store.append_log(run_id, "output", "content")
    store.close_run(run_id, ...)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ..base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class GoalRunStorage(SQLiteStore):
    """任务执行持久化，管理 brain.db 中 goal_* 表和 pace_checkpoints 表。"""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    # ── Schema ──────────────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        version = self._get_schema_version("goal_run")
        if version >= SCHEMA_VERSION:
            return

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS goal_runs (
                run_id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL DEFAULT '',
                goal_description TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                start_time REAL NOT NULL DEFAULT 0.0,
                end_time REAL NOT NULL DEFAULT 0.0,
                total_steps INTEGER NOT NULL DEFAULT 0,
                total_llm_calls INTEGER NOT NULL DEFAULT 0,
                total_tool_calls INTEGER NOT NULL DEFAULT 0,
                total_elapsed REAL NOT NULL DEFAULT 0.0,
                surprises_detected TEXT NOT NULL DEFAULT '{}',
                hard_rules_triggered INTEGER NOT NULL DEFAULT 0,
                llm_checks_performed INTEGER NOT NULL DEFAULT 0,
                escalations INTEGER NOT NULL DEFAULT 0,
                auto_advances INTEGER NOT NULL DEFAULT 0,
                waiting_user_exits INTEGER NOT NULL DEFAULT 0,
                sub_goals_completed INTEGER NOT NULL DEFAULT 0,
                sub_goals_failed INTEGER NOT NULL DEFAULT 0,
                goal_completed INTEGER NOT NULL DEFAULT 0,
                exit_reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS goal_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_index INTEGER NOT NULL DEFAULT 0,
                goal_description TEXT NOT NULL DEFAULT '',
                llm_output TEXT NOT NULL DEFAULT '',
                tool_calls TEXT NOT NULL DEFAULT '[]',
                tool_call_count INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL NOT NULL DEFAULT 0.0,
                has_progress_tag INTEGER NOT NULL DEFAULT 0,
                progress_status TEXT,
                surprises TEXT NOT NULL DEFAULT '[]',
                step_check_suggestion TEXT NOT NULL DEFAULT '',
                iv_retry INTEGER NOT NULL DEFAULT 0,
                iv_block INTEGER NOT NULL DEFAULT 0,
                iv_escalate INTEGER NOT NULL DEFAULT 0,
                perspective_tried INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                action_decided TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY (run_id) REFERENCES goal_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_goal_steps_run
                ON goal_steps(run_id, step_index);

            CREATE TABLE IF NOT EXISTS goal_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL DEFAULT '',
                goal_id TEXT NOT NULL DEFAULT '',
                entry_type TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                sub_goal_id TEXT NOT NULL DEFAULT '',
                step_index INTEGER,
                created_at REAL NOT NULL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_goal_log_run
                ON goal_log(run_id);
            CREATE INDEX IF NOT EXISTS idx_goal_log_goal
                ON goal_log(goal_id);

            CREATE TABLE IF NOT EXISTS pace_checkpoints (
                goal_id TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                step_index INTEGER NOT NULL DEFAULT 0,
                observations_json TEXT NOT NULL DEFAULT '[]',
                budget_call_count INTEGER NOT NULL DEFAULT 0,
                budget_skip_until REAL NOT NULL DEFAULT 0.0,
                budget_consecutive_continue INTEGER NOT NULL DEFAULT 0,
                consecutive_empty_count INTEGER NOT NULL DEFAULT 0,
                last_nudge TEXT NOT NULL DEFAULT '',
                saved_at REAL NOT NULL DEFAULT 0.0,
                run_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (goal_id, agent_id)
            );
        """)
        conn.commit()
        self._set_schema_version("goal_run", SCHEMA_VERSION)
        logger.info("[GoalRunStorage] 表已创建/确认 (version=%d)", SCHEMA_VERSION)

    # ── goal_runs ───────────────────────────────────────────────────

    def create_run(
        self, goal_id: str, goal_description: str, agent_id: str = "",
    ) -> str:
        """创建一次任务执行记录。返回 run_id。"""
        import uuid
        run_id = uuid.uuid4().hex[:12]
        now = time.time()
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO goal_runs (run_id, goal_id, goal_description, agent_id,
                start_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, goal_id, goal_description, agent_id, now, now))
        conn.commit()
        logger.info("[GoalRunStorage] 创建 run: %s goal=%s", run_id, goal_id)
        return run_id

    def close_run(
        self, run_id: str, total_llm_calls: int, exit_reason: str,
        surprises_detected: dict | None = None,
        hard_rules_triggered: int = 0,
        llm_checks_performed: int = 0,
        escalations: int = 0,
        auto_advances: int = 0,
        waiting_user_exits: int = 0,
        sub_goals_completed: int = 0,
        sub_goals_failed: int = 0,
        goal_completed: bool = False,
    ) -> None:
        """结束一次任务执行，写入汇总指标。"""
        conn = self._get_conn()
        # 先计算 steps 统计
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(tool_call_count),0) as tc, "
            "COALESCE(SUM(elapsed_seconds),0) as el FROM goal_steps WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        total_steps = row[0] if row else 0
        total_tool_calls = row[1] if row else 0
        total_elapsed = row[2] if row else 0.0

        surprises_json = json.dumps(surprises_detected or {}, ensure_ascii=False)
        now = time.time()
        conn.execute("""
            UPDATE goal_runs SET
                end_time = ?,
                total_steps = ?,
                total_llm_calls = ?,
                total_tool_calls = ?,
                total_elapsed = ?,
                surprises_detected = ?,
                hard_rules_triggered = ?,
                llm_checks_performed = ?,
                escalations = ?,
                auto_advances = ?,
                waiting_user_exits = ?,
                sub_goals_completed = ?,
                sub_goals_failed = ?,
                goal_completed = ?,
                exit_reason = ?
            WHERE run_id = ?
        """, (
            now, total_steps, total_llm_calls, total_tool_calls,
            round(total_elapsed, 1), surprises_json,
            hard_rules_triggered, llm_checks_performed, escalations,
            auto_advances, waiting_user_exits,
            sub_goals_completed, sub_goals_failed,
            1 if goal_completed else 0, exit_reason,
            run_id,
        ))
        conn.commit()
        logger.info("[GoalRunStorage] 关闭 run: %s steps=%d reason=%s",
                    run_id, total_steps, exit_reason)

    # ── goal_steps ──────────────────────────────────────────────────

    def record_step(
        self,
        run_id: str,
        step_index: int,
        goal_description: str,
        llm_output: str,
        tool_calls: list[str],
        tool_call_count: int,
        elapsed_seconds: float,
        has_progress_tag: bool,
        progress_status: str | None,
        surprises: list[str],
        step_check_suggestion: str,
        iv_retry: bool = False,
        iv_block: bool = False,
        iv_escalate: bool = False,
        perspective_tried: bool = False,
        retry_count: int = 0,
        action_decided: str = "",
    ) -> int:
        """记录一步执行。返回 row id。"""
        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute("""
            INSERT INTO goal_steps (
                run_id, step_index, goal_description, llm_output,
                tool_calls, tool_call_count, elapsed_seconds,
                has_progress_tag, progress_status, surprises,
                step_check_suggestion,
                iv_retry, iv_block, iv_escalate, perspective_tried,
                retry_count, action_decided, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, step_index, goal_description,
            llm_output[:1000] if llm_output else "",
            json.dumps(tool_calls, ensure_ascii=False),
            tool_call_count, elapsed_seconds,
            1 if has_progress_tag else 0, progress_status,
            json.dumps(surprises, ensure_ascii=False),
            step_check_suggestion,
            1 if iv_retry else 0, 1 if iv_block else 0,
            1 if iv_escalate else 0, 1 if perspective_tried else 0,
            retry_count, action_decided, now,
        ))
        conn.commit()
        return cursor.lastrowid

    # ── goal_log ────────────────────────────────────────────────────

    def append_log(
        self,
        run_id: str = "",
        goal_id: str = "",
        entry_type: str = "",
        content: str = "",
        sub_goal_id: str = "",
        step_index: int | None = None,
    ) -> int:
        """追加一条日志。返回 row id。"""
        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute("""
            INSERT INTO goal_log (run_id, goal_id, entry_type, content,
                sub_goal_id, step_index, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (run_id, goal_id, entry_type, content[:2000], sub_goal_id, step_index, now))
        conn.commit()
        return cursor.lastrowid

    # ── pace_checkpoints ────────────────────────────────────────────

    def save_checkpoint(
        self,
        goal_id: str,
        agent_id: str,
        step_index: int,
        observations_json: str,
        budget_call_count: int,
        budget_skip_until: float = 0.0,
        budget_consecutive_continue: int = 0,
        consecutive_empty_count: int = 0,
        last_nudge: str = "",
        run_id: str = "",
    ) -> None:
        """保存检查点到 DB（INSERT OR REPLACE）。"""
        conn = self._get_conn()
        now = time.time()
        conn.execute("""
            INSERT OR REPLACE INTO pace_checkpoints (
                goal_id, agent_id, step_index, observations_json,
                budget_call_count, budget_skip_until, budget_consecutive_continue,
                consecutive_empty_count, last_nudge, saved_at, run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            goal_id, agent_id, step_index, observations_json,
            budget_call_count, budget_skip_until, budget_consecutive_continue,
            consecutive_empty_count, last_nudge, now, run_id,
        ))
        conn.commit()
        logger.info("[GoalRunStorage] checkpoint 已保存: goal=%s agent=%s step=%d",
                    goal_id, agent_id, step_index)

    def load_checkpoint(self, goal_id: str, agent_id: str) -> dict | None:
        """从 DB 加载检查点。返回 dict 或 None。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM pace_checkpoints WHERE goal_id = ? AND agent_id = ?",
            (goal_id, agent_id),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def delete_checkpoint(self, goal_id: str, agent_id: str) -> None:
        """删除检查点。"""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM pace_checkpoints WHERE goal_id = ? AND agent_id = ?",
            (goal_id, agent_id),
        )
        conn.commit()

    # ── Query helpers ───────────────────────────────────────────────

    def get_run(self, run_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM goal_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_steps(self, run_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM goal_steps WHERE run_id = ? ORDER BY step_index",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_logs(self, run_id: str = "", goal_id: str = "", limit: int = 100) -> list[dict]:
        conn = self._get_conn()
        if run_id:
            rows = conn.execute(
                "SELECT * FROM goal_log WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
                (run_id, limit),
            ).fetchall()
        elif goal_id:
            rows = conn.execute(
                "SELECT * FROM goal_log WHERE goal_id = ? ORDER BY created_at DESC LIMIT ?",
                (goal_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM goal_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self, agent_id: str = "") -> dict:
        """获取聚合摘要（替代 metrics_summary.json）。"""
        conn = self._get_conn()
        if agent_id:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_runs,
                    COALESCE(SUM(total_steps), 0) as total_steps,
                    COALESCE(SUM(total_llm_calls), 0) as total_llm_calls,
                    COALESCE(SUM(total_tool_calls), 0) as total_tool_calls,
                    COALESCE(SUM(total_elapsed), 0.0) as total_elapsed,
                    COALESCE(SUM(hard_rules_triggered), 0) as hard_rules,
                    COALESCE(SUM(llm_checks_performed), 0) as llm_checks,
                    COALESCE(SUM(escalations), 0) as escalations,
                    COALESCE(SUM(auto_advances), 0) as auto_advances,
                    COALESCE(SUM(waiting_user_exits), 0) as waiting_user,
                    COALESCE(SUM(goal_completed), 0) as completed,
                    COUNT(*) - COALESCE(SUM(goal_completed), 0) as failed,
                    COALESCE(SUM(sub_goals_completed), 0) as sub_completed,
                    COALESCE(SUM(sub_goals_failed), 0) as sub_failed
                FROM goal_runs WHERE agent_id = ?
            """, (agent_id,)).fetchone()
        else:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_runs,
                    COALESCE(SUM(total_steps), 0) as total_steps,
                    COALESCE(SUM(total_llm_calls), 0) as total_llm_calls,
                    COALESCE(SUM(total_tool_calls), 0) as total_tool_calls,
                    COALESCE(SUM(total_elapsed), 0.0) as total_elapsed,
                    COALESCE(SUM(hard_rules_triggered), 0) as hard_rules,
                    COALESCE(SUM(llm_checks_performed), 0) as llm_checks,
                    COALESCE(SUM(escalations), 0) as escalations,
                    COALESCE(SUM(auto_advances), 0) as auto_advances,
                    COALESCE(SUM(waiting_user_exits), 0) as waiting_user,
                    COALESCE(SUM(goal_completed), 0) as completed,
                    COUNT(*) - COALESCE(SUM(goal_completed), 0) as failed,
                    COALESCE(SUM(sub_goals_completed), 0) as sub_completed,
                    COALESCE(SUM(sub_goals_failed), 0) as sub_failed
                FROM goal_runs
            """).fetchone()

        return dict(row) if row else {}

    def get_aggregated_surprises(self, agent_id: str = "") -> dict:
        """聚合所有 runs 的 surprises_detected。"""
        conn = self._get_conn()
        if agent_id:
            rows = conn.execute(
                "SELECT surprises_detected FROM goal_runs WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT surprises_detected FROM goal_runs",
            ).fetchall()

        aggregated: dict[str, int] = {}
        for row in rows:
            try:
                data = json.loads(row[0]) if row[0] else {}
                for k, v in data.items():
                    aggregated[k] = aggregated.get(k, 0) + v
            except (json.JSONDecodeError, TypeError):
                pass
        return aggregated
