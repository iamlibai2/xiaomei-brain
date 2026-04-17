"""Working memory: short-term context that persists within a session."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WorkingMemoryItem:
    """A single item in working memory."""

    key: str          # e.g., "user_mood", "current_topic"
    value: str        # e.g., "心情不好", "讨论做饭"
    source_turn: int  # which conversation turn this was noted
    importance: float = 0.5  # 0.0 ~ 1.0


class WorkingMemory:
    """Short-term memory for the current session.

    Stores key facts and context from the ongoing conversation.
    Cleared on session reset. Not persisted to disk.

    Examples:
        - "user_mood": "seems tired"
        - "current_topic": "cooking"
        - "user_mentioned": "has a cat"
    """

    def __init__(self, max_items: int = 20) -> None:
        self.max_items = max_items
        self._items: dict[str, WorkingMemoryItem] = {}
        self._turn_counter: int = 0
        logger.debug("WorkingMemory initialized, max_items=%d", max_items)

    def update(self, key: str, value: str, importance: float = 0.5) -> None:
        """Add or update a working memory item."""
        self._items[key] = WorkingMemoryItem(
            key=key,
            value=value,
            source_turn=self._turn_counter,
            importance=importance,
        )
        logger.debug("WorkingMemory update: %s = %s (importance=%.2f)", key, value, importance)

        # Evict lowest importance if at capacity
        if len(self._items) > self.max_items:
            least_important = min(self._items, key=lambda k: self._items[k].importance)
            del self._items[least_important]
            logger.debug("Evicted working memory item: %s", least_important)

    def get(self, key: str) -> str | None:
        """Get a working memory value by key."""
        item = self._items.get(key)
        return item.value if item else None

    def advance_turn(self) -> None:
        """Increment the turn counter."""
        self._turn_counter += 1

    def to_context_string(self) -> str:
        """Format working memory for injection into system prompt."""
        if not self._items:
            return ""

        lines = []
        # Sort by importance descending
        sorted_items = sorted(self._items.values(), key=lambda x: x.importance, reverse=True)
        for item in sorted_items:
            lines.append(f"- {item.key}: {item.value}")
        return "\n".join(lines)

    def all_items(self) -> dict[str, WorkingMemoryItem]:
        """Return all working memory items."""
        return dict(self._items)

    def clear(self) -> None:
        """Clear all working memory."""
        self._items.clear()
        self._turn_counter = 0

    def __len__(self) -> int:
        return len(self._items)
