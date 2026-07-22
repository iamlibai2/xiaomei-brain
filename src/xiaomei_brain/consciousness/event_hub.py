"""In-process domain events emitted by one running Agent.

The EventHub is deliberately transport agnostic.  Agent runtime code publishes
facts here; projections decide whether those facts update an active-turn
snapshot, reach a Gateway client, or are persisted.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomainEvent:
    """One immutable event envelope produced inside an Agent process."""

    name: str
    payload: dict[str, Any]
    session_id: str = ""
    turn_id: str = ""
    sequence: int = 0
    timestamp: int = 0


EventListener = Callable[[DomainEvent], None]


class EventHub:
    """Thread-safe synchronous publisher for one Agent's domain events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: list[EventListener] = []
        self._sequence = 0

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Register a projection and return an idempotent unsubscribe callback."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def publish(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> DomainEvent:
        """Publish an event to every projection without coupling producers to it."""
        body = copy.deepcopy(payload or {})
        resolved_session_id = session_id or str(body.get("session_id", ""))
        resolved_turn_id = turn_id or str(body.get("turn_id", ""))
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            listeners = tuple(self._listeners)

        event = DomainEvent(
            name=name,
            payload=body,
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            sequence=sequence,
            timestamp=int(time.time() * 1000),
        )
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # One broken projection must not stop the Agent or hide events
                # from the remaining projections.
                logger.exception("Domain event projection failed: %s", name)
        return event

