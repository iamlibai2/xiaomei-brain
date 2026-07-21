"""Authoritative snapshots for conversation turns that are still running."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any


class ActiveTurnRegistry:
    """Track resumable UI state for active turns, grouped by session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, dict[str, Any]] = {}

    def start(self, session_id: str, turn_id: str) -> None:
        if not session_id or not turn_id:
            return
        with self._lock:
            self._turns[session_id] = {
                "session_id": session_id,
                "turn_id": turn_id,
                "status": "running",
                "started_at": int(time.time() * 1000),
                "items": [],
            }

    def append_text(self, session_id: str, turn_id: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            turn = self._matching_turn(session_id, turn_id)
            if turn is None:
                return
            items = turn["items"]
            if items and items[-1].get("type") == "message":
                items[-1]["text"] += text
            else:
                items.append({"type": "message", "text": text})

    def tool_event(
        self,
        event: str,
        payload: dict[str, Any],
        session_id: str,
        turn_id: str,
    ) -> None:
        tool_call_id = str(payload.get("tool_call_id", ""))
        if not tool_call_id:
            return
        with self._lock:
            turn = self._matching_turn(session_id, turn_id)
            if turn is None:
                return
            items = turn["items"]
            existing = next(
                (item for item in items if item.get("type") == "tool" and item.get("id") == tool_call_id),
                None,
            )
            if event == "tool.start":
                if existing is None:
                    items.append({
                        "type": "tool",
                        "id": tool_call_id,
                        "name": str(payload.get("name", "")),
                        "arguments": copy.deepcopy(payload.get("arguments", {})),
                        "status": "running",
                        "summary": "",
                        "truncated": False,
                        "error": "",
                    })
                return
            if existing is None:
                existing = {
                    "type": "tool",
                    "id": tool_call_id,
                    "name": str(payload.get("name", "")),
                    "arguments": {},
                }
                items.append(existing)
            error = payload.get("error")
            existing.update({
                "status": "error" if error else "complete",
                "summary": str(payload.get("summary", "")),
                "truncated": bool(payload.get("truncated", False)),
                "error": str(error.get("message", "")) if isinstance(error, dict) else "",
            })

    def interaction_event(self, event: str, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("session_id", ""))
        turn_id = str(payload.get("turn_id", ""))
        interaction_id = str(payload.get("id", ""))
        if not interaction_id:
            return
        with self._lock:
            turn = self._matching_turn(session_id, turn_id)
            if turn is None:
                return
            items = turn["items"]
            existing = next(
                (
                    item for item in items
                    if item.get("type") == "interaction" and item.get("id") == interaction_id
                ),
                None,
            )
            data = {
                "type": "interaction",
                "id": interaction_id,
                "question": str(payload.get("question", "")),
                "choices": list(payload.get("choices", [])),
                "status": str(payload.get("status", "pending")),
                "response": str(payload.get("response", "")),
            }
            if existing is None:
                items.append(data)
            else:
                existing.update(data)
            turn["status"] = "waiting_user" if event == "interaction.requested" else "running"

    def complete(self, session_id: str, turn_id: str) -> None:
        with self._lock:
            if self._matching_turn(session_id, turn_id) is not None:
                self._turns.pop(session_id, None)

    def snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            turn = self._turns.get(session_id)
            return copy.deepcopy(turn) if turn is not None else None

    def _matching_turn(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        turn = self._turns.get(session_id)
        if turn is None or turn.get("turn_id") != turn_id:
            return None
        return turn
