"""Compact Project context rendered for one verified conversation Person."""

from __future__ import annotations

from html import escape
from typing import Any

from .models import ProjectActor, ProjectActorType
from .service import ProjectService


def render_project_context(agent: Any, *, limit: int = 6) -> str:
    """Render only the Project explicitly bound to the current run.

    ConversationDriver restores ``active_project_id`` from the verified
    session binding at the start of every turn. Listing every active Project
    here would make unrelated long-running work permanent prompt baggage.
    """
    service = getattr(agent, "project_service", None)
    person_id = str(getattr(agent, "user_id", "")).strip()
    if (
        not isinstance(service, ProjectService)
        or not person_id
        or person_id in {"global", "system"}
    ):
        return ""
    actor = ProjectActor(ProjectActorType.PERSON, person_id)
    active_id = str(getattr(agent, "active_project_id", "")).strip()
    if not active_id:
        return ""
    try:
        current = service.require_project(active_id, actor=actor)
    except (KeyError, PermissionError, ValueError):
        return ""

    lines = [
        "<project_context>",
        "以下是当前人物可访问的长期工作项目事实，不是固定工作流。",
        "项目阶段是 Agent 可调整的认知地图：可以新增、移除、重命名、合并、重排或重新判断。",
        "在方案形成、计划变化、候选交付、用户确认或要求修改后，使用 review_project 根据真实证据复盘；不要让项目记录与实际工作脱节。",
        "复盘必须区分技术检查、模型视觉检查和用户观看确认；没有实际观看证据时，不要声称已经看过或完成视觉验收。",
        "计划结构改变时可移除不再适合的阶段；若需要保留一项未执行的决策记录，可标记 skipped 并说明原因。",
        "收到确认或恢复旧项目时，先核对已有项目资产和交付物；已有结果满足要求时直接复用，不要仅为更新项目状态重复执行昂贵工具。",
    ]
    lines.extend([
        f'<current id="{escape(current.id)}" '
        f'type="{escape(current.project_type)}" '
        f'status="{current.status.value}">',
        f"名称：{escape(current.name[:200])}",
    ])
    if current.summary:
        lines.append(f"说明：{escape(current.summary[:600])}")
    if current.progress_summary:
        lines.append(f"进展：{escape(current.progress_summary[:600])}")
    if current.waiting_reason:
        lines.append(f"等待：{escape(current.waiting_reason[:300])}")
    last_review = current.metadata.get("last_review")
    if isinstance(last_review, dict):
        assessment = str(last_review.get("assessment") or "").strip()
        next_action = str(last_review.get("next_action") or "").strip()
        if assessment:
            lines.append(f"最近复盘：{escape(assessment[:500])}")
        if next_action:
            lines.append(f"复盘后的下一步：{escape(next_action[:300])}")
        for label, key in (("计划调整", "plan_changes"), ("已知偏差", "deviations")):
            values = last_review.get(key)
            if isinstance(values, list):
                normalized = [
                    str(item).strip() for item in values if str(item).strip()
                ]
                if normalized:
                    lines.append(
                        f"{label}：{escape('；'.join(normalized)[:500])}",
                    )
    steps = service.store.list_steps(current.id)
    if steps:
        lines.append("阶段：")
        for step in steps[:12]:
            units = ""
            if step.total_units is not None:
                units = f" {step.completed_units or 0}/{step.total_units}"
            lines.append(
                f'- id="{escape(step.step_id)}" status="{step.status.value}"> '
                f"{escape(step.title[:160])}{units}",
            )
    assets = [
        asset for asset in service.store.list_assets(current.id)
        if asset.status.value == "available" and asset.role.value != "cache"
    ]
    if assets:
        lines.append("已有资产：")
        for asset in assets[:8]:
            facts = ""
            if asset.role.value == "deliverable":
                actual_duration = asset.metadata.get("actual_duration")
                has_audio = asset.metadata.get("has_audio")
                details = []
                if isinstance(actual_duration, (int, float)):
                    details.append(f"实际时长 {actual_duration:g} 秒")
                if isinstance(has_audio, bool):
                    details.append("有音轨" if has_audio else "无音轨")
                if details:
                    facts = f"（{'，'.join(details)}）"
            lines.append(
                f'- id="{escape(asset.id)}" role="{asset.role.value}" '
                f'kind="{escape(asset.kind)}"> {escape(asset.name[:180])}'
                f"{facts}",
            )
    lines.append("</current>")
    lines.append(
        "工具负责记录文件、时长等事实；Agent 负责解释事实、调整计划并保持项目状态诚实。具体执行仍使用委托和普通工具。",
    )
    lines.append("</project_context>")
    return "\n".join(lines)
