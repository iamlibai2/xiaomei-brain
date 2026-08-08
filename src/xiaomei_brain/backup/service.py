"""Small, reliable SQLite snapshots used as the first recovery boundary."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupSnapshot:
    path: Path
    created_at: float
    reason: str
    databases: tuple[str, ...]


class AgentBackupService:
    """Create consistent copies of the Agent's SQLite databases.

    This intentionally starts small: it provides whole-Agent database
    recovery without introducing record-level rollback or a backup UI. Asset
    blobs will join the same snapshot manifest when the unified AssetService
    owns them.
    """

    def __init__(
        self,
        agent_root: str | Path,
        database_paths: Iterable[str | Path],
        *,
        retention: int = 7,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.agent_root = Path(agent_root).expanduser().resolve()
        self.backup_root = self.agent_root / "backups"
        self.database_paths = tuple(
            Path(item).expanduser().resolve() for item in database_paths
        )
        self.retention = max(1, retention)
        self._clock = clock

    def backup_if_due(
        self,
        *,
        max_age_seconds: float = 24 * 60 * 60,
        reason: str = "scheduled",
    ) -> BackupSnapshot | None:
        latest = self._read_latest()
        now = self._clock()
        if latest is not None and now - latest.created_at < max_age_seconds:
            return None
        return self.backup_now(reason=reason, now=now)

    def backup_now(
        self,
        *,
        reason: str,
        now: float | None = None,
    ) -> BackupSnapshot:
        created_at = self._clock() if now is None else now
        stamp = datetime.fromtimestamp(created_at, tz=timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        snapshot_dir = self.backup_root / f"snapshot-{stamp}-{uuid4().hex[:8]}"
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        copied: list[str] = []
        try:
            for source in self.database_paths:
                if not source.is_file():
                    continue
                target = snapshot_dir / source.name
                self._backup_sqlite(source, target)
                copied.append(source.name)
            manifest = {
                "created_at": created_at,
                "reason": reason,
                "databases": copied,
            }
            self._write_json(snapshot_dir / "manifest.json", manifest)
            self.backup_root.mkdir(parents=True, exist_ok=True)
            self._write_json(
                self.backup_root / "latest.json",
                {**manifest, "snapshot": snapshot_dir.name},
            )
        except Exception:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            raise
        self._prune()
        logger.info(
            "[Backup] Agent snapshot created: %s (%s)", snapshot_dir, reason,
        )
        return BackupSnapshot(
            path=snapshot_dir,
            created_at=created_at,
            reason=reason,
            databases=tuple(copied),
        )

    @staticmethod
    def _backup_sqlite(source: Path, target: Path) -> None:
        source_conn = sqlite3.connect(str(source))
        target_conn = sqlite3.connect(str(target))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()

    def _read_latest(self) -> BackupSnapshot | None:
        marker = self.backup_root / "latest.json"
        if not marker.is_file():
            return None
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            snapshot = self.backup_root / str(payload["snapshot"])
            return BackupSnapshot(
                path=snapshot,
                created_at=float(payload["created_at"]),
                reason=str(payload.get("reason") or ""),
                databases=tuple(str(item) for item in payload.get("databases", [])),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("[Backup] Ignoring invalid latest marker: %s", marker)
            return None

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        temporary.replace(path)

    def _prune(self) -> None:
        snapshots = sorted(
            (
                item for item in self.backup_root.glob("snapshot-*")
                if item.is_dir()
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        for stale in snapshots[self.retention:]:
            shutil.rmtree(stale, ignore_errors=True)
