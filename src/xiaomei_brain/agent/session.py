"""Session management: SessionManager (persist) + AgentSession (runtime)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session file persistence (save/load/list/delete).

    Saves conversation state to JSON files in ~/.xiaomei-brain/sessions/
    """

    def __init__(self, session_dir: str | None = None) -> None:
        self.session_dir = session_dir or os.path.expanduser("~/.xiaomei-brain/sessions")
        os.makedirs(self.session_dir, exist_ok=True)
        self._current_session_id: str | None = None
        logger.info("SessionManager initialized, dir=%s", self.session_dir)

    def save(
        self,
        session_id: str | None = None,
        messages: list | None = None,
        context_summary: str = "",
        working_memory_items: dict | None = None,
    ) -> str:
        """Save session state to disk."""
        if not session_id:
            session_id = self._current_session_id or f"session-{int(time.time())}"

        self._current_session_id = session_id

        state = {
            "id": session_id,
            "timestamp": time.time(),
            "messages": messages or [],
            "context_summary": context_summary,
            "working_memory": working_memory_items or {},
        }

        filepath = os.path.join(self.session_dir, f"{session_id}.json")
        with open(filepath, "w", encoding="utf-8", errors="surrogatepass") as f:
            json_str = json.dumps(state, ensure_ascii=False, indent=2)
            json_str = json_str.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
            f.write(json_str)

        logger.info("Saved session: %s (%d messages)", session_id, len(messages or []))
        return session_id

    def load(self, session_id: str) -> dict | None:
        """Load session state from disk."""
        filepath = os.path.join(self.session_dir, f"{session_id}.json")
        if not os.path.exists(filepath):
            logger.warning("Session not found: %s", session_id)
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            state = json.load(f)

        self._current_session_id = session_id
        logger.info("Loaded session: %s (%d messages)", session_id, len(state.get("messages", [])))
        return state

    def list_sessions(self) -> list[dict]:
        """List all saved sessions, most recent first."""
        sessions = []
        if not os.path.exists(self.session_dir):
            return sessions

        for fname in os.listdir(self.session_dir):
            if not fname.endswith(".json"):
                continue
            filepath = os.path.join(self.session_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    state = json.load(f)
                sessions.append({
                    "id": state.get("id", fname[:-5]),
                    "timestamp": state.get("timestamp", 0),
                    "message_count": len(state.get("messages", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        sessions.sort(key=lambda s: s["timestamp"], reverse=True)
        return sessions

    def latest_session_id(self) -> str | None:
        """Get the ID of the most recent session."""
        sessions = self.list_sessions()
        return sessions[0]["id"] if sessions else None

    def delete(self, session_id: str) -> bool:
        """Delete a session file."""
        filepath = os.path.join(self.session_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info("Deleted session: %s", session_id)
            return True
        return False


@dataclass
class AgentSession:
    """Runtime session state for an active conversation.

    Holds Agent instance, message history, and session persistence.
    Used by WebSocket handlers, channels, and other runtime contexts.
    """
    id: str
    agent: Any  # Agent instance
    session_manager: SessionManager
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the session history."""
        self.messages.append({"role": role, "content": content, "timestamp": time.time()})

    def save(self) -> str:
        """Persist session state to disk."""
        wm_items = {}
        if hasattr(self.agent, "working_memory") and self.agent.working_memory:
            wm_items = {
                k: {"value": v.value, "importance": v.importance, "source_turn": v.source_turn}
                for k, v in self.agent.working_memory.all_items().items()
            }
        return self.agent.save_session(
            self.session_manager,
            self.id,
            messages=self.messages,
            context_summary="",
            working_memory_items=wm_items,
        )

    def get_messages(self) -> list[dict[str, Any]]:
        """Get copy of current session messages."""
        return list(self.messages)

    def restore(self, session_id: str) -> bool:
        """Load session state from disk. Returns True if resumed."""
        return self.agent.load_session(self.session_manager, session_id)