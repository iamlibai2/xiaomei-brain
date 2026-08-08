"""Agent tools for bringing tabular attachments into a Workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import (
    current_tool_execution,
    resolve_current_attachment,
)


def create_import_tools(agent: Any) -> list[Tool]:
    def core() -> Any:
        return agent._get_agent()

    def service():
        value = getattr(agent, "workspace_service", None)
        if value is None:
            value = getattr(core(), "workspace_service", None)
        if value is None:
            raise RuntimeError("Workspace service is not initialized")
        return value

    def import_tabular_data(
        workspace_id: str,
        attachment_id: str = "",
        sheet: str = "",
        collection_id: str = "",
        collection_name: str = "",
        collection_label: str = "",
        key_column: str = "",
    ) -> dict[str, Any]:
        """Import a current-turn CSV, TSV or XLSX attachment as business facts."""
        context = current_tool_execution()
        if context is None:
            return {"error": "import_tabular_data is only available during an Agent tool call"}
        try:
            attachment = resolve_current_attachment(
                attachment_id,
                allowed_suffixes=(".csv", ".tsv", ".xlsx"),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        local_path = Path(str(attachment.get("local_path") or ""))
        if not local_path.is_file():
            return {"error": "Attachment file is not available"}
        try:
            return service().imports.import_path(
                workspace_id,
                local_path,
                source_name=str(attachment.get("name") or local_path.name),
                sheet=sheet,
                collection_id=collection_id,
                collection_name=collection_name,
                collection_label=collection_label,
                key_column=key_column,
                source_person_id=context.person_id,
                asset_id=attachment_id,
                session_id=context.session_id,
                turn_id=context.turn_id,
            )
        except Exception as exc:
            return {"error": str(exc), "attachment_id": attachment_id}

    return [Tool(
        name="import_tabular_data",
        description=(
            "Import a CSV, TSV or XLSX attachment into a persistent Workspace. "
            "The tool records its DataSource and Observation, automatically creates "
            "or evolves a typed Collection, and creates or updates durable business "
            "records. Use this instead of manually copying spreadsheet rows through "
            "upsert_business_record. Reuse collection_id when the file belongs to an "
            "existing business object; otherwise omit it and let the Agent form one."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "workspace_id": {"type": "string"},
                "attachment_id": {
                    "type": "string",
                    "description": (
                        "Current attachment ID or filename. May be omitted when "
                        "the Turn contains exactly one CSV, TSV or XLSX attachment"
                    ),
                },
                "sheet": {"type": "string", "description": "Optional XLSX worksheet name"},
                "collection_id": {
                    "type": "string",
                    "description": "Optional existing Collection to update",
                },
                "collection_name": {
                    "type": "string",
                    "description": "Optional machine name when a Collection must be created",
                },
                "collection_label": {
                    "type": "string",
                    "description": "Optional business label when a Collection must be created",
                },
                "key_column": {
                    "type": "string",
                    "description": "Optional unique column used to match later file revisions",
                },
            },
            "required": ["workspace_id"],
        },
        func=import_tabular_data,
        category="workspace",
    )]
