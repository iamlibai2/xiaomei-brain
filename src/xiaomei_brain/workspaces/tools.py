"""Agent tools for creating and evolving workspaces through dialogue."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.tools.base import Tool


def create_workspace_tools(agent: Any) -> list[Tool]:
    def core() -> Any:
        return agent._get_agent()

    def service():
        value = getattr(agent, "workspace_service", None)
        if value is None:
            value = getattr(core(), "workspace_service", None)
        if value is None:
            raise RuntimeError("Workspace service is not initialized")
        return value

    def person_id() -> str:
        value = str(getattr(core(), "user_id", "")).strip()
        if not value or value in {"global", "system"}:
            raise ValueError("The current conversation has no verified Person")
        return value

    def context() -> tuple[str, str]:
        current = core()
        return (
            str(getattr(current, "session_id", "") or ""),
            str(getattr(current, "turn_id", "") or ""),
        )

    def create_workspace(name: str, description: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Create a persistent workspace from structured components."""
        session_id, turn_id = context()
        workspace = service().create(
            name=name,
            description=description,
            scope_type="person",
            scope_id=person_id(),
            spec=spec,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(workspace)

    def update_workspace(
        workspace_id: str,
        spec: dict[str, Any],
        name: str = "",
        description: str = "",
        expected_revision: int = 0,
    ) -> dict[str, Any]:
        """Replace a workspace description after inspecting its current state."""
        session_id, turn_id = context()
        workspace = service().update(
            workspace_id,
            person_id=person_id(),
            name=name or None,
            description=description or None,
            spec=spec,
            expected_revision=expected_revision or None,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(workspace)

    def get_workspace(workspace_id: str) -> dict[str, Any]:
        """Inspect one workspace before explaining or changing it."""
        return service().snapshot(service().require(workspace_id, person_id=person_id()))

    def list_workspaces() -> dict[str, Any]:
        """List persistent workspaces belonging to the current Person."""
        return {
            "workspaces": [
                service().snapshot(item)
                for item in service().list_for_person(person_id(), limit=100)
            ],
        }

    component_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string"},
            "type": {
                "type": "string",
                "enum": ["metric", "text", "table", "bar_chart", "line_chart", "pie_chart"],
            },
            "title": {"type": "string"},
            "value": {
                "type": "string",
                "description": "metric value; use a number or short display string",
            },
            "unit": {"type": "string"},
            "detail": {"type": "string"},
            "content": {
                "type": "string",
                "description": "text component body",
            },
            "columns": {
                "type": "array",
                "description": "table column keys in display order",
                "items": {"type": "string"},
            },
            "rows": {
                "type": "array",
                "description": "table rows whose keys match columns",
                "items": {"type": "object", "additionalProperties": True},
            },
            "data": {
                "type": "array",
                "description": "chart points as {label: string, value: number}",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "number"},
                    },
                    "required": ["label", "value"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["type"],
    }
    spec_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "components": {
                "type": "array",
                "items": component_schema,
                "minItems": 1,
                "maxItems": 24,
            },
        },
        "required": ["components"],
    }
    return [
        Tool(
            name="create_workspace",
            description=(
                "Create a persistent data workspace when the user asks for a 工作台, dashboard, "
                "or reusable data view. Components may be metric, text, table, bar_chart, "
                "line_chart, or pie_chart. Return real analyzed data, not placeholders."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "spec": spec_schema,
                },
                "required": ["name", "description", "spec"],
            },
            func=create_workspace,
            category="workspace",
        ),
        Tool(
            name="update_workspace",
            description=(
                "Update an existing workspace after get_workspace. Send the complete replacement "
                "spec and its current revision so concurrent changes are not overwritten."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "spec": spec_schema,
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                },
                "required": ["workspace_id", "spec", "expected_revision"],
            },
            func=update_workspace,
            category="workspace",
        ),
        Tool(
            name="get_workspace",
            description="Read the current structured state of a workspace before modifying it.",
            parameters={
                "type": "object",
                "properties": {"workspace_id": {"type": "string"}},
                "required": ["workspace_id"],
            },
            func=get_workspace,
            category="workspace",
        ),
        Tool(
            name="list_workspaces",
            description="List the current Person's saved workspaces.",
            parameters={"type": "object", "properties": {}},
            func=list_workspaces,
            category="workspace",
        ),
    ]
