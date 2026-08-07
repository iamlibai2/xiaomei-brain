"""Encrypted persistence for Person-scoped external service accounts.

External accounts are deliberately separate from ``identity_bindings``:
identity bindings prove who a Person is, while an external account grants that
Person permission to let the Agent operate another service on their behalf.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from xiaomei_brain.base.sqlite_store import SQLiteStore

from .models import ExternalAccount


SCHEMA_COMPONENT = "external_accounts"
SCHEMA_VERSION = 1


class ExternalAccountStore(SQLiteStore):
    """Store account metadata in brain.db and encrypt OAuth credentials."""

    def __init__(self, db_path: str | Path, secret_key_path: str | Path) -> None:
        super().__init__(db_path)
        self.secret_key_path = Path(secret_key_path)
        self._cipher = Fernet(self._load_or_create_key())
        self._ensure_tables()

    def _load_or_create_key(self) -> bytes:
        path = self.secret_key_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            key = path.read_bytes().strip()
            try:
                Fernet(key)
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"外部账户密钥无效: {path}") from exc
            return key

        key = Fernet.generate_key()
        # Exclusive creation prevents two concurrent Agent startups from
        # silently replacing a key that already encrypted credentials.
        try:
            with path.open("xb") as handle:
                handle.write(key)
        except FileExistsError:
            key = path.read_bytes().strip()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        if self._get_schema_version(SCHEMA_COMPONENT) >= SCHEMA_VERSION:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS external_accounts (
                account_id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                subject TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                scopes_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                credential_ciphertext TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_verified_at REAL,
                revoked_at REAL,
                UNIQUE (person_id, provider, subject)
            );

            CREATE INDEX IF NOT EXISTS idx_external_accounts_person_provider
                ON external_accounts(person_id, provider, status, updated_at DESC);
            """
        )
        conn.commit()
        self._set_schema_version(SCHEMA_COMPONENT, SCHEMA_VERSION)

    def save(
        self,
        *,
        person_id: str,
        provider: str,
        subject: str,
        credentials: dict[str, Any],
        display_name: str = "",
        scopes: list[str] | tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> ExternalAccount:
        person_id = person_id.strip()
        provider = provider.strip().lower()
        subject = subject.strip()
        if not person_id or not provider or not subject:
            raise ValueError("person_id、provider 和 subject 不能为空")
        timestamp = time.time() if now is None else now
        ciphertext = self._cipher.encrypt(
            json.dumps(credentials, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        conn = self._get_conn()
        existing = conn.execute(
            """
            SELECT account_id, created_at FROM external_accounts
            WHERE person_id = ? AND provider = ? AND subject = ?
            """,
            (person_id, provider, subject),
        ).fetchone()
        account_id = str(existing["account_id"]) if existing else f"account_{uuid.uuid4().hex}"
        created_at = float(existing["created_at"]) if existing else timestamp
        conn.execute(
            """
            INSERT INTO external_accounts (
                account_id, person_id, provider, subject, display_name, status,
                scopes_json, metadata_json, credential_ciphertext, created_at,
                updated_at, last_verified_at, revoked_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(person_id, provider, subject) DO UPDATE SET
                display_name = excluded.display_name,
                status = 'active',
                scopes_json = excluded.scopes_json,
                metadata_json = excluded.metadata_json,
                credential_ciphertext = excluded.credential_ciphertext,
                updated_at = excluded.updated_at,
                last_verified_at = excluded.last_verified_at,
                revoked_at = NULL
            """,
            (
                account_id,
                person_id,
                provider,
                subject,
                display_name.strip(),
                json.dumps(sorted(set(scopes)), ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                ciphertext,
                created_at,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        account = self.get(account_id)
        if account is None:
            raise RuntimeError("外部账户保存失败")
        return account

    def get(self, account_id: str) -> ExternalAccount | None:
        row = self._get_conn().execute(
            "SELECT * FROM external_accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def get_active(self, person_id: str, provider: str) -> ExternalAccount | None:
        row = self._get_conn().execute(
            """
            SELECT * FROM external_accounts
            WHERE person_id = ? AND provider = ? AND status = 'active'
              AND revoked_at IS NULL
            ORDER BY last_verified_at DESC, updated_at DESC
            LIMIT 1
            """,
            (person_id.strip(), provider.strip().lower()),
        ).fetchone()
        return self._from_row(row) if row else None

    def list_for_person(self, person_id: str) -> list[ExternalAccount]:
        rows = self._get_conn().execute(
            """
            SELECT * FROM external_accounts
            WHERE person_id = ?
            ORDER BY status = 'active' DESC, updated_at DESC
            """,
            (person_id.strip(),),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def credentials(self, account_id: str) -> dict[str, Any]:
        row = self._get_conn().execute(
            "SELECT credential_ciphertext FROM external_accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise KeyError(account_id)
        try:
            plaintext = self._cipher.decrypt(str(row[0]).encode("ascii"))
            value = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("外部账户凭据无法解密") from exc
        if not isinstance(value, dict):
            raise RuntimeError("外部账户凭据格式无效")
        return value

    def update_credentials(
        self,
        account_id: str,
        credentials: dict[str, Any],
        *,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else now
        ciphertext = self._cipher.encrypt(
            json.dumps(credentials, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        cur = self._get_conn().execute(
            """
            UPDATE external_accounts
            SET credential_ciphertext = ?, updated_at = ?, last_verified_at = ?
            WHERE account_id = ? AND status = 'active'
            """,
            (ciphertext, timestamp, timestamp, account_id),
        )
        self._get_conn().commit()
        if cur.rowcount == 0:
            raise KeyError(account_id)

    def revoke(self, person_id: str, provider: str, *, now: float | None = None) -> int:
        timestamp = time.time() if now is None else now
        cur = self._get_conn().execute(
            """
            UPDATE external_accounts
            SET status = 'revoked', revoked_at = ?, updated_at = ?
            WHERE person_id = ? AND provider = ? AND status = 'active'
            """,
            (timestamp, timestamp, person_id.strip(), provider.strip().lower()),
        )
        self._get_conn().commit()
        return cur.rowcount

    @staticmethod
    def _from_row(row: Any) -> ExternalAccount:
        def load_json(value: str, fallback: Any) -> Any:
            try:
                parsed = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return fallback
            return parsed

        scopes = load_json(str(row["scopes_json"]), [])
        metadata = load_json(str(row["metadata_json"]), {})
        return ExternalAccount(
            account_id=str(row["account_id"]),
            person_id=str(row["person_id"]),
            provider=str(row["provider"]),
            subject=str(row["subject"]),
            display_name=str(row["display_name"]),
            status=str(row["status"]),
            scopes=tuple(str(value) for value in scopes if isinstance(value, str)),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_verified_at=(
                float(row["last_verified_at"])
                if row["last_verified_at"] is not None
                else None
            ),
            revoked_at=float(row["revoked_at"]) if row["revoked_at"] is not None else None,
        )
