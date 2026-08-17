"""SQLite persistence for Missions, bounded Runs, and append-only Events."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import Mission, MissionEvent, MissionRun, MissionRunStatus, MissionStatus

SCHEMA_COMPONENT = "missions"
SCHEMA_VERSION = 2


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback


class MissionStore(SQLiteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        current_version = self._get_schema_version(SCHEMA_COMPONENT)
        if current_version >= SCHEMA_VERSION:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                priority REAL NOT NULL DEFAULT 0.5,
                accountable_person_id TEXT NOT NULL DEFAULT '',
                origin_session_id TEXT NOT NULL DEFAULT '',
                origin_turn_id TEXT NOT NULL DEFAULT '',
                skill_name TEXT NOT NULL DEFAULT '',
                success_criteria_json TEXT NOT NULL DEFAULT '[]',
                constraints_json TEXT NOT NULL DEFAULT '[]',
                permissions_json TEXT NOT NULL DEFAULT '[]',
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                progress_summary TEXT NOT NULL DEFAULT '',
                waiting_reason TEXT NOT NULL DEFAULT '',
                waiting_for_json TEXT NOT NULL DEFAULT '[]',
                next_run_at REAL,
                last_run_at REAL,
                created_by TEXT NOT NULL DEFAULT 'user',
                revision INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_missions_status_due
                ON missions(status, next_run_at, priority DESC);
            CREATE INDEX IF NOT EXISTS idx_missions_person
                ON missions(accountable_person_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS mission_runs (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_intent_id TEXT NOT NULL DEFAULT '',
                runtime_session_id TEXT NOT NULL DEFAULT '',
                result_summary TEXT NOT NULL DEFAULT '',
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                error_message TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mission_runs_mission
                ON mission_runs(mission_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS mission_events (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mission_events_mission
                ON mission_events(mission_id, created_at DESC);
        """)
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(missions)").fetchall()
        }
        if "waiting_reason" not in columns:
            conn.execute(
                "ALTER TABLE missions ADD COLUMN waiting_reason TEXT NOT NULL DEFAULT ''"
            )
        if "waiting_for_json" not in columns:
            conn.execute(
                "ALTER TABLE missions ADD COLUMN waiting_for_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def create_mission(self, values: dict[str, Any]) -> Mission:
        now = time.time()
        mission_id = str(values.get("id") or f"mission_{uuid.uuid4().hex}")
        self._get_conn().execute(
            """INSERT INTO missions (
                id, title, objective, status, priority, accountable_person_id,
                origin_session_id, origin_turn_id, skill_name,
                success_criteria_json, constraints_json, permissions_json,
                checkpoint_json, progress_summary, waiting_reason,
                waiting_for_json, next_run_at, last_run_at,
                created_by, revision, created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)""",
            (
                mission_id, values["title"], values["objective"], values["status"],
                values.get("priority", 0.5), values.get("accountable_person_id", ""),
                values.get("origin_session_id", ""), values.get("origin_turn_id", ""),
                values.get("skill_name", ""),
                json.dumps(values.get("success_criteria", []), ensure_ascii=False),
                json.dumps(values.get("constraints", []), ensure_ascii=False),
                json.dumps(values.get("permissions", []), ensure_ascii=False),
                json.dumps(values.get("checkpoint", {}), ensure_ascii=False),
                values.get("progress_summary", ""),
                values.get("waiting_reason", ""),
                json.dumps(values.get("waiting_for", []), ensure_ascii=False),
                values.get("next_run_at"),
                values.get("last_run_at"), values.get("created_by", "user"), now, now,
            ),
        )
        self._get_conn().commit()
        return self.require_mission(mission_id)

    def get_mission(self, mission_id: str) -> Mission | None:
        row = self._get_conn().execute(
            "SELECT * FROM missions WHERE id = ?", (mission_id,),
        ).fetchone()
        return self._mission(row) if row else None

    def require_mission(self, mission_id: str) -> Mission:
        mission = self.get_mission(mission_id)
        if mission is None:
            raise KeyError(f"Mission not found: {mission_id}")
        return mission

    def list_missions(self, status: str = "", limit: int = 100) -> list[Mission]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, min(int(limit), 500)))
        rows = self._get_conn().execute(
            f"SELECT * FROM missions {where} ORDER BY priority DESC, updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [self._mission(row) for row in rows]

    def list_due(self, now: float, limit: int = 20) -> list[Mission]:
        rows = self._get_conn().execute(
            """SELECT * FROM missions
               WHERE status = 'active' AND (next_run_at IS NULL OR next_run_at <= ?)
               ORDER BY priority DESC, COALESCE(next_run_at, 0), updated_at
               LIMIT ?""",
            (now, max(1, min(int(limit), 100))),
        ).fetchall()
        return [self._mission(row) for row in rows]

    def update_mission(self, mission_id: str, **changes: Any) -> Mission:
        allowed = {
            "title", "objective", "status", "priority", "skill_name",
            "success_criteria", "constraints", "permissions", "checkpoint",
            "progress_summary", "waiting_reason", "waiting_for",
            "next_run_at", "last_run_at", "completed_at",
        }
        columns: list[str] = []
        values: list[Any] = []
        json_columns = {
            "success_criteria": "success_criteria_json",
            "constraints": "constraints_json",
            "permissions": "permissions_json",
            "checkpoint": "checkpoint_json",
            "waiting_for": "waiting_for_json",
        }
        for key, value in changes.items():
            if key not in allowed:
                continue
            column = json_columns.get(key, key)
            if key in json_columns:
                value = json.dumps(value, ensure_ascii=False)
            columns.append(f"{column} = ?")
            values.append(value)
        if not columns:
            return self.require_mission(mission_id)
        columns.extend(["revision = revision + 1", "updated_at = ?"])
        values.extend([time.time(), mission_id])
        cursor = self._get_conn().execute(
            f"UPDATE missions SET {', '.join(columns)} WHERE id = ?", tuple(values),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Mission not found: {mission_id}")
        self._get_conn().commit()
        return self.require_mission(mission_id)

    def create_run(self, mission_id: str, trigger_intent_id: str, runtime_session_id: str) -> MissionRun:
        run_id = f"mission_run_{uuid.uuid4().hex}"
        started_at = time.time()
        self._get_conn().execute(
            """INSERT INTO mission_runs (
                id, mission_id, status, trigger_intent_id, runtime_session_id, started_at
            ) VALUES (?, ?, 'running', ?, ?, ?)""",
            (run_id, mission_id, trigger_intent_id, runtime_session_id, started_at),
        )
        self._get_conn().commit()
        return self.require_run(run_id)

    def finish_run(self, run_id: str, status: MissionRunStatus, *, result_summary: str = "", checkpoint: dict[str, Any] | None = None, error_message: str = "") -> MissionRun:
        cursor = self._get_conn().execute(
            """UPDATE mission_runs SET status = ?, result_summary = ?, checkpoint_json = ?,
               error_message = ?, completed_at = ? WHERE id = ?""",
            (status.value, result_summary, json.dumps(checkpoint or {}, ensure_ascii=False), error_message, time.time(), run_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Mission run not found: {run_id}")
        self._get_conn().commit()
        return self.require_run(run_id)

    def require_run(self, run_id: str) -> MissionRun:
        row = self._get_conn().execute(
            "SELECT * FROM mission_runs WHERE id = ?", (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Mission run not found: {run_id}")
        return self._run(row)

    def add_event(self, mission_id: str, event_type: str, summary: str = "", *, run_id: str = "", details: dict[str, Any] | None = None) -> MissionEvent:
        event_id = f"mission_event_{uuid.uuid4().hex}"
        created_at = time.time()
        self._get_conn().execute(
            """INSERT INTO mission_events (
                id, mission_id, run_id, event_type, summary, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, mission_id, run_id, event_type, summary, json.dumps(details or {}, ensure_ascii=False), created_at),
        )
        self._get_conn().commit()
        return MissionEvent(event_id, mission_id, run_id, event_type, summary, details or {}, created_at)

    def list_events(self, mission_id: str, limit: int = 20) -> list[MissionEvent]:
        rows = self._get_conn().execute(
            "SELECT * FROM mission_events WHERE mission_id = ? ORDER BY created_at DESC LIMIT ?",
            (mission_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [MissionEvent(
            id=row["id"], mission_id=row["mission_id"], run_id=row["run_id"],
            event_type=row["event_type"], summary=row["summary"],
            details=dict(_json(row["details_json"], {})), created_at=float(row["created_at"]),
        ) for row in rows]

    @staticmethod
    def _mission(row: Any) -> Mission:
        return Mission(
            id=row["id"], title=row["title"], objective=row["objective"],
            status=MissionStatus(row["status"]), priority=float(row["priority"]),
            accountable_person_id=row["accountable_person_id"],
            origin_session_id=row["origin_session_id"], origin_turn_id=row["origin_turn_id"],
            skill_name=row["skill_name"],
            success_criteria=tuple(_json(row["success_criteria_json"], [])),
            constraints=tuple(_json(row["constraints_json"], [])),
            permissions=tuple(_json(row["permissions_json"], [])),
            checkpoint=dict(_json(row["checkpoint_json"], {})),
            progress_summary=row["progress_summary"],
            waiting_reason=row["waiting_reason"],
            waiting_for=tuple(dict(item) for item in _json(row["waiting_for_json"], [])),
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"], created_by=row["created_by"],
            revision=int(row["revision"]), created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]), completed_at=row["completed_at"],
        )

    @staticmethod
    def _run(row: Any) -> MissionRun:
        return MissionRun(
            id=row["id"], mission_id=row["mission_id"], status=MissionRunStatus(row["status"]),
            trigger_intent_id=row["trigger_intent_id"], runtime_session_id=row["runtime_session_id"],
            result_summary=row["result_summary"], checkpoint=dict(_json(row["checkpoint_json"], {})),
            error_message=row["error_message"], started_at=float(row["started_at"]),
            completed_at=row["completed_at"],
        )
