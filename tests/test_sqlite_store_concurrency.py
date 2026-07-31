"""Concurrency guarantees shared by all Agent-local SQLite stores."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from xiaomei_brain.base.sqlite_store import SQLiteStore
from xiaomei_brain.memory.experience_stream import ExperienceStream


class _CounterStore(SQLiteStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self._get_conn().execute(
            "CREATE TABLE IF NOT EXISTS concurrency_values (value TEXT)",
        )
        self._get_conn().commit()

    def insert_transaction(
        self,
        value: str,
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO concurrency_values(value) VALUES (?)",
                (value,),
            )
            if entered is not None:
                entered.set()
            if release is not None:
                assert release.wait(timeout=5)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def values(self) -> list[str]:
        return [
            str(row[0])
            for row in self._get_conn().execute(
                "SELECT value FROM concurrency_values ORDER BY rowid",
            ).fetchall()
        ]


def test_same_database_writers_wait_before_entering_sqlite(tmp_path):
    """A second store must not consume SQLite's busy timeout."""
    path = tmp_path / "brain.db"
    first = _CounterStore(path)
    second = _CounterStore(path)
    # Without process-level coordination, this writer would fail immediately
    # while the first connection holds BEGIN IMMEDIATE.
    second._get_conn().execute("PRAGMA busy_timeout = 1")
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def hold_first_writer() -> None:
        try:
            first.insert_transaction("first", entered=entered, release=release)
        except BaseException as exc:
            errors.append(exc)

    def run_second_writer() -> None:
        try:
            second.insert_transaction("second")
        except BaseException as exc:
            errors.append(exc)

    thread_one = threading.Thread(target=hold_first_writer)
    thread_one.start()
    assert entered.wait(timeout=5)
    thread_two = threading.Thread(target=run_second_writer)
    thread_two.start()
    time.sleep(0.05)
    assert thread_two.is_alive()
    release.set()
    thread_one.join(timeout=5)
    thread_two.join(timeout=5)

    assert errors == []
    assert first.values() == ["first", "second"]
    first.close()
    second.close()


def test_experience_stream_serializes_concurrent_agent_events(tmp_path):
    stream = ExperienceStream(str(tmp_path / "brain.db"))

    def append(index: int) -> None:
        stream.log(
            type="activity_progress",
            content=f"event-{index}",
            related_id=f"activity-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(80)))

    rows = stream.get_recent(limit=100)
    assert len(rows) == 80
    assert {row["content"] for row in rows} == {
        f"event-{index}" for index in range(80)
    }
    stream.close()
