"""Deterministic first-version retention policies."""

from __future__ import annotations


RETENTION_SECONDS = {
    "temporary_plan": 3 * 24 * 60 * 60,
    "unfinished": 7 * 24 * 60 * 60,
    "event": 3 * 24 * 60 * 60,
    "preference_signal": 7 * 24 * 60 * 60,
    "relationship_signal": 7 * 24 * 60 * 60,
    "emotion_event": 14 * 24 * 60 * 60,
}


def retention_seconds(kind: str, importance: float, emotion_intensity: float) -> float:
    base = float(RETENTION_SECONDS.get(kind, RETENTION_SECONDS["event"]))
    if importance >= 0.8 or emotion_intensity >= 0.8:
        return max(base, 30 * 24 * 60 * 60)
    if importance >= 0.65 or emotion_intensity >= 0.6:
        return max(base, 7 * 24 * 60 * 60)
    return base
