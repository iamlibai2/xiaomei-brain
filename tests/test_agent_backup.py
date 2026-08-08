from __future__ import annotations

import sqlite3

from xiaomei_brain.backup import AgentBackupService


def _database(path, value: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE state (value TEXT NOT NULL)")
    conn.execute("INSERT INTO state VALUES (?)", (value,))
    conn.commit()
    conn.close()


def test_agent_backup_creates_consistent_sqlite_snapshot(tmp_path):
    brain = tmp_path / "brain.db"
    workspace = tmp_path / "workspaces" / "workspaces.db"
    workspace.parent.mkdir()
    _database(brain, "brain")
    _database(workspace, "workspace")

    service = AgentBackupService(
        tmp_path, [brain, workspace], clock=lambda: 100.0,
    )
    snapshot = service.backup_now(reason="test")

    assert snapshot.databases == ("brain.db", "workspaces.db")
    for name, expected in (("brain.db", "brain"), ("workspaces.db", "workspace")):
        conn = sqlite3.connect(snapshot.path / name)
        assert conn.execute("SELECT value FROM state").fetchone()[0] == expected
        conn.close()


def test_agent_backup_skips_recent_snapshot_and_prunes_old_ones(tmp_path):
    brain = tmp_path / "brain.db"
    _database(brain, "brain")
    times = iter((100.0, 110.0, 200.0, 300.0))
    service = AgentBackupService(
        tmp_path, [brain], retention=2, clock=lambda: next(times),
    )

    first = service.backup_if_due(max_age_seconds=50)
    assert first is not None
    assert service.backup_if_due(max_age_seconds=50) is None
    service.backup_now(reason="second")
    service.backup_now(reason="third")

    snapshots = list((tmp_path / "backups").glob("snapshot-*"))
    assert len(snapshots) == 2
