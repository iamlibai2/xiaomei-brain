"""Single Agent-facing tool for all registered document formats."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from xiaomei_brain.documents import DocumentService
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


_DOCUMENT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_MAX_DOCUMENT_ASSET_BYTES = 10 * 1024 * 1024
_TARGET_LOCKS: dict[str, threading.Lock] = {}
_TARGET_LOCKS_GUARD = threading.Lock()


def _target_lock(path: Path) -> threading.Lock:
    key = str(path.resolve()).casefold()
    with _TARGET_LOCKS_GUARD:
        return _TARGET_LOCKS.setdefault(key, threading.Lock())


def _workspace_asset_references(value: Any) -> set[str]:
    """Collect explicit workspace_path values without scanning the workspace."""
    found: set[str] = set()
    if isinstance(value, dict):
        raw_path = value.get("workspace_path")
        if isinstance(raw_path, str) and raw_path.strip():
            found.add(raw_path.strip())
        for child in value.values():
            found.update(_workspace_asset_references(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_workspace_asset_references(child))
    return found


def _resolve_workspace_asset(
    raw_path: str,
    workspace_root: Path,
    working_directory: Path,
) -> Path:
    """Resolve one explicitly referenced image inside the execution workspace."""
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"workspace_path must be a relative workspace path: {raw_path}")
    first = candidate.parts[0].lower() if candidate.parts else ""
    base = workspace_root if first in {"inputs", "work", "outputs"} else working_directory
    try:
        resolved = (base / candidate).resolve(strict=True)
        resolved.relative_to(workspace_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Workspace image is unavailable: {raw_path}") from exc
    if not resolved.is_file() or resolved.suffix.lower() not in _DOCUMENT_IMAGE_SUFFIXES:
        raise ValueError(f"workspace_path is not a supported image: {raw_path}")
    if resolved.stat().st_size > _MAX_DOCUMENT_ASSET_BYTES:
        raise ValueError(f"Workspace image exceeds 10 MB: {raw_path}")
    return resolved


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
        readable_attachment = dict(attachment)
        managed_path = Path(str(attachment.get("managed_artifact_path") or ""))
        if managed_path.is_file():
            # Referenced Agent artifacts remain mutable during the turn.  The
            # prepared attachment is an immutable ingress snapshot, so reading
            # it after write_document would otherwise return stale content.
            readable_attachment["local_path"] = str(managed_path)
        source = db_path_provider()
        db_path = getattr(source, "db_path", None) if source is not None else None
        try:
            return DocumentService(plugin_registry, db_path).read(
                readable_attachment,
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


def create_write_document_tool(
    plugin_registry: Any,
    template_service: Any | None = None,
) -> Tool:
    """Create the stable authoring tool; format details remain plugin-owned."""

    def write_document(
        format: str,
        specification_path: str,
        output_name: str,
        source_attachment_id: str = "",
        template_id: str = "",
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
        working_directory = Path(context.working_directory or workspace_root).resolve()
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
        source_path = None
        source_artifact: dict[str, Any] | None = None
        managed_artifact_target: Path | None = None
        template_record = None
        if source_attachment_id and template_id:
            return {"error": "source_attachment_id 和 template_id 不能同时使用"}
        if template_id:
            if template_service is None:
                return {"error": "当前运行环境没有启用文档模板库"}
            try:
                template_record, source_path = template_service.source_for_use(
                    template_id,
                    context.person_id,
                )
            except Exception as exc:
                return {"error": str(exc), "template_id": template_id}
            if template_record.format != str(format).strip().lower():
                return {
                    "error": (
                        f"模板格式 {template_record.format} 与输出格式 {format} 不一致"
                    ),
                }
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
            raw_source_artifact = attachment.get("source_artifact")
            raw_managed_path = str(attachment.get("managed_artifact_path") or "")
            if isinstance(raw_source_artifact, dict) and raw_managed_path:
                candidate = Path(raw_managed_path).resolve()
                if candidate.suffix.lower() != suffix:
                    return {"error": "原产物格式与目标格式不一致"}
                source_artifact = dict(raw_source_artifact)
                managed_artifact_target = candidate
                if candidate.is_file():
                    # Multiple revisions in one turn must build on the latest
                    # Agent-owned file, not on the immutable ingress snapshot.
                    source_path = candidate

        try:
            output_root.mkdir(parents=True, exist_ok=True)
            if managed_artifact_target is not None:
                managed_artifact_target.parent.mkdir(parents=True, exist_ok=True)
                output_path = managed_artifact_target
            else:
                output_path = _available_output_path(output_root, safe_name).resolve()
                output_path.relative_to(output_root)
        except (OSError, ValueError):
            return {"error": "Output path is outside the current output directory"}

        asset_paths: dict[str, Path] = {}
        for attachment in context.attachments:
            attachment_id = str(attachment.get("id") or "")
            local_path = Path(str(attachment.get("local_path") or ""))
            if attachment_id and local_path.is_file():
                asset_paths[attachment_id] = local_path
        try:
            for workspace_path in _workspace_asset_references(specification):
                asset_paths[f"workspace:{workspace_path}"] = _resolve_workspace_asset(
                    workspace_path,
                    workspace_root,
                    working_directory,
                )
        except ValueError as exc:
            return {"error": str(exc), "format": format}

        temporary_path = output_path.parent / (
            f".{output_path.stem}.{uuid4().hex}.tmp{output_path.suffix}"
        )
        try:
            with _target_lock(output_path):
                result = writer.write(
                    specification,
                    temporary_path,
                    source_path=source_path,
                    asset_paths=asset_paths,
                )
                if (
                    template_record is not None
                    and specification.get("allow_unresolved_placeholders") is not True
                ):
                    unresolved = template_service.validate_generated(
                        template_record,
                        temporary_path,
                    )
                    if unresolved:
                        raise ValueError(
                            "模板仍有未填写字段: " + ", ".join(unresolved[:30])
                        )
                temporary_path.replace(output_path)
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            return {"error": str(exc), "format": format}
        response = {
            "success": True,
            "format": str(format).lower(),
            "output_path": str(output_path),
            "output_name": output_path.name,
            **result,
        }
        if template_record is not None:
            response["template"] = {
                "template_id": template_record.template_id,
                "name": template_record.name,
            }
        if source_artifact is not None:
            response["updated_artifact"] = {
                "artifact_id": str(source_artifact.get("artifact_id") or ""),
                "session_id": str(source_artifact.get("session_id") or ""),
                "output_path": str(output_path),
            }
        return response

    return Tool(
        name="write_document",
        description=(
            "Create or revise a document through a registered format plugin. First write the "
            "format-specific JSON specification inside the current workspace, then pass its "
            "relative path. To revise an uploaded document, pass its current attachment id; "
            "to create from an Agent-owned template, pass template_id instead. The original "
            "uploaded attachment or template is never overwritten. When the source attachment is an "
            "Agent-owned artifact, update that artifact in place and keep its artifact id. Specifications "
            "may reference current image "
            "attachment ids or relative workspace image paths exposed by image tools."
        ),
        parameters={
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "Registered format id, for example word"},
                "specification_path": {"type": "string", "description": "JSON specification path inside the workspace"},
                "output_name": {"type": "string", "description": "Plain final file name including extension"},
                "source_attachment_id": {"type": "string", "description": "Optional current attachment id to revise"},
                "template_id": {"type": "string", "description": "Optional reusable template id or exact visible template name"},
            },
            "required": ["format", "specification_path", "output_name"],
        },
        func=write_document,
        category="document",
    )
