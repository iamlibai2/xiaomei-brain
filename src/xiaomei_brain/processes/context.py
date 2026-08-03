"""Compact Process constraints injected beside, not inside, the Project plan."""

from __future__ import annotations

from html import escape
from typing import Any

from xiaomei_brain.projects import ProjectActor, ProjectActorType


def render_process_context(agent: Any) -> str:
    service = getattr(agent, "process_service", None)
    project_id = str(getattr(agent, "active_project_id", "") or "").strip()
    person_id = str(getattr(agent, "user_id", "") or "").strip()
    if service is None or not project_id or not person_id or person_id == "global":
        return ""
    try:
        process = service.require_for_project(
            project_id,
            actor=ProjectActor(ProjectActorType.PERSON, person_id),
        )
        snapshot = service.snapshot(process)
    except (KeyError, PermissionError, ValueError):
        return ""
    lines = [
        f'<process_contract id="{escape(process.id)}" status="{process.status.value}">',
        f"正式交付标准：{escape(process.name)}。它约束必须提交的结果，不规定你如何思考或执行。",
        "你可以自由调整 Project 工作计划；若标准不再符合用户意图，应明确修订 Process，不能假装已经满足。",
    ]
    for stage in snapshot["stages"]:
        required = "必需" if stage["required"] else "可选"
        lines.append(
            f'- id="{escape(stage["id"])}" status="{stage["status"]}" '
            f'kind="{required}">{escape(stage["title"])}',
        )
        requirements = stage.get("requirements") or []
        if requirements:
            labels = [
                str(item.get("label") or item.get("id") or "未命名要求")
                for item in requirements
                if isinstance(item, dict)
            ]
            if labels:
                lines.append("  要求：" + "；".join(escape(item) for item in labels))
        submission = stage.get("submission") or {}
        missing = submission.get("missing") or []
        if missing:
            lines.append("  仍缺少：" + "；".join(escape(str(item)) for item in missing))
    lines.append("</process_contract>")
    return "\n".join(lines)
