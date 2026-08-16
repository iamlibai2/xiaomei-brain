"""Live, read-only projection of one Agent's observable inner activity."""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from xiaomei_brain.activity import ActivityStatus

from ..protocol import ErrorCode, build_error, build_response

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (
    ActivityStatus.QUEUED,
    ActivityStatus.RUNNING,
    ActivityStatus.PAUSED,
)
_RELEVANT_EVENT_PREFIXES = (
    "activity.",
    "agent.state.",
    "memory.",
    "assignment.",
    "project.",
)


@dataclass
class _Watcher:
    person_id: str
    snapshot: dict[str, Any]
    comparable: dict[str, Any]
    revision: int


class BrainMethods:
    """Expose a live projection only while at least one Desktop is watching."""

    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts
        self._lock = threading.RLock()
        self._watchers: dict[str, _Watcher] = {}
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        event_hub = getattr(living, "_event_hub", None)
        self._unsubscribe = (
            event_hub.subscribe(self._on_domain_event)
            if event_hub is not None and hasattr(event_hub, "subscribe")
            else None
        )

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "brain.get": self.handle_get,
            "brain.watch": self.handle_watch,
            "brain.unwatch": self.handle_unwatch,
        }

    def handle_get(self, conn_id: str, req_id: str, _params: dict) -> dict:
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        return build_response(
            req_id,
            result={"brain": self._build_snapshot(person_id, revision=0)},
        )

    def handle_watch(self, conn_id: str, req_id: str, _params: dict) -> dict:
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        snapshot = self._build_snapshot(person_id, revision=1)
        with self._lock:
            self._watchers[conn_id] = _Watcher(
                person_id=person_id,
                snapshot=copy.deepcopy(snapshot),
                comparable=self._comparable(snapshot),
                revision=1,
            )
            self._ensure_thread()
        self._wake.set()
        return build_response(req_id, result={"brain": snapshot, "watching": True})

    def handle_unwatch(self, conn_id: str, req_id: str, _params: dict) -> dict:
        self.drop_connection(conn_id)
        return build_response(req_id, result={"watching": False})

    def drop_connection(self, conn_id: str) -> None:
        with self._lock:
            self._watchers.pop(conn_id, None)

    def _person_id(
        self,
        conn_id: str,
        req_id: str,
    ) -> tuple[str, dict | None]:
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return "", build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        return str(context.person_id), None

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="brain-observer",
            daemon=True,
        )
        self._thread.start()

    def _on_domain_event(self, event: Any) -> None:
        if not str(getattr(event, "name", "")).startswith(_RELEVANT_EVENT_PREFIXES):
            return
        with self._lock:
            if self._watchers:
                self._wake.set()

    def _watch_loop(self) -> None:
        """Sample at most once a second and do no work without watchers."""
        while True:
            with self._lock:
                has_watchers = bool(self._watchers)
            # Once the last page closes, sleep without a timer.  A later
            # brain.watch call wakes the observer and starts sampling again.
            self._wake.wait(timeout=1.0 if has_watchers else None)
            self._wake.clear()
            with self._lock:
                watchers = tuple(self._watchers.items())
            if not watchers:
                continue
            for conn_id, watcher in watchers:
                try:
                    next_revision = watcher.revision + 1
                    snapshot = self._build_snapshot(
                        watcher.person_id,
                        revision=next_revision,
                    )
                    comparable = self._comparable(snapshot)
                    changed = self._changed_sections(watcher.comparable, comparable)
                    if not changed:
                        continue
                    with self._lock:
                        current = self._watchers.get(conn_id)
                        if current is not watcher:
                            continue
                        current.snapshot = copy.deepcopy(snapshot)
                        current.comparable = comparable
                        current.revision = next_revision
                    self._publish(conn_id, next_revision, changed)
                except Exception:
                    logger.exception("[Brain] Failed to update watcher %s", conn_id[:8])

    def _publish(self, conn_id: str, revision: int, changed: dict[str, Any]) -> None:
        router = getattr(self._living, "_router", None)
        adapter = router.get_adapter("ws") if router is not None else None
        sender = getattr(adapter, "send_connection_event", None)
        if sender is None:
            return
        sender(
            conn_id,
            "brain.changed",
            {
                "revision": revision,
                "observed_at": time.time(),
                "changed": changed,
            },
        )

    def _build_snapshot(self, person_id: str, *, revision: int) -> dict[str, Any]:
        state_getter = getattr(self._living, "get_state_snapshot", None)
        state = dict(state_getter()) if state_getter is not None else {}
        body = state.pop("internal", None)
        relation_getter = getattr(self._living, "get_relationship_projection", None)
        relationship = (
            relation_getter(person_id)
            if relation_getter is not None and person_id
            else None
        )
        activities = self._activities(person_id)
        pending_intents = self._pending_intents(person_id)
        return {
            "revision": revision,
            "observed_at": time.time(),
            "living": state,
            "body": body,
            "relationship": relationship,
            "current_activity": self._current_activity(activities),
            "active_activities": [
                item for item in activities if item.get("status") in {"queued", "running", "paused"}
            ][:12],
            "pending_intents": pending_intents,
            "recent_activities": activities[:40],
        }

    def _activities(self, person_id: str) -> list[dict[str, Any]]:
        service = getattr(self._living, "_activity_service", None)
        if service is None:
            return []
        values = service.store.list(limit=120)
        return [
            service.snapshot(item)
            for item in values
            if self._activity_visible(item, person_id)
        ]

    def _pending_intents(self, person_id: str) -> list[dict[str, Any]]:
        consciousness = getattr(self._living, "consciousness", None)
        self_image = (
            consciousness.get_self_image()
            if consciousness is not None and hasattr(consciousness, "get_self_image")
            else None
        )
        intent_state = getattr(self_image, "intent", None)
        values = list(getattr(intent_state, "intent_buffer", None) or [])
        visible = []
        for value in values:
            scope_type = str(value.get("scope_type") or "agent")
            owner = str(value.get("user_id") or "")
            if scope_type != "agent" and owner and owner != person_id:
                continue
            visible.append({
                "id": str(value.get("intent_id") or value.get("id") or ""),
                "type": str(value.get("type") or ""),
                "content": str(value.get("content") or ""),
                "priority": int(value.get("priority") or 0),
                "source": str(value.get("source") or ""),
                "scope_type": scope_type,
                "person_id": owner,
                "session_id": str(value.get("session_id") or ""),
                "trigger_time": float(value.get("trigger_time") or 0),
                "created_at": float(value.get("created_at") or value.get("trigger_time") or 0),
                "status": "pending",
            })
        visible.sort(
            key=lambda item: (item["priority"], item["created_at"]),
            reverse=True,
        )
        return visible[:30]

    @staticmethod
    def _current_activity(activities: list[dict[str, Any]]) -> dict[str, Any] | None:
        rank = {"running": 0, "paused": 1, "queued": 2}
        active = [item for item in activities if item.get("status") in rank]
        if not active:
            return None
        return min(
            active,
            key=lambda item: (
                rank[str(item.get("status"))],
                -float(item.get("updated_at") or 0),
            ),
        )

    @staticmethod
    def _activity_visible(activity: Any, person_id: str) -> bool:
        return (
            activity.scope_type == "agent"
            or activity.scope_id == "global"
            or activity.person_id == person_id
            or (activity.scope_type == "person" and activity.scope_id == person_id)
        )

    @staticmethod
    def _comparable(snapshot: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(snapshot)
        value.pop("revision", None)
        value.pop("observed_at", None)
        body = value.get("body")
        if isinstance(body, dict):
            body.pop("observed_at", None)
        return value

    @staticmethod
    def _changed_sections(
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: copy.deepcopy(value)
            for key, value in current.items()
            if previous.get(key) != value
        }
