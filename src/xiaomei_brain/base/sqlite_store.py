"""Shared SQLite base class for brain.db consumers.

All classes that use the same SQLite database file inherit from this to
get lazy connection management, standard PRAGMAs, directory creation,
and component-level schema version tracking.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


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
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
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
