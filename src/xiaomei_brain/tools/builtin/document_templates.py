"""One conversational management tool for Agent-owned document templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.documents.templates import DocumentTemplateService
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


def _attachment(attachment_id: str, attachments: tuple[dict[str, Any], ...]) -> Path:
    match = next(
        (item for item in attachments if str(item.get("id")) == attachment_id),
        None,
    )
    if match is None or match.get("kind") != "document":
        raise ValueError("当前执行现场中没有这个文档附件")
    path = Path(str(match.get("local_path") or ""))
    if not path.is_file():
        raise ValueError("模板附件文件不可用")
    return path


def create_manage_document_template_tool(service: DocumentTemplateService) -> Tool:
    def manage_document_template(
        action: str,
        template: str = "",
        attachment_id: str = "",
        name: str = "",
        description: str = "",
        keywords: list[str] | None = None,
        scope_type: str = "",
        confirmed: bool = False,
    ) -> dict[str, Any]:
        context = current_tool_execution()
        if context is None:
            return {"error": "manage_document_template 只能在 Agent 工具调用期间使用"}
        person_id = context.person_id
        operation = str(action).strip().lower()
        try:
            if operation == "list":
                records = service.list(person_id)
                return {
                    "success": True,
                    "action": "list",
                    "count": len(records),
                    "templates": [record.public() for record in records],
                }

            if operation == "register":
                if not attachment_id:
                    raise ValueError("register 需要当前消息中的 attachment_id")
                if not name:
                    raise ValueError("register 需要明确的模板名称")
                record = service.register(
                    _attachment(attachment_id, context.attachments),
                    name=name,
                    person_id=person_id,
                    description=description,
                    keywords=keywords,
                    scope_type=scope_type or "person",
                )
                preview = service.copy_preview_to(
                    record,
                    context.output_root or context.workspace_root,
                    context.session_id,
                )
                return {
                    "success": True,
                    "action": "register",
                    "template": record.public(include_manifest=True),
                    "preview_output_path": str(preview) if preview else "",
                    "next_action": (
                        "如有 preview_output_path，调用 present_artifacts 展示预览；"
                        "告诉用户以后可直接按模板名称使用"
                    ),
                }

            if operation == "inspect":
                if not template:
                    raise ValueError("inspect 需要模板名称或 template_id")
                record = service.resolve(template, person_id)
                preview = service.copy_preview_to(
                    record,
                    context.output_root or context.workspace_root,
                    context.session_id,
                )
                return {
                    "success": True,
                    "action": "inspect",
                    "template": record.public(include_manifest=True),
                    "preview_output_path": str(preview) if preview else "",
                    "next_action": "如有 preview_output_path，调用 present_artifacts 展示预览",
                }

            if operation == "update":
                if not template:
                    raise ValueError("update 需要模板名称或 template_id")
                source_path = (
                    _attachment(attachment_id, context.attachments)
                    if attachment_id else None
                )
                record = service.update(
                    template,
                    person_id,
                    source_path=source_path,
                    name=name,
                    description=description if description else None,
                    keywords=keywords,
                    scope_type=scope_type,
                )
                preview = service.copy_preview_to(
                    record,
                    context.output_root or context.workspace_root,
                    context.session_id,
                )
                return {
                    "success": True,
                    "action": "update",
                    "template": record.public(include_manifest=True),
                    "preview_output_path": str(preview) if preview else "",
                }

            if operation == "remove":
                if not template:
                    raise ValueError("remove 需要模板名称或 template_id")
                if confirmed is not True:
                    raise ValueError("删除模板前必须向当前 Person 明确确认，并传入 confirmed=true")
                record = service.remove(template, person_id)
                return {
                    "success": True,
                    "action": "remove",
                    "removed": record.public(),
                }

            raise ValueError("action 只支持 register、list、inspect、update 或 remove")
        except Exception as exc:
            return {"error": str(exc), "action": operation}

    return Tool(
        name="manage_document_template",
        description=(
            "Manage reusable document templates owned by this Agent through conversation. "
            "Register a DOCX attachment, list visible templates, inspect one with its real "
            "preview, update metadata or replace its source, or remove it after explicit "
            "person confirmation. New templates default to the current Person; use scope_type "
            "global only when the person explicitly says everyone or the company may use it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["register", "list", "inspect", "update", "remove"],
                },
                "template": {"type": "string", "description": "Template name or template_id"},
                "attachment_id": {"type": "string", "description": "Current DOCX attachment for register/update"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "scope_type": {"type": "string", "enum": ["person", "global"]},
                "confirmed": {"type": "boolean", "description": "Only true after explicit person confirmation when removing"},
            },
            "required": ["action"],
        },
        func=manage_document_template,
        category="document",
    )
