"""Agent-facing writer for interactive conversation visualizations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.builtin.file_ops import get_workspace_dir, write
from xiaomei_brain.tools.execution_context import current_tool_execution


_MAX_VISUALIZATION_BYTES = 1024 * 1024
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _visualization_filename(value: str) -> str:
    """Return a safe plain name with the platform-owned visualization suffix."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("filename cannot be empty")
    if Path(raw).name != raw or raw in {".", ".."}:
        raise ValueError("filename must be a plain file name without directories")

    # Models sometimes include the platform marker without ``.html`` or copy
    # an already duplicated artifact name. Collapse every trailing marker so
    # the platform always owns exactly one canonical suffix.
    stem = raw
    if stem.lower().endswith(".html"):
        stem = stem[:-len(".html")]
    while stem.lower().endswith(".visualization"):
        stem = stem[:-len(".visualization")]
    stem = _INVALID_FILENAME_CHARS.sub("-", stem).strip(" .")
    if not stem:
        raise ValueError("filename must contain visible characters")
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"{stem}-visualization"
    return f"{stem}.visualization.html"


def _available_output_path(output_root: Path, filename: str) -> Path:
    target = output_root / filename
    if not target.exists():
        return target
    suffix = ".visualization.html"
    stem = filename[:-len(suffix)]
    for index in range(1, 10000):
        candidate = output_root / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("unable to allocate a unique visualization file name")


def write_visualization(
    filename: str,
    content: str,
    source_attachment_id: str = "",
) -> dict[str, Any]:
    """Write one self-contained visualization fragment into the output area."""
    context = current_tool_execution()
    if context is None:
        return {"error": "write_visualization is only available during an Agent tool call"}
    if not isinstance(content, str) or not content.strip():
        return {"error": "visualization content cannot be empty"}
    content_size = len(content.encode("utf-8"))
    if content_size > _MAX_VISUALIZATION_BYTES:
        return {"error": "visualization content exceeds 1 MB"}

    try:
        safe_name = _visualization_filename(filename)
        output_root = Path(context.output_root or get_workspace_dir()).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        source_artifact: dict[str, Any] | None = None
        if source_attachment_id:
            attachment = next(
                (
                    item for item in context.attachments
                    if str(item.get("id", "")) == source_attachment_id
                ),
                None,
            )
            if attachment is None:
                return {"error": "source attachment is not available in this turn"}
            raw_source = attachment.get("source_artifact")
            raw_managed_path = str(attachment.get("managed_artifact_path") or "")
            if not isinstance(raw_source, dict) or not raw_managed_path:
                return {"error": "source attachment is not an Agent-owned artifact"}
            output_path = Path(raw_managed_path).resolve()
            if not output_path.name.lower().endswith(".visualization.html"):
                return {"error": "source artifact is not a visualization"}
            try:
                output_path.relative_to(output_root)
            except ValueError:
                return {"error": "source visualization is outside the current output area"}
            source_artifact = dict(raw_source)
        else:
            output_path = _available_output_path(output_root, safe_name)
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}

    result = write(str(output_path), content)
    if result.get("error"):
        return result
    response = {
        "success": True,
        "type": "visualization_write_result",
        "kind": "visualization",
        "name": output_path.name,
        "output_path": str(output_path),
        **result,
    }
    if source_artifact is not None:
        response["updated_artifact"] = {
            "artifact_id": str(source_artifact.get("artifact_id") or ""),
            "session_id": str(source_artifact.get("session_id") or ""),
            "output_path": str(output_path),
        }
    return response


write_visualization_tool = Tool(
    name="write_visualization",
    description=(
        "Create a self-contained interactive visualization for the current conversation. "
        "Pass a plain human-readable filename and an HTML fragment containing CSS and "
        "JavaScript. Version-pinned static dependencies may use the visualization CDN "
        "allowlist, but API requests are unavailable. The platform assigns the protected "
        ".visualization.html suffix; do not use the generic write tool for visualizations. "
        "When revising an attached Agent-owned visualization, pass its source_attachment_id "
        "to update the same artifact in place. Never reconstruct the Agent data directory "
        "as an absolute path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": (
                    "Plain display filename. .html or .visualization is optional; "
                    "all variants are normalized to one .visualization.html suffix"
                ),
            },
            "content": {
                "type": "string",
                "description": "HTML fragment with inline CSS and JavaScript, at most 1 MB",
            },
            "source_attachment_id": {
                "type": "string",
                "description": (
                    "Optional id of the current attached visualization. When present, "
                    "the Agent-owned source and artifact identity are updated in place"
                ),
            },
        },
        "required": ["filename", "content"],
    },
    func=write_visualization,
    source="plugin:visualize",
    category="visualization",
)
