"""Create or update one Agent-local Skill from its controlled Workspace."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class AuthoredSkill:
    name: str
    description: str
    version: str
    requires_tools: tuple[str, ...]
    install_dir: Path


def install_authored_skill(
    *,
    source_dir: Path,
    workspace_root: Path,
    skills_dir: Path,
    tool_registry: Any,
) -> AuthoredSkill:
    """Validate and atomically install one filesystem-backed Skill."""
    source = source_dir.expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()
    try:
        relative = source.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("Skill 源目录不能越过当前 Agent Workspace") from exc
    if not relative.parts or relative.parts[0].casefold() == "inputs":
        raise ValueError("Skill 源目录必须位于 Workspace 的可写区域")
    if not source.is_dir():
        raise ValueError(f"Skill 源目录不存在: {relative.as_posix()}")

    skill_file = source / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError("Skill 源目录根部必须包含 SKILL.md")
    metadata = _parse_skill(skill_file)
    missing = [
        name for name in metadata.requires_tools
        if tool_registry is None or tool_registry.get(name) is None
    ]
    if missing:
        raise ValueError("Skill 声明了当前 Agent 不存在的工具: " + ", ".join(missing))

    for item in source.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"Skill 不能包含符号链接: {item.relative_to(source).as_posix()}")

    root = skills_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / metadata.name
    staging = root / f".{metadata.name}.staging-{uuid.uuid4().hex}"
    backup = root / f".{metadata.name}.backup-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise

    return AuthoredSkill(
        name=metadata.name,
        description=metadata.description,
        version=metadata.version,
        requires_tools=metadata.requires_tools,
        install_dir=destination,
    )


def _parse_skill(path: Path) -> AuthoredSkill:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError("SKILL.md 必须以 YAML frontmatter 开头")
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md frontmatter 无效: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter 必须是对象")

    name = str(frontmatter.get("name") or "").strip()
    if not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError("Skill name 只能使用小写字母、数字、点、下划线或连字符")
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        raise ValueError("SKILL.md 必须提供 description")
    if not text[match.end():].strip():
        raise ValueError("SKILL.md 必须包含作业指南正文")

    raw_tools = frontmatter.get("requires_tools", frontmatter.get("tools", []))
    if isinstance(raw_tools, str):
        raw_tools = [item.strip() for item in raw_tools.split(",")]
    if raw_tools is None:
        raw_tools = []
    if not isinstance(raw_tools, list):
        raise ValueError("requires_tools 必须是工具名称数组")
    tools = tuple(dict.fromkeys(
        str(item).strip() for item in raw_tools if str(item).strip()
    ))
    return AuthoredSkill(
        name=name,
        description=description,
        version=str(frontmatter.get("version") or "1.0.0").strip(),
        requires_tools=tools,
        install_dir=path.parent,
    )
