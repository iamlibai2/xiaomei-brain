"""Domain models used by the memory formation service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    operation: str = "ADD"
    tag: str = "event"
    retention: str = "short_term"
    scope_type: str = "person"
    scope_id: str = "global"
    confidence: float = 0.7
    importance: float = 0.5
    emotion_intensity: float = 0.0
    scenes: tuple[str, ...] = ()
    structured_value: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[tuple[str, str], ...] = ()
    event_time: float | None = None
    event_time_end: float | None = None


@dataclass(frozen=True)
class FormationResult:
    layer: str
    memory_id: int
    operation: str
    content: str
    scope_type: str
    scope_id: str
