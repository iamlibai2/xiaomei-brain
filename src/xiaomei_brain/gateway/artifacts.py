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
) -> list[dict[str, Any]]:
    """Find real output files mentioned by a successful tool call.

    Every candidate must resolve below an Agent-owned output directory. Paths
    outside that boundary are ignored even when a tool result mentions them.
    """
    if _tool_failed(result):
        return []
    agent_root = _agent_root(agent_id)
    candidates: list[Path] = []

    for key, value in arguments.items():
        if not isinstance(value, str):
            continue
        normalized = key.lower()
        if normalized in {"path", "file", "filename", "file_path", "output", "output_path"}:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = agent_root / "workspace" / candidate
            candidates.append(candidate)

    for value in _structured_strings(result):
        candidates.append(Path(value).expanduser())
    for directory in _OUTPUT_DIRS:
        prefix = str(agent_root / directory)
        pattern = re.compile(re.escape(prefix) + r"[^\r\n'\"]*")
        for match in pattern.finditer(result):
            raw = match.group(0).strip().rstrip("。。，,;；])}")
            candidates.append(Path(raw))

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
        mime_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
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
    keys = ("id", "name", "mime_type", "size", "kind", "description", "tool_call_id", "turn_id")
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
