"""Structured messages used to steer an active Agent turn safely."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SteerMessage:
    """One persisted human message eligible to amend an active ReAct turn.

    Identity and lifecycle fields are intentionally kept with the text.  A
    steer is still a real human message; it must never become an anonymous
    string that can cross Person, session, or Turn boundaries.
    """

    content: str
    user_id: str
    session_id: str
    turn_id: str
    message_id: int | None = None
    observation_id: str = ""
    source: str = ""
    context_key: str = ""
    user_display_name: str = ""
    active_turn_id: str = ""
