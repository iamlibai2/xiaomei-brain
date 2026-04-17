"""Session persistence: save and restore conversation state."""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session save/restore for conversation continuity.

    Saves:
    - Conversation messages
    - Context manager summary
    - Working memory items
    - Timestamp

    File format: JSON in ~/.xiaomei-brain/sessions/
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
        """Save session state to disk.

        Args:
            session_id: Session identifier. Auto-generated if not provided.
            messages: Conversation messages list.
            context_summary: Compressed summary from ContextManager.
            working_memory_items: Working memory items dict.

        Returns:
            The session ID.
        """
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
            # Clean surrogate characters before serializing
            json_str = json.dumps(state, ensure_ascii=False, indent=2)
            # Remove surrogate characters that JSON can't encode
            json_str = json_str.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
            f.write(json_str)

        logger.info("Saved session: %s (%d messages)", session_id, len(messages or []))
        return session_id

    def load(self, session_id: str) -> dict | None:
        """Load session state from disk.

        Args:
            session_id: Session identifier.

        Returns:
            Session state dict or None if not found.
        """
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
