"""Runtime boundary for filesystem resources bundled with Skills."""

from __future__ import annotations

from typing import Any


def activate_skill_resource_root(agent: Any, skill: dict[str, Any]) -> str:
    """Grant one installed Skill package read-only access to its Agent Core.

    Skill resources are trusted installed inputs, never Agent outputs. Their
    relative paths resolve from the package root and the root is appended to
    the current Core's read-only boundary without changing its working dir.
    """
    resource_root = str(skill.get("resource_root") or "").strip()
    if not resource_root:
        return ""
    get_runtime_agent = getattr(agent, "_get_agent", None)
    runtime_agent = get_runtime_agent() if callable(get_runtime_agent) else agent
    existing_roots = tuple(
        getattr(runtime_agent, "tool_read_only_roots", ()) or ()
    )
    if resource_root not in existing_roots:
        runtime_agent.tool_read_only_roots = (*existing_roots, resource_root)
    return resource_root
