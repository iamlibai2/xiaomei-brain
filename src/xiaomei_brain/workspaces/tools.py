"""Agent tools for creating business workspaces and interactive surfaces."""

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

    def create_workspace(
        name: str,
        purpose: str,
        description: str = "",
        initial_surface: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a persistent business world, optionally with its first Surface."""
        session_id, turn_id = context()
        workspace = service().create(
            name=name,
            purpose=purpose,
            description=description,
            created_reason="Created by the Agent from the current conversation",
            created_by_person_id=person_id(),
            default_surface_definition=initial_surface,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(workspace, include_surfaces=True)

    def update_workspace(
        workspace_id: str,
        expected_revision: int,
        name: str = "",
        purpose: str = "",
        description: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        """Update a Workspace's identity, purpose, lifecycle or description."""
        session_id, turn_id = context()
        workspace = service().update(
            workspace_id,
            name=name or None,
            purpose=purpose or None,
            description=description or None,
            status=status or None,
            expected_revision=expected_revision,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(workspace, include_surfaces=True)

    def create_surface(
        workspace_id: str,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create a durable interactive Surface inside a Workspace."""
        service().require(workspace_id)
        session_id, turn_id = context()
        surface = service().surfaces.create(
            workspace_id,
            name=name,
            purpose=purpose,
            definition=definition,
            is_default=is_default,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().surfaces.snapshot(surface)

    def update_surface(
        surface_id: str,
        definition: dict[str, Any],
        expected_revision: int,
        name: str = "",
        purpose: str = "",
    ) -> dict[str, Any]:
        """Replace one Surface definition after inspecting its current revision."""
        session_id, turn_id = context()
        surface = service().surfaces.update(
            surface_id,
            name=name or None,
            purpose=purpose or None,
            definition=definition,
            expected_revision=expected_revision,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().surfaces.snapshot(surface)

    def get_workspace(workspace_id: str) -> dict[str, Any]:
        """Inspect a Workspace and all of its Surfaces."""
        return service().snapshot(
            service().require(workspace_id), include_surfaces=True,
        )

    def list_workspaces() -> dict[str, Any]:
        """List every Workspace in this Agent's world."""
        return {
            "workspaces": [
                service().snapshot(item)
                for item in service().list_all(limit=100)
            ],
        }

    component_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string"},
            "type": {
                "type": "string",
                "enum": [
                    "metric", "text", "table", "record", "bar_chart",
                    "line_chart", "pie_chart", "timeline", "asset", "group",
                ],
            },
            "title": {"type": "string"},
            "value": {},
            "unit": {"type": "string"},
            "detail": {"type": "string"},
            "content": {"type": "string"},
            "columns": {"type": "array", "items": {}},
            "rows": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
            "data": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "required": ["type"],
    }
    definition_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "components": {
                "type": "array",
                "items": component_schema,
                "minItems": 1,
                "maxItems": 48,
            },
        },
        "required": ["components"],
    }
    return [
        Tool(
            name="create_workspace",
            description=(
                "Create a Workspace only for a business that will continue to change, "
                "be queried or receive future action. Do not create one for a one-off task. "
                "An optional initial_surface may present the first useful business interface."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "initial_surface": definition_schema,
                },
                "required": ["name", "purpose"],
            },
            func=create_workspace,
            category="workspace",
        ),
        Tool(
            name="update_workspace",
            description=(
                "Update a Workspace's name, purpose, description or active/closed status. "
                "Surface contents are changed with update_surface instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["active", "closed"]},
                },
                "required": ["workspace_id", "expected_revision"],
            },
            func=update_workspace,
            category="workspace",
        ),
        Tool(
            name="create_surface",
            description=(
                "Create a persistent interactive Surface in an existing Workspace. "
                "A Surface presents business data; it is not the Workspace itself."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "definition": definition_schema,
                    "is_default": {"type": "boolean"},
                },
                "required": ["workspace_id", "name", "purpose", "definition"],
            },
            func=create_surface,
            category="workspace",
        ),
        Tool(
            name="update_surface",
            description=(
                "Update an existing Surface after get_workspace. Send its complete "
                "definition and current revision so concurrent changes are preserved."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "surface_id": {"type": "string"},
                    "definition": definition_schema,
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["surface_id", "definition", "expected_revision"],
            },
            func=update_surface,
            category="workspace",
        ),
        Tool(
            name="get_workspace",
            description="Read one Workspace and its Surfaces before changing them.",
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
            description="List the persistent business Workspaces known by this Agent.",
            parameters={"type": "object", "properties": {}},
            func=list_workspaces,
            category="workspace",
        ),
    ]
