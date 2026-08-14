"""Bounded JSONL diagnostics for embedding and semantic retrieval."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Callable, Iterator


logger = logging.getLogger(__name__)

_CURRENT_CONTEXT: ContextVar[dict[str, str]] = ContextVar(
    "xiaomei_vector_trace_context",
    default={},
)
_TRACE_CALLBACK: Callable[[dict[str, Any]], None] | None = None


def set_vector_trace_callback(callback: Callable[[dict[str, Any]], None] | None) -> None:
    """Bind the recorder owned by the current Agent process."""
    global _TRACE_CALLBACK
    _TRACE_CALLBACK = callback


@contextmanager
def vector_trace_context(
    *,
    person_id: str = "",
    session_id: str = "",
    turn_id: str = "",
) -> Iterator[None]:
    current = dict(_CURRENT_CONTEXT.get())
    current.update({
        "person_id": str(person_id or ""),
        "session_id": str(session_id or ""),
        "turn_id": str(turn_id or ""),
    })
    token = _CURRENT_CONTEXT.set(current)
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


def record_vector_trace(
    *,
    source: str,
    phase: str,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    selected: list[str] | None = None,
    threshold: float | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "ok",
    error: str = "",
    trace_id: str = "",
) -> None:
    """Record one complete fact without ever persisting an embedding vector."""
    if _TRACE_CALLBACK is None:
        return
    context = dict(_CURRENT_CONTEXT.get())
    payload: dict[str, Any] = {
        "id": str(trace_id or f"vector_{uuid.uuid4().hex}"),
        "created_at": time.time(),
        "source": str(source or "unknown")[:80],
        "phase": str(phase or "retrieval")[:40],
        "person_id": context.get("person_id", ""),
        "session_id": context.get("session_id", ""),
        "turn_id": context.get("turn_id", ""),
        "query": str(query or "")[:8000],
        "candidates": [_safe_candidate(item) for item in (candidates or [])[:50]],
        "selected": [str(item)[:300] for item in (selected or [])[:50]],
        "threshold": threshold,
        "status": str(status or "ok"),
        "error": str(error or "")[:2000],
        "metadata": _safe_value(metadata or {}),
    }
    try:
        _TRACE_CALLBACK(payload)
    except Exception:
        logger.debug("Unable to record vector trace", exc_info=True)


def _safe_candidate(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _safe_value(item)
        for key, item in value.items()
        if key not in {"vector", "embedding"}
    }


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value[:100]]
    return str(value)[:2000]


class VectorTraceStore:
    """Append-only JSONL store with small file rotation for one Agent."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backups: int = 3,
        on_change: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max(256 * 1024, int(max_bytes))
        self.backups = max(1, int(backups))
        self.on_change = on_change
        self._lock = threading.RLock()

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self.path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(line)
        if self.on_change is not None:
            try:
                self.on_change("vector.trace.created", self._summary(record))
            except Exception:
                logger.debug("Unable to publish vector trace event", exc_info=True)

    def list_records(
        self,
        *,
        session_id: str = "",
        source: str = "",
        phase: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        with self._lock:
            for path in self._paths_newest_first():
                records.extend(reversed(self._read_lines(path)))
        filtered = [
            item for item in records
            if (not session_id or item.get("session_id") == session_id)
            and (not source or item.get("source") == source)
            and (not phase or item.get("phase") == phase)
        ]
        start = max(0, int(offset))
        count = max(1, min(1000, int(limit)))
        return {"items": filtered[start:start + count], "total": len(filtered)}

    def clear(self) -> int:
        removed = 0
        with self._lock:
            for path in self._all_paths():
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        return removed

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = self.path.stat().st_size
        except FileNotFoundError:
            current_size = 0
        if current_size + incoming_bytes <= self.max_bytes:
            return
        oldest = self.path.with_suffix(self.path.suffix + f".{self.backups}")
        try:
            oldest.unlink()
        except FileNotFoundError:
            pass
        for index in range(self.backups - 1, 0, -1):
            source = self.path.with_suffix(self.path.suffix + f".{index}")
            target = self.path.with_suffix(self.path.suffix + f".{index + 1}")
            if source.exists():
                os.replace(source, target)
        if self.path.exists():
            os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))

    def _paths_newest_first(self) -> list[Path]:
        return [path for path in self._all_paths() if path.exists()]

    def _all_paths(self) -> list[Path]:
        return [self.path] + [
            self.path.with_suffix(self.path.suffix + f".{index}")
            for index in range(1, self.backups + 1)
        ]

    @staticmethod
    def _read_lines(path: Path) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            result.append(value)
                    except ValueError:
                        continue
        except FileNotFoundError:
            pass
        return result

    @staticmethod
    def _summary(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "id", "created_at", "source", "phase", "person_id",
                "session_id", "turn_id", "status",
            )
        }
