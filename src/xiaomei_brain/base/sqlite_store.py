"""Shared SQLite base class for brain.db consumers.

All classes that use the same SQLite database file inherit from this to
get lazy connection management, standard PRAGMAs, and directory creation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteStore:
    """Shared base for all classes using the brain.db SQLite database.

    Provides:
    - Lazy connection with check_same_thread=False and row_factory=Row
    - WAL journal mode + foreign_keys ON
    - Automatic parent directory creation
    - _configure_connection() hook for subclass-specific PRAGMAs
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
            self._configure_connection(self._conn)
        return self._conn

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        """Override in subclasses to add extra PRAGMAs or settings."""

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
