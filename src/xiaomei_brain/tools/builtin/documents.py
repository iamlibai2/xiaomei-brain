"""Single Agent-facing tool for all registered document formats."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.documents import DocumentService
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


def create_read_document_tool(plugin_registry: Any, db_path_provider: Any) -> Tool:
    def read_document(
        attachment_id: str,
        section: str = "",
        offset: int = 0,
        limit: int = 12000,
    ) -> dict[str, Any]:
        """Read one attachment owned by the current turn, optionally by section."""
        context = current_tool_execution()
        if context is None:
            return {"error": "read_document is only available during an Agent tool call"}
        attachment = next(
            (item for item in context.attachments if str(item.get("id")) == attachment_id),
            None,
        )
        if attachment is None or attachment.get("kind") != "document":
            return {"error": "Attachment is not available in the current execution context"}
        source = db_path_provider()
        db_path = getattr(source, "db_path", None) if source is not None else None
        try:
            return DocumentService(plugin_registry, db_path).read(
                attachment,
                session_id=context.session_id,
                section=section,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            return {"error": str(exc), "attachment_id": attachment_id}

    return Tool(
        name="read_document",
        description=(
            "Read a Word, PDF, spreadsheet or presentation attachment from the current turn. "
            "Pass its attachment_id; do not pass a filesystem path. The first call returns a "
            "bounded preview and section list. Use section and next_offset for large documents."
        ),
        parameters={
            "type": "object",
            "properties": {
                "attachment_id": {"type": "string", "description": "ID shown in the attached_document block"},
                "section": {"type": "string", "description": "Optional section key returned by an earlier call"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20000},
            },
            "required": ["attachment_id"],
        },
        func=read_document,
        category="document",
    )
