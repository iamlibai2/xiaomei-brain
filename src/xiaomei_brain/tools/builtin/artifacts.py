"""Explicitly present Agent-owned files to the current conversation."""

from __future__ import annotations

import os
from pathlib import Path

from ..base import tool
from .file_ops import get_workspace_dir


_PRESENTABLE_DIRS = frozenset({"workspace", "images", "music", "tts"})
_MAX_PRESENTED_FILES = 10
_MAX_PRESENTED_BYTES = 20 * 1024 * 1024


def _resolve_presentable_file(raw_path: str) -> tuple[Path | None, str]:
    """Resolve one path while keeping delivery inside this Agent's storage."""
    if not str(raw_path).strip():
        return None, "文件路径不能为空"

    agent_root = Path(get_workspace_dir()).resolve().parent
    candidate = Path(os.path.expanduser(str(raw_path).strip()))
    if not candidate.is_absolute():
        candidate = Path(get_workspace_dir()) / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(agent_root)
    except (OSError, ValueError):
        return None, f"文件不存在或不属于当前 Agent：{raw_path}"

    if (
        not relative.parts
        or relative.parts[0] not in _PRESENTABLE_DIRS
        or not resolved.is_file()
    ):
        return None, f"只能交付当前 Agent 自己生成的文件：{raw_path}"
    size = resolved.stat().st_size
    if size <= 0:
        return None, f"不能交付空文件：{raw_path}"
    if size > _MAX_PRESENTED_BYTES:
        return None, f"文件超过 20 MB，无法通过会话交付：{raw_path}"
    return resolved, ""


@tool(
    name="present_artifacts",
    description=(
        "Present final files to the person in the current conversation. "
        "You MUST call this after creating any file the person should view, "
        "download, or receive, including documents, presentations, spreadsheets, "
        "images, audio, archives, and reports. Include every final deliverable, "
        "but never include temporary scripts or intermediate files. Relative paths "
        "are resolved from the current Agent workspace. This is the only explicit "
        "file-delivery action for Desktop, Feishu, and DingTalk."
    ),
)
def present_artifacts(paths: list[str], message: str = "") -> dict | str:
    """Select final Agent-owned files for presentation to the current person."""
    if not paths:
        return "Error: 至少需要选择一个要交付的文件"
    if len(paths) > _MAX_PRESENTED_FILES:
        return f"Error: 一次最多交付 {_MAX_PRESENTED_FILES} 个文件"

    resolved_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        resolved, error = _resolve_presentable_file(str(raw_path))
        if error:
            return f"Error: {error}"
        assert resolved is not None
        normalized = os.path.normcase(str(resolved))
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved_paths.append(str(resolved))

    return {
        "type": "present_artifacts_result",
        # ``path`` is intentionally a list. Artifact discovery recursively
        # consumes this field and creates immutable conversation snapshots.
        "path": resolved_paths,
        "message": str(message).strip(),
        "count": len(resolved_paths),
        "delivered": True,
    }


present_artifacts_tool = present_artifacts
