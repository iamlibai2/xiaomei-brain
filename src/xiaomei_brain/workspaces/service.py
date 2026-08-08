"""Validation and authorization boundary for workspaces."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .models import Workspace, WorkspacePermissionError
from .store import WorkspaceStore

PublishCallback = Callable[..., Any]

ALLOWED_COMPONENT_TYPES = frozenset({
    "metric", "text", "table", "bar_chart", "line_chart", "pie_chart",
})
MAX_COMPONENTS = 24
MAX_SPEC_BYTES = 2 * 1024 * 1024


class WorkspaceService:
    def __init__(
        self,
        store: WorkspaceStore,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._publish = publish
        self._clock = clock

    def create(
        self,
        *,
        name: str,
        description: str,
        scope_type: str,
        scope_id: str,
        spec: dict[str, Any],
        session_id: str = "",
        turn_id: str = "",
    ) -> Workspace:
        name = name.strip()
        if not name:
            raise ValueError("Workspace name cannot be empty")
        if scope_type != "person" or not scope_id.strip():
            raise ValueError("The first workspace version requires a Person scope")
        validated = self.validate_spec(spec)
        workspace = self.store.create(
            name=name,
            description=description.strip(),
            scope_type=scope_type,
            scope_id=scope_id.strip(),
            spec=validated,
            now=self._clock(),
        )
        self._publish_snapshot(
            "workspace.created", workspace,
            session_id=session_id, turn_id=turn_id,
        )
        return workspace

    def require(self, workspace_id: str, *, person_id: str) -> Workspace:
        workspace = self.store.get(workspace_id.strip())
        if workspace is None:
            raise KeyError(workspace_id)
        if workspace.scope_type != "person" or workspace.scope_id != person_id:
            raise WorkspacePermissionError("Workspace does not belong to the current Person")
        return workspace

    def list_for_person(self, person_id: str, *, limit: int = 100) -> list[Workspace]:
        return self.store.list_for_scope("person", person_id.strip(), limit=limit)

    def update(
        self,
        workspace_id: str,
        *,
        person_id: str,
        name: str | None = None,
        description: str | None = None,
        spec: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Workspace:
        current = self.require(workspace_id, person_id=person_id)
        resolved_name = current.name if name is None else name.strip()
        if not resolved_name:
            raise ValueError("Workspace name cannot be empty")
        updated = self.store.update(
            current.id,
            name=resolved_name,
            description=current.description if description is None else description.strip(),
            spec=current.spec if spec is None else self.validate_spec(spec),
            expected_revision=expected_revision,
            now=self._clock(),
        )
        self._publish_snapshot(
            "workspace.updated", updated,
            session_id=session_id, turn_id=turn_id,
        )
        return updated

    @staticmethod
    def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, dict):
            raise ValueError("Workspace spec must be an object")
        components = spec.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError("Workspace requires at least one component")
        if len(components) > MAX_COMPONENTS:
            raise ValueError(f"Workspace supports at most {MAX_COMPONENTS} components")
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                raise ValueError(f"Component {index + 1} must be an object")
            item = dict(component)
            component_type = str(item.get("type") or "").strip()
            if component_type not in ALLOWED_COMPONENT_TYPES:
                raise ValueError(f"Unsupported workspace component: {component_type}")
            component_id = str(item.get("id") or f"component_{index + 1}").strip()
            if not component_id or component_id in seen:
                raise ValueError("Workspace component IDs must be unique")
            seen.add(component_id)
            item["id"] = component_id
            item["type"] = component_type
            item["title"] = str(item.get("title") or "").strip()
            normalized.append(item)
        result = dict(spec)
        result["components"] = normalized
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_SPEC_BYTES:
            raise ValueError("Workspace data is too large for the first version")
        return result

    @staticmethod
    def snapshot(workspace: Workspace) -> dict[str, Any]:
        return {
            "id": workspace.id,
            "name": workspace.name,
            "description": workspace.description,
            "scope_type": workspace.scope_type,
            "scope_id": workspace.scope_id,
            "spec": workspace.spec,
            "revision": workspace.revision,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
        }

    def _publish_snapshot(
        self,
        event: str,
        workspace: Workspace,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        if self._publish is None:
            return
        payload = self.snapshot(workspace)
        payload["_target_person_id"] = workspace.scope_id
        self._publish(
            event, payload, session_id=session_id, turn_id=turn_id,
        )
