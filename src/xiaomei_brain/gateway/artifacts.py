"""Agent-owned output artifact discovery and secure retrieval."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
_OUTPUT_DIRS = {"workspace", "images", "music", "tts"}


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
    if tool_name in {"read_file", "web_get", "web_search"}:
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
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_ARTIFACT_BYTES:
            continue
        mime_type = _guess_mime_type(resolved)
        artifact_id = hashlib.sha256(
            f"{session_id}\0{turn_id}\0{relative_path}".encode("utf-8"),
        ).hexdigest()[:32]
        suffix = resolved.suffix.lower()[:16]
        storage_path = _artifact_storage_path(agent_id, session_id, artifact_id, suffix)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(resolved.read_bytes())
        artifacts.append({
            "id": artifact_id,
            "name": resolved.name,
            "mime_type": mime_type,
            "size": size,
            "kind": _artifact_kind(mime_type, resolved.suffix.lower()),
            "description": f"Created by {tool_name}",
            "relative_path": relative_path,
            "storage_suffix": suffix,
            "tool_call_id": "",
            "turn_id": turn_id,
        })
    return artifacts


def public_artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "name", "mime_type", "size", "kind", "description",
        "tool_call_id", "turn_id", "workspace_role",
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
    if not data or len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("产物为空或超过 20 MB")
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


def _tool_failed(result: str) -> bool:
    lowered = result.lower()
    return result.startswith(("Error:", "Blocked")) or "timed out" in lowered or "failed" in lowered


def _structured_strings(result: str) -> list[str]:
    values: list[str] = []
    parsed: Any = None
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(result)
            break
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue

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


def _artifact_kind(mime_type: str, suffix: str) -> str:
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
