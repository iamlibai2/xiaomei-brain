"""Model-facing unified discovery tool."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.tools.base import Tool, tool
from xiaomei_brain.tools.execution_context import current_tool_execution


def create_discover_tool(service: Any) -> Tool:
    @tool(
        name="discover",
        description=(
            "Search all abilities available to this Agent when the currently visible resources "
            "cannot complete the task. One specific query searches user-facing capabilities, "
            "procedural Skills and executable Tools together. Matching Tool schemas are activated "
            "for the next reasoning step; a single unambiguous Skill is loaded immediately."
        ),
    )
    def discover(query: str, limit: int = 5) -> dict[str, Any]:
        """Discover the ability to perform a missing action.

        Args:
            query: Describe the concrete result or missing action, not an internal tool name.
            limit: Maximum candidates per discovery category, from 1 to 8.
        """
        execution = current_tool_execution()
        person_id = execution.person_id if execution is not None else ""
        return service.discover(query, limit=limit, person_id=person_id)

    discover.category = "internal"
    return discover
