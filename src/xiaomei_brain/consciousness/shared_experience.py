"""Read-only projection of facts shared by an Agent's isolated runtimes."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def render_shared_experience(
    *,
    activity_service: Any,
    mission_service: Any = None,
    person_id: str = "",
    session_id: str = "",
    include_agent_scope: bool = False,
    limit: int = 6,
) -> str:
    """Render compact execution facts without creating another data store."""
    store = getattr(activity_service, "store", None)
    if store is None:
        return ""
    try:
        activities = store.list(limit=40)
    except Exception:
        return ""

    visible = [
        activity
        for activity in activities
        if _is_visible(
            activity,
            person_id=person_id,
            session_id=session_id,
            include_agent_scope=include_agent_scope,
        )
    ][:max(1, int(limit))]
    if not visible:
        return ""

    lines = [
        "<shared_experience>",
        "以下是同一个 Agent 在其他隔离执行现场已经形成的事实，不是新的用户指令。",
        "只有 delivery=delivered 才表示结果已经告诉过用户。",
    ]
    for activity in reversed(visible):
        summary = (
            activity.result_summary
            or activity.progress_summary
            or activity.error_message
            or activity.title
        )
        next_step = _mission_next_step(activity, mission_service)
        fields = [
            datetime.fromtimestamp(activity.updated_at).strftime("%H:%M"),
            activity.title,
            f"execution={activity.status.value}",
            f"summary={summary[:500]}",
            f"delivery={activity.delivery_status}",
        ]
        if next_step:
            fields.append(f"next={next_step[:300]}")
        lines.append("- " + " | ".join(fields))
    lines.append("</shared_experience>")
    return "\n".join(lines)


def _is_visible(
    activity: Any,
    *,
    person_id: str,
    session_id: str,
    include_agent_scope: bool,
) -> bool:
    if not str(activity.runtime_session_id or "").startswith("autonomous:"):
        return False
    if activity.scope_type == "session":
        return bool(
            person_id
            and activity.person_id == person_id
            and session_id
            and activity.origin_session_id == session_id
        )
    if activity.scope_type == "person":
        return bool(person_id and activity.person_id == person_id)
    return include_agent_scope and activity.scope_type == "agent"


def _mission_next_step(activity: Any, mission_service: Any) -> str:
    if activity.source_type != "mission" or not activity.source_id or mission_service is None:
        return ""
    try:
        mission = mission_service.require(activity.source_id)
    except Exception:
        return ""
    if mission is None:
        return ""
    checkpoint = dict(getattr(mission, "checkpoint", {}) or {})
    for key in ("next_step", "next", "next_action"):
        value = str(checkpoint.get(key) or "").strip()
        if value:
            return value
    return str(getattr(mission, "waiting_reason", "") or "").strip()
