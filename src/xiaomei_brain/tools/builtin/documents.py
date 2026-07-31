"""Single Agent-facing tool for all registered document formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from xiaomei_brain.documents import DocumentService
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


def _available_output_path(output_root: Path, requested_name: str) -> Path:
    """Choose a new output path without replacing an earlier deliverable."""
    requested = output_root / requested_name
    if not requested.exists():
        return requested
    stem = requested.stem
    suffix = requested.suffix
    for index in range(1, 10000):
        candidate = output_root / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("Unable to allocate a unique output file name")


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


def create_write_document_tool(plugin_registry: Any) -> Tool:
    """Create the stable authoring tool; format details remain plugin-owned."""

    def write_document(
        format: str,
        specification_path: str,
        output_name: str,
        source_attachment_id: str = "",
    ) -> dict[str, Any]:
        context = current_tool_execution()
        if context is None:
            return {"error": "write_document is only available during an Agent tool call"}
        writer = plugin_registry.get_document_writer(format)
        if writer is None:
            return {
                "error": f"No writer supports format: {format}",
                "available_formats": plugin_registry.list_document_writers(),
            }

        from xiaomei_brain.tools.builtin.file_ops import get_workspace_dir

        workspace_root = Path(context.workspace_root or get_workspace_dir()).resolve()
        output_root = Path(context.output_root or workspace_root).resolve()
        spec_path = Path(specification_path).expanduser()
        if not spec_path.is_absolute():
            spec_path = workspace_root / spec_path
        try:
            spec_path = spec_path.resolve(strict=True)
            spec_path.relative_to(workspace_root)
        except (OSError, ValueError):
            return {"error": "Specification must be an existing JSON file inside the current workspace"}
        if spec_path.stat().st_size > 1024 * 1024:
            return {"error": "Specification exceeds 1 MB"}
        try:
            specification = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"error": f"Invalid specification JSON: {exc}"}
        if not isinstance(specification, dict):
            return {"error": "Specification root must be a JSON object"}

        safe_name = Path(output_name).name
        if not safe_name or safe_name != output_name:
            return {"error": "output_name must be a plain file name"}
        suffix = str(getattr(writer, "suffix", "")).lower()
        if Path(safe_name).suffix.lower() != suffix:
            return {"error": f"Output file must use the {suffix} extension"}
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            output_path = _available_output_path(output_root, safe_name).resolve()
            output_path.relative_to(output_root)
        except (OSError, ValueError):
            return {"error": "Output path is outside the current output directory"}

        source_path = None
        if source_attachment_id:
            attachment = next(
                (
                    item for item in context.attachments
                    if str(item.get("id")) == source_attachment_id
                ),
                None,
            )
            if attachment is None or attachment.get("kind") != "document":
                return {"error": "Source attachment is not available in the current execution context"}
            source_path = Path(str(attachment.get("local_path") or ""))
            if not source_path.is_file():
                return {"error": "Source attachment file is unavailable"}

        asset_paths: dict[str, Path] = {}
        for attachment in context.attachments:
            attachment_id = str(attachment.get("id") or "")
            local_path = Path(str(attachment.get("local_path") or ""))
            if attachment_id and local_path.is_file():
                asset_paths[attachment_id] = local_path

        temporary_path = output_root / (
            f".{output_path.stem}.{uuid4().hex}.tmp{output_path.suffix}"
        )
        try:
            result = writer.write(
                specification,
                temporary_path,
                source_path=source_path,
                asset_paths=asset_paths,
            )
            temporary_path.replace(output_path)
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            return {"error": str(exc), "format": format}
        return {
            "success": True,
            "format": str(format).lower(),
            "output_path": str(output_path),
            "output_name": output_path.name,
            **result,
        }

    return Tool(
        name="write_document",
        description=(
            "Create or revise a document through a registered format plugin. First write the "
            "format-specific JSON specification inside the current workspace, then pass its "
            "relative path. To revise an uploaded document, pass its current attachment id; "
            "the original is never overwritten."
        ),
        parameters={
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "Registered format id, for example word"},
                "specification_path": {"type": "string", "description": "JSON specification path inside the workspace"},
                "output_name": {"type": "string", "description": "Plain final file name including extension"},
                "source_attachment_id": {"type": "string", "description": "Optional current attachment id to revise"},
            },
            "required": ["format", "specification_path", "output_name"],
        },
        func=write_document,
        category="document",
    )
