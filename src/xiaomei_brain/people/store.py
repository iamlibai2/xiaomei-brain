"""PeopleStore — Agent 本地人物与身份绑定的增量 SQLite 存储。"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from ..base.sqlite_store import SQLiteStore
from .models import (
    ConversationSession,
    IdentityBinding,
    IdentityEvent,
    IdentityLinkRequest,
    Person,
)

SCHEMA_VERSION = 2
SCHEMA_COMPONENT = "people"


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class PeopleStore(SQLiteStore):
    """管理新增人物表，不修改任何既有表或 ``user_id`` 字段。"""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        version = self._get_schema_version(SCHEMA_COMPONENT)
        if version >= SCHEMA_VERSION:
            return

        # People 是独立的增量组件。这里只能创建自己的表，不能顺手调整
        # messages/memories 等旧表，否则一次身份升级会扩散为全库迁移。
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                person_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                first_seen_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_persons_status
                ON persons(status, last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS identity_bindings (
                binding_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                issuer TEXT NOT NULL,
                subject TEXT NOT NULL,
                credential_type TEXT NOT NULL,
                public_key TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                last_verified_at REAL,
                revoked_at REAL,
                FOREIGN KEY (person_id) REFERENCES persons(person_id)
                    ON DELETE CASCADE,
                -- 同一外部主体在一个 Agent 世界中只能指向一个 Person。
                UNIQUE (issuer, subject)
            );

            CREATE INDEX IF NOT EXISTS idx_identity_bindings_person
                ON identity_bindings(person_id, revoked_at);

            CREATE TABLE IF NOT EXISTS identity_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT,
                event_type TEXT NOT NULL,
                issuer TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY (person_id) REFERENCES persons(person_id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_identity_events_person
                ON identity_events(person_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS conversation_sessions (
                session_id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conversation_sessions_scope
                ON conversation_sessions(scope_type, scope_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS identity_link_requests (
                request_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                issuer TEXT NOT NULL,
                code_salt TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                subject TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY (person_id) REFERENCES persons(person_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_identity_link_requests_lookup
                ON identity_link_requests(provider, issuer, status, expires_at);

            CREATE INDEX IF NOT EXISTS idx_identity_link_requests_person
                ON identity_link_requests(person_id, created_at DESC);
        """)
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    # ── Person ──────────────────────────────────────────────────

    def create_person(
        self,
        display_name: str,
        *,
        person_id: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
        if_not_exists: bool = False,
    ) -> Person:
        person_id = (person_id or _new_id("person")).strip()
        display_name = display_name.strip()
        if not person_id:
            raise ValueError("person_id 不能为空")
        if not display_name:
            raise ValueError("display_name 不能为空")

        timestamp = time.time() if now is None else now
        sql = "INSERT OR IGNORE" if if_not_exists else "INSERT"
        conn = self._get_conn()
        conn.execute(
            f"""
            {sql} INTO persons (
                person_id, display_name, status, first_seen_at, last_seen_at,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                display_name,
                status,
                timestamp,
                timestamp,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        person = self.get_person(person_id)
        if person is None:
            raise RuntimeError(f"人物创建失败: {person_id}")
        return person

    def get_person(self, person_id: str) -> Person | None:
        row = self._get_conn().execute(
            "SELECT * FROM persons WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        return self._person_from_row(row) if row else None

    def list_people(self, *, status: str | None = None) -> list[Person]:
        conn = self._get_conn()
        if status is None:
            rows = conn.execute(
                "SELECT * FROM persons ORDER BY last_seen_at DESC, person_id",
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM persons
                WHERE status = ?
                ORDER BY last_seen_at DESC, person_id
                """,
                (status,),
            ).fetchall()
        return [self._person_from_row(row) for row in rows]

    def touch_person(self, person_id: str, *, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        cur = self._get_conn().execute(
            """
            UPDATE persons
            SET last_seen_at = ?, updated_at = ?
            WHERE person_id = ?
            """,
            (timestamp, timestamp, person_id),
        )
        self._get_conn().commit()
        return cur.rowcount > 0

    def register_person_with_binding(
        self,
        display_name: str,
        issuer: str,
        subject: str,
        credential_type: str,
        public_key: str,
        *,
        person_id: str | None = None,
        now: float | None = None,
    ) -> tuple[Person, IdentityBinding]:
        """在同一事务中创建 Person 和首个已验证身份绑定。"""
        person_id = (person_id or _new_id("person")).strip()
        binding_id = _new_id("binding")
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO persons (
                    person_id, display_name, status, first_seen_at,
                    last_seen_at, metadata_json, created_at, updated_at
                ) VALUES (?, ?, 'active', ?, ?, '{}', ?, ?)
                """,
                (
                    person_id,
                    display_name.strip(),
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO identity_bindings (
                    binding_id, person_id, issuer, subject, credential_type,
                    public_key, metadata_json, created_at, last_verified_at,
                    revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, NULL)
                """,
                (
                    binding_id,
                    person_id,
                    issuer,
                    subject,
                    credential_type,
                    public_key,
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            # 不能留下“有人物但没有身份证明”的半完成登记。
            conn.rollback()
            raise ValueError(f"外部身份已登记: {issuer}/{subject}") from exc

        person = self.get_person(person_id)
        binding = self.get_binding(binding_id)
        if person is None or binding is None:
            raise RuntimeError("人物身份登记未完整写入")
        return person, binding

    # ── Identity binding ────────────────────────────────────────

    def create_binding(
        self,
        person_id: str,
        issuer: str,
        subject: str,
        credential_type: str,
        *,
        public_key: str = "",
        metadata: dict[str, Any] | None = None,
        binding_id: str | None = None,
        verified_at: float | None = None,
        now: float | None = None,
    ) -> IdentityBinding:
        issuer = issuer.strip()
        subject = subject.strip()
        credential_type = credential_type.strip()
        if not issuer or not subject or not credential_type:
            raise ValueError("issuer、subject 和 credential_type 不能为空")
        # 绑定必须落到已经存在的本地人物，不能由一个外部账号隐式造人。
        if self.get_person(person_id) is None:
            raise ValueError(f"人物不存在: {person_id}")

        timestamp = time.time() if now is None else now
        binding_id = binding_id or _new_id("binding")
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO identity_bindings (
                    binding_id, person_id, issuer, subject, credential_type,
                    public_key, metadata_json, created_at, last_verified_at,
                    revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    binding_id,
                    person_id,
                    issuer,
                    subject,
                    credential_type,
                    public_key,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    timestamp,
                    verified_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError(f"外部身份已绑定: {issuer}/{subject}") from exc
        conn.commit()
        binding = self.get_binding(binding_id)
        if binding is None:
            raise RuntimeError(f"身份绑定创建失败: {binding_id}")
        return binding

    def get_binding(self, binding_id: str) -> IdentityBinding | None:
        row = self._get_conn().execute(
            "SELECT * FROM identity_bindings WHERE binding_id = ?",
            (binding_id,),
        ).fetchone()
        return self._binding_from_row(row) if row else None

    def resolve_identity(
        self,
        issuer: str,
        subject: str,
        *,
        include_revoked: bool = False,
    ) -> IdentityBinding | None:
        sql = """
            SELECT * FROM identity_bindings
            WHERE issuer = ? AND subject = ?
        """
        # 撤销后保留审计数据，但绝不能再用于认证。
        if not include_revoked:
            sql += " AND revoked_at IS NULL"
        row = self._get_conn().execute(sql, (issuer, subject)).fetchone()
        return self._binding_from_row(row) if row else None

    def list_bindings(
        self,
        person_id: str,
        *,
        include_revoked: bool = False,
    ) -> list[IdentityBinding]:
        sql = "SELECT * FROM identity_bindings WHERE person_id = ?"
        if not include_revoked:
            sql += " AND revoked_at IS NULL"
        sql += " ORDER BY created_at, binding_id"
        rows = self._get_conn().execute(sql, (person_id,)).fetchall()
        return [self._binding_from_row(row) for row in rows]

    def revoke_binding(
        self,
        binding_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE identity_bindings
            SET revoked_at = ?
            WHERE binding_id = ? AND revoked_at IS NULL
            """,
            (timestamp, binding_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def mark_binding_verified(
        self,
        binding_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE identity_bindings
            SET last_verified_at = ?
            WHERE binding_id = ? AND revoked_at IS NULL
            """,
            (timestamp, binding_id),
        )
        conn.commit()
        return cur.rowcount > 0

    # ── Audit ───────────────────────────────────────────────────

    def create_link_request(
        self,
        person_id: str,
        provider: str,
        issuer: str,
        code_salt: str,
        code_hash: str,
        expires_at: float,
        *,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> IdentityLinkRequest:
        """Create one pending external identity link and cancel its predecessor."""
        if self.get_person(person_id) is None:
            raise ValueError(f"人物不存在: {person_id}")
        timestamp = time.time() if now is None else now
        request_id = request_id or _new_id("link")
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE identity_link_requests
            SET status = 'cancelled'
            WHERE person_id = ? AND provider = ? AND issuer = ?
              AND status = 'pending'
            """,
            (person_id, provider, issuer),
        )
        conn.execute(
            """
            INSERT INTO identity_link_requests (
                request_id, person_id, provider, issuer, code_salt,
                code_hash, status, subject, metadata_json, created_at,
                expires_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?, ?, ?, NULL)
            """,
            (
                request_id,
                person_id,
                provider,
                issuer,
                code_salt,
                code_hash,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
                expires_at,
            ),
        )
        conn.commit()
        request = self.get_link_request(request_id)
        if request is None:
            raise RuntimeError("身份绑定请求创建失败")
        return request

    def get_link_request(self, request_id: str) -> IdentityLinkRequest | None:
        row = self._get_conn().execute(
            "SELECT * FROM identity_link_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return self._link_request_from_row(row) if row else None

    def list_pending_link_requests(
        self,
        provider: str,
        issuer: str,
        *,
        now: float | None = None,
    ) -> list[IdentityLinkRequest]:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE identity_link_requests
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at <= ?
            """,
            (timestamp,),
        )
        conn.commit()
        rows = conn.execute(
            """
            SELECT * FROM identity_link_requests
            WHERE provider = ? AND issuer = ?
              AND status = 'pending' AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (provider, issuer, timestamp),
        ).fetchall()
        return [self._link_request_from_row(row) for row in rows]

    def complete_link_request(
        self,
        request_id: str,
        subject: str,
        *,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE identity_link_requests
            SET status = 'completed', subject = ?, completed_at = ?
            WHERE request_id = ? AND status = 'pending' AND expires_at > ?
            """,
            (subject, timestamp, request_id, timestamp),
        )
        conn.commit()
        return cur.rowcount > 0

    def cancel_link_request(self, request_id: str, person_id: str) -> bool:
        conn = self._get_conn()
        cur = conn.execute(
            """
            UPDATE identity_link_requests
            SET status = 'cancelled'
            WHERE request_id = ? AND person_id = ? AND status = 'pending'
            """,
            (request_id, person_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def record_identity_event(
        self,
        event_type: str,
        *,
        person_id: str | None = None,
        issuer: str = "",
        subject: str = "",
        outcome: str = "",
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> IdentityEvent:
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO identity_events (
                person_id, event_type, issuer, subject, outcome,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                event_type,
                issuer,
                subject,
                outcome,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM identity_events WHERE event_id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return self._event_from_row(row)

    # ── Conversation session ────────────────────────────────────

    def ensure_session(
        self,
        session_id: str,
        scope_type: str,
        scope_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> ConversationSession:
        if not session_id or not scope_type or not scope_id:
            raise ValueError("session_id、scope_type 和 scope_id 不能为空")
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_sessions (
                session_id, scope_type, scope_id, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                scope_type,
                scope_id,
                json.dumps(metadata or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError(f"会话创建失败: {session_id}")
        # session_id 一旦建立就不能被重新解释为另一个人物或作用域。
        if session.scope_type != scope_type or session.scope_id != scope_id:
            raise ValueError(f"会话作用域不一致: {session_id}")
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        row = self._get_conn().execute(
            "SELECT * FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return self._session_from_row(row) if row else None

    def list_scope_session_ids(self, scope_type: str, scope_id: str) -> list[str]:
        rows = self._get_conn().execute(
            """
            SELECT session_id FROM conversation_sessions
            WHERE scope_type = ? AND scope_id = ?
            ORDER BY updated_at DESC
            """,
            (scope_type, scope_id),
        ).fetchall()
        return [str(row["session_id"]) for row in rows]

    def list_unclaimed_legacy_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出尚未进入人物作用域、但带有旧 user_id 证据的历史会话。"""
        conn = self._get_conn()
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        required = {"session_id", "user_id", "role", "content", "created_at", "id"}
        if not required.issubset(columns):
            return []
        rows = conn.execute(
            """
            SELECT
                m.session_id,
                MIN(m.created_at) AS created_at,
                MAX(m.created_at) AS updated_at,
                SUM(CASE WHEN m.role IN ('user', 'assistant') THEN 1 ELSE 0 END)
                    AS message_count,
                COALESCE((
                    SELECT SUBSTR(first_user.content, 1, 200)
                    FROM messages AS first_user
                    WHERE first_user.session_id = m.session_id
                      AND first_user.role = 'user'
                    ORDER BY first_user.created_at, first_user.id
                    LIMIT 1
                ), '') AS first_user_message
            FROM messages AS m
            LEFT JOIN conversation_sessions AS scoped
              ON scoped.session_id = m.session_id
            WHERE m.session_id <> ''
              AND scoped.session_id IS NULL
              AND m.user_id NOT IN ('', 'global', 'system')
            GROUP BY m.session_id
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["legacy_user_ids"] = sorted(self._legacy_session_person_ids(
                str(row["session_id"]),
            ))
            results.append(item)
        return results

    def claim_legacy_session(
        self,
        session_id: str,
        person_id: str,
        *,
        now: float | None = None,
    ) -> ConversationSession:
        """由本机管理者显式把旧会话关联到当前人物，不改写任何旧消息。"""
        timestamp = time.time() if now is None else now
        conn = self._get_conn()
        if self.get_person(person_id) is None:
            raise ValueError(f"人物不存在: {person_id}")
        if self.get_session(session_id) is not None:
            raise ValueError(f"会话已经有关联: {session_id}")
        legacy_user_ids = sorted(self._legacy_session_person_ids(session_id))
        if not legacy_user_ids:
            raise ValueError(f"会话没有可关联的旧身份记录: {session_id}")
        metadata = {
            "source": "legacy_explicit_claim",
            "legacy_user_ids": legacy_user_ids,
        }
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO conversation_sessions (
                    session_id, scope_type, scope_id, metadata_json,
                    created_at, updated_at
                ) VALUES (?, 'person', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    person_id,
                    json.dumps(metadata, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO identity_events (
                    person_id, event_type, issuer, subject, outcome,
                    metadata_json, created_at
                ) VALUES (?, 'legacy_session_claimed', '', '', 'success', ?, ?)
                """,
                (
                    person_id,
                    json.dumps(
                        {"session_id": session_id, **metadata},
                        ensure_ascii=False,
                    ),
                    timestamp,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        claimed = self.get_session(session_id)
        if claimed is None:
            raise RuntimeError(f"旧会话关联失败: {session_id}")
        return claimed

    def ensure_person_session(
        self,
        session_id: str,
        person_id: str,
    ) -> ConversationSession:
        """建立人物会话，并保护尚未登记到新表的旧会话历史。"""
        existing = self.get_session(session_id)
        if existing is not None:
            if existing.scope_type != "person" or existing.scope_id != person_id:
                raise ValueError(f"会话不属于当前人物: {session_id}")
            return existing

        legacy_people = self._legacy_session_person_ids(session_id)
        if legacy_people and person_id not in legacy_people:
            # 旧 messages.user_id 暂时不改，但仍可作为旧会话归属证据。
            raise ValueError(f"旧会话不属于当前人物: {session_id}")
        return self.ensure_session(session_id, "person", person_id)

    def session_is_unclaimed(self, session_id: str) -> bool:
        """新人物只能从没有新旧归属记录的会话开始。"""
        return (
            self.get_session(session_id) is None
            and not self._legacy_session_person_ids(session_id)
        )

    def _legacy_session_person_ids(self, session_id: str) -> set[str]:
        conn = self._get_conn()
        table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'messages'
            """,
        ).fetchone()
        if table is None:
            return set()
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if not {"session_id", "user_id"}.issubset(columns):
            return set()
        rows = conn.execute(
            """
            SELECT DISTINCT user_id FROM messages
            WHERE session_id = ?
              AND user_id NOT IN ('', 'global', 'system')
            """,
            (session_id,),
        ).fetchall()
        return {str(row["user_id"]) for row in rows if row["user_id"]}

    # ── Row mapping ─────────────────────────────────────────────

    @staticmethod
    def _person_from_row(row) -> Person:
        return Person(
            person_id=str(row["person_id"]),
            display_name=str(row["display_name"]),
            status=str(row["status"]),
            first_seen_at=float(row["first_seen_at"]),
            last_seen_at=float(row["last_seen_at"]),
            metadata=_json_loads(row["metadata_json"]),
        )

    @staticmethod
    def _binding_from_row(row) -> IdentityBinding:
        return IdentityBinding(
            binding_id=str(row["binding_id"]),
            person_id=str(row["person_id"]),
            issuer=str(row["issuer"]),
            subject=str(row["subject"]),
            credential_type=str(row["credential_type"]),
            public_key=str(row["public_key"]),
            metadata=_json_loads(row["metadata_json"]),
            created_at=float(row["created_at"]),
            last_verified_at=(
                float(row["last_verified_at"])
                if row["last_verified_at"] is not None
                else None
            ),
            revoked_at=(
                float(row["revoked_at"])
                if row["revoked_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _event_from_row(row) -> IdentityEvent:
        return IdentityEvent(
            event_id=int(row["event_id"]),
            person_id=(
                str(row["person_id"]) if row["person_id"] is not None else None
            ),
            event_type=str(row["event_type"]),
            issuer=str(row["issuer"]),
            subject=str(row["subject"]),
            outcome=str(row["outcome"]),
            metadata=_json_loads(row["metadata_json"]),
            created_at=float(row["created_at"]),
        )

    @staticmethod
    def _session_from_row(row) -> ConversationSession:
        return ConversationSession(
            session_id=str(row["session_id"]),
            scope_type=str(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            metadata=_json_loads(row["metadata_json"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _link_request_from_row(row) -> IdentityLinkRequest:
        return IdentityLinkRequest(
            request_id=str(row["request_id"]),
            person_id=str(row["person_id"]),
            provider=str(row["provider"]),
            issuer=str(row["issuer"]),
            code_salt=str(row["code_salt"]),
            code_hash=str(row["code_hash"]),
            status=str(row["status"]),
            subject=str(row["subject"]),
            metadata=_json_loads(row["metadata_json"]),
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            completed_at=(
                float(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
        )
