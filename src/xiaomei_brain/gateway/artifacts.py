"""Agent-owned output artifact discovery and secure retrieval."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_VIDEO_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_VISUALIZATION_ARTIFACT_BYTES = 1 * 1024 * 1024
_OUTPUT_DIRS = {"workspace", "images", "music", "tts", "videos", "projects"}


class ArtifactError(ValueError):
    pass


def discover_tool_artifacts(
    agent_id: str,
    session_id: str,
    turn_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: str,
    *,
    workspace_root: Path | None = None,
    scan_roots: tuple[Path, ...] = (),
) -> list[dict[str, Any]]:
    """Find real output files mentioned by a successful tool call.

    Every candidate must resolve below an Agent-owned output directory. Paths
    outside that boundary are ignored even when a tool result mentions them.
    """
    # Read-only tools describe files they consumed. Treating those paths as
    # newly-created output leaks inputs into the Agent's deliverable list.
    if tool_name in {"read", "glob", "grep", "read_file", "web_get", "web_search"}:
        return []
    if _tool_failed(result):
        return []
    agent_root = _agent_root(agent_id)
    relative_base = workspace_root or (agent_root / "workspace")
    candidates: list[Path] = []

    for key, value in arguments.items():
        if not isinstance(value, str):
            continue
        normalized = key.lower()
        if normalized in {"path", "file", "filename", "file_path", "output", "output_path"}:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = relative_base / candidate
            candidates.append(candidate)

    for value in _structured_strings(result):
        candidates.append(Path(value).expanduser())
    for directory in _OUTPUT_DIRS:
        prefix = str(agent_root / directory)
        pattern = re.compile(re.escape(prefix) + r"[^\r\n'\"]*")
        for match in pattern.finditer(result):
            raw = match.group(0).strip().rstrip("。。，,;；])}")
            candidates.append(Path(raw))
    for root in scan_roots:
        try:
            candidates.extend(path for path in root.rglob("*") if path.is_file())
        except OSError:
            continue

    replacements = _artifact_replacements(result)
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(agent_root.resolve())
        except (OSError, ValueError):
            continue
        if not relative.parts or relative.parts[0] not in _OUTPUT_DIRS or not resolved.is_file():
            continue
        relative_path = relative.as_posix()
        if relative_path in seen:
            continue
        seen.add(relative_path)
        mime_type = _guess_mime_type(resolved)
        kind = _artifact_kind(
            mime_type,
            resolved.suffix.lower(),
            resolved.name,
        )
        size = resolved.stat().st_size
        if size <= 0 or size > _max_artifact_bytes(mime_type, kind):
            continue
        replacement = replacements.get(
            os.path.normcase(str(resolved)),
        )
        artifact_id = str(replacement.get("artifact_id", "")) if replacement else ""
        storage_session_id = str(replacement.get("session_id", "")) if replacement else ""
        if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            artifact_id = hashlib.sha256(
                f"{session_id}\0{turn_id}\0{relative_path}".encode("utf-8"),
            ).hexdigest()[:32]
            replacement = None
        if not storage_session_id:
            storage_session_id = session_id
        suffix = resolved.suffix.lower()[:16]
        storage_path = _artifact_storage_path(
            agent_id, storage_session_id, artifact_id, suffix,
        )
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(storage_path, resolved.read_bytes())
        artifacts.append({
            "id": artifact_id,
            "session_id": storage_session_id,
            "name": resolved.name,
            "mime_type": mime_type,
            "size": size,
            "kind": kind,
            "description": (
                f"Updated by {tool_name}" if replacement
                else f"Created by {tool_name}"
            ),
            "relative_path": relative_path,
            "storage_suffix": suffix,
            "tool_call_id": "",
            "turn_id": turn_id,
            "updated": replacement is not None,
        })
    return artifacts


def public_artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "name", "mime_type", "size", "kind", "description",
        "tool_call_id", "turn_id", "workspace_role", "session_id",
        "updated", "created_at", "updated_at", "presented_at",
    )
    return {key: artifact[key] for key in keys if key in artifact}


def read_stored_artifact(
    agent_id: str,
    session_id: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    artifact_id = str(artifact.get("id", ""))
    suffix = str(artifact.get("storage_suffix", ""))
    if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
        raise ArtifactError("产物标识无效")
    if suffix and not re.fullmatch(r"\.[A-Za-z0-9]{1,15}", suffix):
        raise ArtifactError("产物类型无效")
    path = _artifact_storage_path(agent_id, session_id, artifact_id, suffix)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactError("产物文件不存在或已被移除") from exc
    if not data or len(data) > _max_artifact_bytes(
        str(artifact.get("mime_type") or ""),
        str(artifact.get("kind") or ""),
    ):
        raise ArtifactError("产物为空或超过该类型允许的大小")
    if int(artifact.get("size", -1)) != len(data):
        raise ArtifactError("产物快照与会话记录不一致")
    return {
        **public_artifact_metadata(artifact),
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def project_stored_artifact(
    agent_id: str,
    source_session_id: str,
    target_session_id: str,
    artifact: dict[str, Any],
) -> None:
    """Copy one immutable artifact snapshot into another Agent session."""
    artifact_id = str(artifact.get("id", ""))
    suffix = str(artifact.get("storage_suffix", ""))
    if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
        raise ArtifactError("产物标识无效")
    source = _artifact_storage_path(
        agent_id, source_session_id, artifact_id, suffix,
    )
    target = _artifact_storage_path(
        agent_id, target_session_id, artifact_id, suffix,
    )
    try:
        data = source.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactError("产物文件不存在或已被移除") from exc
    if not data or len(data) != int(artifact.get("size", -1)):
        raise ArtifactError("产物快照与会话记录不一致")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _agent_root(agent_id: str) -> Path:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id or "default")
    return Path.home() / ".xiaomei-brain" / safe_agent


def _artifact_storage_path(
    agent_id: str,
    session_id: str,
    artifact_id: str,
    suffix: str,
) -> Path:
    session_key = hashlib.sha256((session_id or "main").encode("utf-8")).hexdigest()[:16]
    return _agent_root(agent_id) / "artifacts" / session_key / f"{artifact_id}{suffix}"


def managed_artifact_path(agent_id: str, artifact: dict[str, Any]) -> Path:
    """Resolve an artifact's mutable Agent-owned source without trusting clients."""
    relative = Path(str(artifact.get("relative_path", "")))
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[0] not in _OUTPUT_DIRS
    ):
        raise ArtifactError("产物源文件位置无效")
    root = _agent_root(agent_id).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ArtifactError("产物源文件位置无效") from exc
    return candidate


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_replacements(result: str) -> dict[str, dict[str, str]]:
    """Map generated output paths to an existing logical artifact identity."""
    parsed = _structured_value(result)
    if not isinstance(parsed, dict):
        return {}
    raw_items: list[Any] = []
    single = parsed.get("updated_artifact")
    if isinstance(single, dict):
        raw_items.append(single)
    multiple = parsed.get("updated_artifacts")
    if isinstance(multiple, list):
        raw_items.extend(multiple)
    replacements: dict[str, dict[str, str]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifact_id", ""))
        source_session_id = str(item.get("session_id", ""))
        output_path = str(item.get("output_path", ""))
        if (
            re.fullmatch(r"[a-f0-9]{32}", artifact_id)
            and source_session_id
            and output_path
        ):
            replacements[os.path.normcase(str(Path(output_path).resolve()))] = {
                "artifact_id": artifact_id,
                "session_id": source_session_id,
            }
    return replacements


def _tool_failed(result: str) -> bool:
    lowered = result.lower()
    return result.startswith(("Error:", "Blocked")) or "timed out" in lowered or "failed" in lowered


def _structured_strings(result: str) -> list[str]:
    values: list[str] = []
    parsed = _structured_value(result)

    def visit(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"path", "file", "filename", "file_path", "output_path"}:
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    if parsed is not None:
        visit(parsed)

    # Some tools return a short human-readable summary instead of JSON, for
    # example:
    #
    #   Generated 1 image:
    #     - C:\Users\name/.xiaomei-brain/agent\images\image.jpeg
    #
    # Keep those paths discoverable as artifacts.  Do not split on whitespace:
    # Agent-owned output paths may legitimately contain spaces.  Containment is
    # still enforced later by resolving every candidate below the Agent root.
    for raw_line in result.splitlines():
        candidate = raw_line.strip()
        candidate = re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", candidate)
        if re.match(r"^[A-Za-z]:[\\/]", candidate) or candidate.startswith("/"):
            values.append(candidate.strip().strip("'\""))
    return values


def _structured_value(result: str) -> Any:
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(result)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
    return None


def _max_artifact_bytes(mime_type: str, kind: str = "") -> int:
    """Keep the normal snapshot limit small while permitting generated clips."""
    if kind == "visualization":
        return MAX_VISUALIZATION_ARTIFACT_BYTES
    if mime_type.startswith("video/"):
        return MAX_VIDEO_ARTIFACT_BYTES
    return MAX_ARTIFACT_BYTES


def _artifact_kind(mime_type: str, suffix: str, name: str = "") -> str:
    if name.lower().endswith(".visualization.html"):
        return "visualization"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("text/") or suffix in {".md", ".json", ".yaml", ".yml", ".csv"}:
        return "text"
    if suffix in {".docx", ".pptx", ".pdf", ".xlsx", ".xls"}:
        return "document"
    return "file"


def _guess_mime_type(path: Path) -> str:
    office_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return office_types.get(
        path.suffix.lower(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
