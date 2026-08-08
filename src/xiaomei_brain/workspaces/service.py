"""Domain services for business workspaces and their surfaces."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .business_service import BusinessWorldService
from .business_store import BusinessStore
from .models import Surface, Workspace, WorkspacePermissionError
from .store import WorkspaceStore

PublishCallback = Callable[..., Any]

ALLOWED_COMPONENT_TYPES = frozenset({
    "metric", "text", "table", "record", "bar_chart", "line_chart",
    "pie_chart", "timeline", "asset", "group",
})
MAX_COMPONENTS = 48
MAX_DEFINITION_BYTES = 2 * 1024 * 1024


class WorkspaceService:
    def __init__(
        self,
        store: WorkspaceStore,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
        before_business_migration: Callable[[], Any] | None = None,
    ) -> None:
        self.store = store
        self._publish = publish
        self._clock = clock
        self.surfaces = SurfaceService(
            store, publish=publish, clock=clock,
        )
        self.business = BusinessWorldService(
            BusinessStore(
                store.db_path,
                before_schema_migration=before_business_migration,
            ),
            store,
            publish=publish,
            clock=clock,
        )

    def create(
        self,
        *,
        name: str,
        purpose: str,
        description: str = "",
        created_reason: str = "",
        created_by_person_id: str = "",
        default_surface_definition: dict[str, Any] | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Workspace:
        name = name.strip()
        purpose = purpose.strip()
        if not name:
            raise ValueError("Workspace name cannot be empty")
        if not purpose:
            raise ValueError("Workspace purpose cannot be empty")
        default_surface = None
        if default_surface_definition is not None:
            default_surface = (
                name,
                purpose,
                self.surfaces.validate_definition(default_surface_definition),
            )
        workspace = self.store.create(
            name=name,
            purpose=purpose,
            description=description.strip(),
            created_reason=created_reason.strip(),
            created_by_person_id=created_by_person_id.strip(),
            default_surface=default_surface,
            now=self._clock(),
        )
        self._publish_workspace(
            "workspace.created", workspace,
            session_id=session_id, turn_id=turn_id,
        )
        return workspace

    def require(self, workspace_id: str) -> Workspace:
        workspace = self.store.get(workspace_id.strip())
        if workspace is None:
            raise KeyError(workspace_id)
        return workspace

    def require_for_person(self, workspace_id: str, *, person_id: str) -> Workspace:
        workspace = self.require(workspace_id)
        if not self.store.person_is_linked(workspace.id, person_id):
            raise WorkspacePermissionError(
                "Workspace is not available to the current Person",
            )
        return workspace

    def list_all(self, *, limit: int = 100) -> list[Workspace]:
        return self.store.list_all(limit=limit)

    def list_for_person(self, person_id: str, *, limit: int = 100) -> list[Workspace]:
        return self.store.list_for_person(person_id.strip(), limit=limit)

    def update(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        purpose: str | None = None,
        description: str | None = None,
        status: str | None = None,
        expected_revision: int | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Workspace:
        current = self.require(workspace_id)
        resolved_name = current.name if name is None else name.strip()
        resolved_purpose = current.purpose if purpose is None else purpose.strip()
        resolved_status = current.status if status is None else status.strip()
        if not resolved_name:
            raise ValueError("Workspace name cannot be empty")
        if not resolved_purpose:
            raise ValueError("Workspace purpose cannot be empty")
        if resolved_status not in {"active", "closed"}:
            raise ValueError("Workspace status must be active or closed")
        updated = self.store.update(
            current.id,
            name=resolved_name,
            purpose=resolved_purpose,
            description=(
                current.description if description is None else description.strip()
            ),
            status=resolved_status,
            expected_revision=expected_revision,
            now=self._clock(),
        )
        self._publish_workspace(
            "workspace.updated", updated,
            session_id=session_id, turn_id=turn_id,
        )
        return updated

    def snapshot(
        self,
        workspace: Workspace,
        *,
        include_surfaces: bool = False,
        include_business: bool = False,
        include_records: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": workspace.id,
            "name": workspace.name,
            "purpose": workspace.purpose,
            "description": workspace.description,
            "status": workspace.status,
            "created_reason": workspace.created_reason,
            "created_by_person_id": workspace.created_by_person_id,
            "revision": workspace.revision,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "last_active_at": workspace.last_active_at,
        }
        if include_surfaces:
            payload["surfaces"] = [
                self.surfaces.snapshot(item)
                for item in self.store.list_surfaces(workspace.id)
            ]
        if include_business:
            payload["business"] = self.business.workspace_snapshot(
                workspace.id, include_records=include_records,
            )
        return payload

    def _publish_workspace(
        self,
        event: str,
        workspace: Workspace,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        if self._publish is None:
            return
        payload = self.snapshot(workspace, include_surfaces=True)
        for person_id in self.store.linked_person_ids(workspace.id):
            targeted = dict(payload)
            targeted["_target_person_id"] = person_id
            self._publish(
                event, targeted, session_id=session_id, turn_id=turn_id,
            )


class SurfaceService:
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
        workspace_id: str,
        *,
        name: str,
        purpose: str,
        definition: dict[str, Any],
        is_default: bool = False,
        session_id: str = "",
        turn_id: str = "",
    ) -> Surface:
        if self.store.get(workspace_id) is None:
            raise KeyError(workspace_id)
        surface = self.store.create_surface(
            workspace_id,
            name=name.strip() or "Surface",
            purpose=purpose.strip(),
            definition=self.validate_definition(definition),
            is_default=is_default,
            now=self._clock(),
        )
        self._publish_surface(
            "surface.created", surface,
            session_id=session_id, turn_id=turn_id,
        )
        return surface

    def update(
        self,
        surface_id: str,
        *,
        name: str | None = None,
        purpose: str | None = None,
        definition: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Surface:
        current = self.store.get_surface(surface_id)
        if current is None:
            raise KeyError(surface_id)
        surface = self.store.update_surface(
            current.id,
            name=current.name if name is None else (name.strip() or current.name),
            purpose=current.purpose if purpose is None else purpose.strip(),
            definition=(
                current.definition if definition is None
                else self.validate_definition(definition)
            ),
            expected_revision=expected_revision,
            now=self._clock(),
        )
        self._publish_surface(
            "surface.updated", surface,
            session_id=session_id, turn_id=turn_id,
        )
        return surface

    @staticmethod
    def validate_definition(definition: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(definition, dict):
            raise ValueError("Surface definition must be an object")
        components = definition.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError("Surface requires at least one component")
        if len(components) > MAX_COMPONENTS:
            raise ValueError(f"Surface supports at most {MAX_COMPONENTS} components")
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                raise ValueError(f"Component {index + 1} must be an object")
            item = dict(component)
            component_type = str(item.get("type") or "").strip()
            if component_type not in ALLOWED_COMPONENT_TYPES:
                raise ValueError(f"Unsupported surface component: {component_type}")
            component_id = str(item.get("id") or f"component_{index + 1}").strip()
            if not component_id or component_id in seen:
                raise ValueError("Surface component IDs must be unique")
            seen.add(component_id)
            item["id"] = component_id
            item["type"] = component_type
            item["title"] = str(item.get("title") or "").strip()
            normalized.append(item)
        result = dict(definition)
        result["components"] = normalized
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_DEFINITION_BYTES:
            raise ValueError("Surface definition is too large")
        return result

    @staticmethod
    def snapshot(surface: Surface) -> dict[str, Any]:
        return {
            "id": surface.id,
            "workspace_id": surface.workspace_id,
            "name": surface.name,
            "purpose": surface.purpose,
            "definition": surface.definition,
            "status": surface.status,
            "is_default": surface.is_default,
            "revision": surface.revision,
            "created_at": surface.created_at,
            "updated_at": surface.updated_at,
        }

    def _publish_surface(
        self,
        event: str,
        surface: Surface,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        if self._publish is None:
            return
        payload = self.snapshot(surface)
        for person_id in self.store.linked_person_ids(surface.workspace_id):
            targeted = dict(payload)
            targeted["_target_person_id"] = person_id
            self._publish(
                event, targeted, session_id=session_id, turn_id=turn_id,
            )
