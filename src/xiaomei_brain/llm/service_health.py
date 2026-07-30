"""Agent-local health state for the currently selected model service."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .public_error import model_service_error


class ModelServiceHealth:
    """A small circuit breaker shared by one Agent's LLM execution paths."""

    _BACKOFF_SECONDS = (60.0, 300.0, 900.0)

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._available = True
        self._status_code = 0
        self._failure_count = 0
        self._unavailable_since = 0.0
        self._last_checked_at = 0.0
        self._next_probe_at = 0.0
        self._probing = False

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available

    def report_failure(self, status_code: int) -> dict[str, str]:
        now = self._clock()
        with self._lock:
            if self._available:
                self._unavailable_since = now
                self._failure_count = 0
            self._available = False
            self._status_code = int(status_code or 0)
            self._failure_count += 1
            delay = self._BACKOFF_SECONDS[
                min(self._failure_count - 1, len(self._BACKOFF_SECONDS) - 1)
            ]
            self._last_checked_at = now
            self._next_probe_at = now + delay
            self._probing = False
            return model_service_error(self._status_code)

    def mark_available(self) -> bool:
        """Mark healthy and return whether this is a recovery transition."""
        with self._lock:
            recovered = not self._available
            self._available = True
            self._status_code = 0
            self._failure_count = 0
            self._unavailable_since = 0.0
            self._last_checked_at = self._clock()
            self._next_probe_at = 0.0
            self._probing = False
            return recovered

    def begin_probe(self, *, force: bool = False) -> bool:
        now = self._clock()
        with self._lock:
            if self._available or self._probing:
                return False
            if not force and now < self._next_probe_at:
                return False
            self._probing = True
            return True

    def finish_probe_failure(self, status_code: int | None = None) -> None:
        with self._lock:
            fallback_status = self._status_code
        self.report_failure(
            int(status_code if status_code is not None else fallback_status),
        )

    def error(self) -> dict[str, str] | None:
        with self._lock:
            if self._available:
                return None
            return model_service_error(self._status_code)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            error = None if self._available else model_service_error(self._status_code)
            return {
                "available": self._available,
                "status_code": self._status_code,
                "error": error,
                "failure_count": self._failure_count,
                "unavailable_since": self._unavailable_since,
                "last_checked_at": self._last_checked_at,
                "next_probe_at": self._next_probe_at,
            }
