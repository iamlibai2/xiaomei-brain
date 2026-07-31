"""Shared SQLite base class for brain.db consumers.

All classes that use the same SQLite database file inherit from this to
get lazy connection management, standard PRAGMAs, directory creation,
and component-level schema version tracking.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_coordinator_guard = threading.Lock()
_database_write_locks: dict[str, threading.RLock] = {}


def _database_lock(database: str | Path) -> threading.RLock:
    """Return the process-local single-writer lock for one SQLite file."""
    key = os.path.normcase(str(Path(database).expanduser().resolve()))
    with _coordinator_guard:
        lock = _database_write_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _database_write_locks[key] = lock
        return lock


def _statement_writes(sql: str) -> bool:
    """Conservatively classify statements that may acquire a SQLite write lock."""
    statement = str(sql or "").lstrip()
    while statement.startswith("--"):
        _line, _separator, statement = statement.partition("\n")
        statement = statement.lstrip()
    keyword = statement.split(None, 1)[0].upper() if statement else ""
    if keyword == "PRAGMA":
        normalized = statement.upper()
        return (
            "=" in statement
            or "JOURNAL_MODE" in normalized
            or "WAL_CHECKPOINT" in normalized
        )
    return keyword not in {"", "SELECT", "EXPLAIN"}


class CoordinatedConnection(sqlite3.Connection):
    """SQLite connection coordinated with every store using the same DB file.

    SQLite WAL still permits concurrent readers, while writes are serialized
    before they enter SQLite.  The process lock is retained from the first
    write/BEGIN until commit or rollback, preserving each store's existing
    transaction boundary.

    A connection is also sealed to the thread owning its active transaction.
    ``check_same_thread=False`` remains useful for long-lived Agent services,
    but two threads can no longer accidentally interleave statements inside
    one transaction.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        database = str(args[0]) if args else str(kwargs.get("database", ""))
        self._database_name = str(Path(database).expanduser().resolve())
        self._database_write_lock = _database_lock(database)
        self._transaction_gate = threading.RLock()
        self._transaction_owner: int | None = None
        self._write_lock_held = False

    def _enter(self, *, write: bool) -> None:
        thread_id = threading.get_ident()
        if self._transaction_owner != thread_id:
            self._transaction_gate.acquire()
            self._transaction_owner = thread_id
        if write and not self._write_lock_held:
            started = time.monotonic()
            self._database_write_lock.acquire()
            waited = time.monotonic() - started
            if waited >= 1.0:
                logger.warning(
                    "[SQLite] write waited %.2fs for process coordinator: %s",
                    waited,
                    self._database_name,
                )
            self._write_lock_held = True

    def _leave_if_complete(self) -> None:
        if self.in_transaction:
            return
        if self._write_lock_held:
            self._write_lock_held = False
            self._database_write_lock.release()
        if self._transaction_owner is not None:
            self._transaction_owner = None
            self._transaction_gate.release()

    def execute(
        self,
        sql: str,
        parameters: Any = (),
        /,
    ) -> sqlite3.Cursor:
        self._enter(write=_statement_writes(sql))
        try:
            cursor = super().execute(sql, parameters)
        except Exception:
            self._leave_if_complete()
            raise
        self._leave_if_complete()
        return cursor

    def executemany(
        self,
        sql: str,
        seq_of_parameters: Any,
        /,
    ) -> sqlite3.Cursor:
        self._enter(write=_statement_writes(sql))
        try:
            cursor = super().executemany(sql, seq_of_parameters)
        except Exception:
            self._leave_if_complete()
            raise
        self._leave_if_complete()
        return cursor

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        self._enter(write=True)
        try:
            cursor = super().executescript(sql_script)
        except Exception:
            self._leave_if_complete()
            raise
        self._leave_if_complete()
        return cursor

    def commit(self) -> None:
        self._enter(write=False)
        try:
            super().commit()
        finally:
            self._leave_if_complete()

    def rollback(self) -> None:
        self._enter(write=False)
        try:
            super().rollback()
        finally:
            self._leave_if_complete()

    def close(self) -> None:
        self._enter(write=False)
        try:
            if self.in_transaction:
                super().rollback()
            super().close()
        finally:
            # ``in_transaction`` cannot be queried after close.
            if self._write_lock_held:
                self._write_lock_held = False
                self._database_write_lock.release()
            if self._transaction_owner is not None:
                self._transaction_owner = None
                self._transaction_gate.release()


class SQLiteStore:
    """Shared base for all classes using the brain.db SQLite database.

    Provides:
    - Lazy connection with check_same_thread=False and row_factory=Row
    - WAL journal mode + foreign_keys ON
    - Automatic parent directory creation
    - _configure_connection() hook for subclass-specific PRAGMAs
    - Component-level schema version tracking via schema_versions table
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                factory=CoordinatedConnection,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout = 15000")
            self._configure_connection(self._conn)
            self._ensure_schema_versions_table()
        return self._conn

    def _ensure_schema_versions_table(self) -> None:
        """Create the shared schema_versions table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def _get_schema_version(self, component: str) -> int:
        """Get the current schema version for a component."""
        row = self._conn.execute(
            "SELECT version FROM schema_versions WHERE component = ?", (component,)
        ).fetchone()
        return row[0] if row else 0

    def _set_schema_version(self, component: str, version: int) -> None:
        """Set the schema version for a component."""
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_versions (component, version) VALUES (?, ?)",
            (component, version),
        )
        self._conn.commit()

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        """Override in subclasses to add extra PRAGMAs or settings."""

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
