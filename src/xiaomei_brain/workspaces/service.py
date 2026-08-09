"""Domain services for business workspaces and their surfaces."""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any

from .action_service import BusinessActionService
from .action_store import BusinessActionStore
from .asset_service import AssetService
from .asset_store import AssetStore
from .business_service import BusinessWorldService
from .business_store import BusinessStore
from .context_service import WorkspaceContextService
from .context_execution import WorkspaceContextExecutionService
from .context_store import WorkspaceContextStore
from .dataset_service import DatasetService
from .dataset_store import DatasetStore
from .models import Surface, Workspace, WorkspacePermissionError
from .store import WorkspaceStore
from .tabular_import import TabularImportService

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
        self.assets = AssetService(
            AssetStore(
                store.db_path,
                before_schema_migration=before_business_migration,
            ),
            store,
            publish=publish,
            clock=clock,
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
        self.schema = self.business.schema
        context_store = WorkspaceContextStore(
            store.db_path,
            before_schema_migration=before_business_migration,
        )
        self.context_execution = WorkspaceContextExecutionService(
            context_store,
            self.business,
            clock=clock,
        )
        self.context = WorkspaceContextService(
            self.store,
            self.business,
            context_store,
            execution=self.context_execution,
            publish=publish,
            clock=clock,
        )
        self.actions = BusinessActionService(
            BusinessActionStore(
                store.db_path,
                before_schema_migration=before_business_migration,
            ),
            self.business,
            store,
            self.context,
            publish=publish,
            clock=clock,
        )
        self.datasets = DatasetService(
            DatasetStore(
                store.db_path,
                before_schema_migration=before_business_migration,
            ),
            self.business,
            publish=publish,
            clock=clock,
        )
        self.business._on_collection_changed = self.datasets.invalidate_collection
        self.business.set_context_executor(
            self.context_execution.apply_before_record_write,
        )
        self.imports = TabularImportService(self.business)
        self.surfaces = SurfaceService(
            store,
            datasets=self.datasets,
            assets=self.assets,
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

    def focus_session(
        self,
        workspace_id: str,
        *,
        session_id: str,
        person_id: str,
        turn_id: str = "",
    ) -> Workspace:
        resolved_session = session_id.strip()
        if not resolved_session:
            raise ValueError("A conversation Session is required to focus a Workspace")
        workspace = self.require_for_person(
            workspace_id,
            person_id=person_id.strip(),
        )
        self.store.focus_session(
            workspace.id,
            session_id=resolved_session,
            person_id=person_id.strip(),
            turn_id=turn_id.strip(),
            now=self._clock(),
        )
        return workspace

    def current_for_session(
        self,
        session_id: str,
        *,
        person_id: str,
    ) -> Workspace | None:
        workspace_id = self.store.focused_workspace_id(
            session_id,
            person_id=person_id,
        )
        if not workspace_id:
            return None
        try:
            return self.require_for_person(workspace_id, person_id=person_id)
        except (KeyError, WorkspacePermissionError):
            return None

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
            action_snapshot = self.actions.workspace_snapshot(workspace.id)
            established_candidates = {
                item["source_candidate_id"]
                for item in action_snapshot["actions"]
            }
            payload["business"]["action_candidates"] = [
                item for item in payload["business"]["action_candidates"]
                if item["id"] not in established_candidates
            ]
            payload["business"].update(action_snapshot)
            payload["business"]["contexts"] = self.context.list_snapshots(
                workspace.id,
                include_inactive=True,
            )
            payload["business"]["assets"] = self.assets.list_snapshots(
                workspace.id,
            )
            payload["datasets"] = [
                self.datasets.snapshot(item)
                for item in self.datasets.list_for_workspace(workspace.id)
            ]
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
        datasets: DatasetService | None = None,
        assets: AssetService | None = None,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.datasets = datasets
        self.assets = assets
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
        persistence: str = "persistent",
        session_id: str = "",
        turn_id: str = "",
    ) -> Surface:
        if self.store.get(workspace_id) is None:
            raise KeyError(workspace_id)
        resolved_persistence = persistence.strip() or "persistent"
        if resolved_persistence not in {"temporary", "persistent"}:
            raise ValueError("Surface persistence must be temporary or persistent")
        if is_default and resolved_persistence != "persistent":
            raise ValueError("A default Surface must be persistent")
        normalized_definition = self.validate_definition(definition)
        self._validate_bindings(workspace_id, normalized_definition)
        surface = self.store.create_surface(
            workspace_id,
            name=name.strip() or "Surface",
            purpose=purpose.strip(),
            definition=normalized_definition,
            is_default=is_default,
            status=resolved_persistence,
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
        persistence: str | None = None,
        expected_revision: int | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Surface:
        current = self.store.get_surface(surface_id)
        if current is None:
            raise KeyError(surface_id)
        resolved_persistence = current.status
        if persistence is not None:
            resolved_persistence = persistence.strip()
            if resolved_persistence not in {"temporary", "persistent"}:
                raise ValueError("Surface persistence must be temporary or persistent")
        if current.is_default and resolved_persistence != "persistent":
            raise ValueError("A default Surface must be persistent")
        normalized_definition = (
            current.definition if definition is None
            else self.validate_definition(definition)
        )
        self._validate_bindings(current.workspace_id, normalized_definition)
        surface = self.store.update_surface(
            current.id,
            name=current.name if name is None else (name.strip() or current.name),
            purpose=current.purpose if purpose is None else purpose.strip(),
            definition=normalized_definition,
            status=resolved_persistence,
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
        seen: set[str] = set()
        component_count = 0

        def normalize_component(
            component: Any,
            index: int,
            parent_id: str = "",
        ) -> dict[str, Any]:
            nonlocal component_count
            if not isinstance(component, dict):
                raise ValueError(f"Component {index + 1} must be an object")
            component_count += 1
            if component_count > MAX_COMPONENTS:
                raise ValueError(
                    f"Surface supports at most {MAX_COMPONENTS} components"
                )
            item = dict(component)
            component_type = str(item.get("type") or "").strip()
            if component_type not in ALLOWED_COMPONENT_TYPES:
                raise ValueError(f"Unsupported surface component: {component_type}")
            fallback_id = (
                f"{parent_id}_component_{index + 1}"
                if parent_id else f"component_{index + 1}"
            )
            component_id = str(item.get("id") or fallback_id).strip()
            if not component_id or component_id in seen:
                raise ValueError("Surface component IDs must be unique")
            seen.add(component_id)
            item["id"] = component_id
            item["type"] = component_type
            item["title"] = str(item.get("title") or "").strip()
            binding = item.get("binding")
            if binding is not None:
                if not isinstance(binding, dict):
                    raise ValueError("Surface component binding must be an object")
                if component_type == "asset":
                    if not str(binding.get("asset_id") or "").strip():
                        raise ValueError("Asset component binding requires asset_id")
                elif not str(binding.get("dataset_id") or "").strip():
                    raise ValueError("Surface Dataset binding requires dataset_id")
            if component_type == "asset" and binding is None:
                if not str(item.get("asset_id") or "").strip():
                    raise ValueError("Asset component requires asset_id")
            if component_type == "group":
                children = item.get("components")
                if not isinstance(children, list) or not children:
                    raise ValueError("Group component requires nested components")
                item["components"] = [
                    normalize_component(child, child_index, component_id)
                    for child_index, child in enumerate(children)
                ]
            return item

        normalized = [
            normalize_component(component, index)
            for index, component in enumerate(components)
        ]
        result = dict(definition)
        result["components"] = normalized
        encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_DEFINITION_BYTES:
            raise ValueError("Surface definition is too large")
        return result

    def _validate_bindings(
        self,
        workspace_id: str,
        definition: dict[str, Any],
    ) -> None:
        """Reject invented or cross-Workspace Dataset IDs before persistence."""
        if self.datasets is None:
            return

        def validate_component(component: Any) -> None:
            if not isinstance(component, dict):
                return
            if component.get("type") == "group":
                for child in component.get("components") or []:
                    validate_component(child)
                return
            binding = component.get("binding")
            if not isinstance(binding, dict) or component.get("type") == "asset":
                return
            dataset_id = str(binding.get("dataset_id") or "").strip()
            if not dataset_id:
                return
            dataset = self.datasets.store.get(dataset_id)
            if dataset is None:
                raise ValueError(
                    "Surface binding requires an existing dataset_id returned "
                    f"by create_dataset: {dataset_id}",
                )
            dataset = self.datasets.require(dataset_id, refresh_stale=True)
            if dataset.workspace_id != workspace_id:
                raise ValueError("Dataset does not belong to the Surface Workspace")
            component_type = str(component.get("type") or "")
            columns = dataset.data.get("columns")
            column_keys = {
                str(item.get("key") or "")
                for item in columns or []
                if isinstance(item, dict) and str(item.get("key") or "")
            }
            if component_type == "metric":
                metric_key = str(binding.get("metric_key") or "").strip()
                metric_keys = {
                    str(item.get("key") or "")
                    for item in dataset.data.get("metrics") or []
                    if isinstance(item, dict)
                }
                if not metric_key or metric_key not in metric_keys:
                    raise ValueError(
                        f"Surface metric binding not found in Dataset: {metric_key}"
                    )
            elif component_type in {"table", "record"}:
                if not isinstance(dataset.data.get("rows"), list):
                    raise ValueError(
                        f"Surface {component_type} requires a row Dataset"
                    )
            elif component_type in {"bar_chart", "line_chart", "pie_chart"}:
                if not isinstance(dataset.data.get("points"), list):
                    label_field = str(binding.get("label_field") or "").strip()
                    value_field = str(binding.get("value_field") or "").strip()
                    for field_name, role in (
                        (label_field, "label_field"),
                        (value_field, "value_field"),
                    ):
                        if not field_name or field_name not in column_keys:
                            raise ValueError(
                                f"Surface chart {role} not found in Dataset columns: "
                                f"{field_name}"
                            )
            elif component_type == "timeline" and not isinstance(
                dataset.data.get("points"), list,
            ):
                for role in ("time_field", "title_field", "detail_field"):
                    field_name = str(binding.get(role) or "").strip()
                    if field_name and field_name not in column_keys:
                        raise ValueError(
                            f"Surface timeline {role} not found in Dataset columns: "
                            f"{field_name}"
                        )

        for component in definition.get("components") or []:
            validate_component(component)

    def snapshot(self, surface: Surface) -> dict[str, Any]:
        payload = {
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
        if self.datasets is not None:
            payload["resolved_definition"] = self._resolve_definition(
                surface.definition,
                surface.workspace_id,
            )
        return payload

    def _resolve_definition(
        self,
        definition: dict[str, Any],
        workspace_id: str,
    ) -> dict[str, Any]:
        resolved = copy.deepcopy(definition)
        components = resolved.get("components")
        if not isinstance(components, list) or self.datasets is None:
            return resolved
        def resolve_component(component: Any) -> None:
            if not isinstance(component, dict):
                return
            if component.get("type") == "group":
                for child in component.get("components") or []:
                    resolve_component(child)
                return
            binding = component.get("binding")
            if component.get("type") == "asset":
                asset_id = str(
                    (binding or {}).get("asset_id")
                    if isinstance(binding, dict)
                    else component.get("asset_id") or ""
                ).strip()
                if not asset_id or self.assets is None:
                    component["binding_error"] = "Asset binding is unavailable"
                    return
                asset = self.assets.store.get(asset_id)
                if (
                    asset is None
                    or not self.assets.store.is_linked(
                        asset.id,
                        workspace_id,
                    )
                ):
                    component["binding_error"] = "Asset is not linked to this Workspace"
                    return
                component["asset"] = self.assets.snapshot(asset)
                return
            if not isinstance(binding, dict):
                return
            dataset_id = str(binding.get("dataset_id") or "").strip()
            if not dataset_id:
                component["binding_error"] = "Dataset binding has no dataset_id"
                return
            try:
                dataset = self.datasets.require(dataset_id, refresh_stale=True)
                presented_data = self.datasets.present_data(
                    workspace_id,
                    dataset.data,
                )
                self._apply_dataset(component, presented_data, binding)
                component["dataset_revision"] = dataset.revision
                component["dataset_status"] = dataset.status
            except Exception as exc:
                component["binding_error"] = str(exc)
        for component in components:
            resolve_component(component)
        return resolved

    @staticmethod
    def _apply_dataset(
        component: dict[str, Any],
        data: dict[str, Any],
        binding: dict[str, Any],
    ) -> None:
        component_type = str(component.get("type") or "")
        if component_type == "metric":
            metric_key = str(binding.get("metric_key") or "")
            metrics = data.get("metrics") if isinstance(data.get("metrics"), list) else []
            metric = next(
                (item for item in metrics if str(item.get("key") or "") == metric_key),
                None,
            )
            if metric is None:
                raise ValueError(f"Dataset metric not found: {metric_key}")
            component["value"] = metric.get("value")
            component["unit"] = metric.get("unit") or component.get("unit") or ""
            if not component.get("title"):
                component["title"] = metric.get("label") or metric_key
            return
        if component_type in {"table", "record"}:
            component["columns"] = data.get("columns") or []
            component["rows"] = data.get("rows") or []
            return
        if component_type == "timeline":
            if isinstance(data.get("points"), list):
                component["items"] = [
                    {
                        "time": item.get("period"),
                        "title": item.get("label") or item.get("period"),
                        "detail": item.get("value"),
                    }
                    for item in data["points"]
                    if isinstance(item, dict)
                ]
                return
            rows = data.get("rows") if isinstance(data.get("rows"), list) else []
            time_field = str(binding.get("time_field") or "")
            title_field = str(binding.get("title_field") or "")
            detail_field = str(binding.get("detail_field") or "")
            component["items"] = [
                {
                    "time": row.get(time_field) if time_field else "",
                    "title": row.get(title_field) if title_field else "",
                    "detail": row.get(detail_field) if detail_field else "",
                }
                for row in rows if isinstance(row, dict)
            ]
            return
        if component_type in {"bar_chart", "line_chart", "pie_chart"}:
            if isinstance(data.get("points"), list):
                component["data"] = [
                    {"label": item.get("period"), "value": item.get("value")}
                    for item in data["points"]
                ]
                return
            rows = data.get("rows") if isinstance(data.get("rows"), list) else []
            label_field = str(binding.get("label_field") or "")
            value_field = str(binding.get("value_field") or "")
            if not label_field or not value_field:
                raise ValueError("Chart binding requires label_field and value_field")
            component["data"] = [
                {"label": row.get(label_field), "value": row.get(value_field)}
                for row in rows if isinstance(row, dict)
            ]

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
