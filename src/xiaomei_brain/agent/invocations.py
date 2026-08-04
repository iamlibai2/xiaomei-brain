"""Resolve explicit work choices selected by a human conversation client."""

from __future__ import annotations

from typing import Any


EXECUTION_MODES = (
    {
        "id": "assignment",
        "name": "委托执行",
        "description": "交给后台执行现场持续完成，不阻塞当前对话。",
    },
    {
        "id": "project",
        "name": "项目方式",
        "description": "建立持续工作空间，累积进度、资产和交付结果。",
    },
)


def process_matches_capability(template: Any, capability_id: str) -> bool:
    """Match explicit ownership first, with a legacy project-type fallback."""
    normalized = str(capability_id or "").strip().lower()
    if not normalized:
        return False
    explicit = {
        str(item).strip().lower()
        for item in getattr(template, "capability_ids", ())
        if str(item).strip()
    }
    if explicit:
        return normalized in explicit
    aliases = {
        str(item).strip().lower().replace(".", "_").replace("-", "_")
        for item in getattr(template, "project_types", ())
        if str(item).strip()
    }
    return normalized.replace("-", "_") in aliases


def validate_invocation(instance: Any, value: dict[str, Any]) -> dict[str, str]:
    """Validate client-selected IDs against this Agent's live registries."""
    kind = str(value.get("kind") or "").strip()
    selected_id = str(value.get("id") or "").strip()
    process_template_id = str(value.get("process_template_id") or "").strip()
    if kind == "capability":
        capability = instance.get_capability(selected_id)
        if capability is None or not capability.get("enabled"):
            raise ValueError("所选能力不存在或已关闭")
        if capability.get("status") not in {"ready", "degraded"}:
            raise ValueError("所选能力尚未就绪")
        if process_template_id:
            registry = getattr(instance, "_process_template_registry", None)
            if registry is None:
                raise ValueError("当前 Agent 没有可用的交付标准")
            template = registry.require(process_template_id)
            if not process_matches_capability(template, selected_id):
                raise ValueError("所选交付标准不属于该能力")
    elif kind == "skill":
        loader = getattr(instance, "_skill_loader", None)
        if loader is None or loader.view_skill(selected_id) is None:
            raise ValueError("所选工作方法不存在或已停用")
        if process_template_id:
            raise ValueError("Skill 不能直接指定交付标准")
    elif kind == "execution":
        if selected_id not in {item["id"] for item in EXECUTION_MODES}:
            raise ValueError("未知的执行方式")
        if process_template_id:
            raise ValueError("执行方式不能直接指定交付标准")
    else:
        raise ValueError("未知的调用类型")
    return {
        "kind": kind,
        "id": selected_id,
        "process_template_id": process_template_id,
    }


def render_invocation_context(instance: Any, value: dict[str, Any] | None) -> str:
    """Render a trusted, explicit constraint for one selected work method."""
    if not value:
        return ""
    invocation = validate_invocation(instance, value)
    kind = invocation["kind"]
    selected_id = invocation["id"]
    lines = [
        "<用户明确选择的工作方式>",
        "这是用户在当前消息中的明确选择，优先级高于自动匹配，不要替换为其他能力或工作方法。",
    ]
    if kind == "skill":
        skill = instance._skill_loader.view_skill(selected_id)
        lines.extend([
            f"- 工作方法：{skill.get('name', selected_id)}",
            f"- 说明：{skill.get('description', '')}",
            "- 必须遵循下列完整 Skill 指引：",
            str(skill.get("content") or ""),
        ])
    elif kind == "capability":
        capability = instance.get_capability(selected_id) or {}
        lines.extend([
            f"- 能力：{capability.get('name', selected_id)}",
            f"- 说明：{capability.get('summary', '')}",
            f"- 当前状态：{capability.get('status', '')}",
        ])
        template_id = invocation["process_template_id"]
        if template_id:
            template = instance._process_template_registry.require(template_id)
            lines.extend([
                f"- 交付标准：{template.name} (template_id={template.id})",
                f"- 标准说明：{template.description}",
                "- 如果尚未建立 Project，先建立与任务匹配的 Project；然后必须调用 "
                f"apply_project_process_template，使用精确 template_id={template.id}。",
                "- 不得自行缩减、改名或替换该交付标准。",
            ])
    else:
        if selected_id == "assignment":
            lines.extend([
                "- 执行方式：委托执行",
                "- 必须使用 delegate 建立后台委托，不要在当前对话中假装已完成。",
            ])
        else:
            lines.extend([
                "- 执行方式：项目方式",
                "- 必须建立或继续一个 Project，将进度、资产和交付结果归入该 Project。",
            ])
    lines.append("</用户明确选择的工作方式>")
    return "\n".join(lines)

