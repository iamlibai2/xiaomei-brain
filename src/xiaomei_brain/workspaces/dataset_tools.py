"""Agent tools for reusable Dataset computation."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.tools.base import Tool


def create_dataset_tools(agent: Any) -> list[Tool]:
    def core() -> Any:
        return agent._get_agent()

    def workspace_service():
        workspace_service = getattr(agent, "workspace_service", None)
        if workspace_service is None:
            workspace_service = getattr(core(), "workspace_service", None)
        if workspace_service is None:
            raise RuntimeError("Workspace service is not initialized")
        return workspace_service

    def service():
        return workspace_service().datasets

    def person_id() -> str:
        value = str(getattr(core(), "user_id", "")).strip()
        if not value or value in {"global", "system"}:
            raise ValueError("The current conversation has no verified Person")
        return value

    def require_workspace(workspace_id: str) -> None:
        workspace_service().require_for_person(
            workspace_id,
            person_id=person_id(),
        )

    def require_dataset(dataset_id: str) -> None:
        dataset = service().store.get(dataset_id)
        if dataset is None:
            raise KeyError(dataset_id)
        require_workspace(dataset.workspace_id)

    def context() -> tuple[str, str]:
        current = core()
        return (
            str(getattr(current, "session_id", "") or ""),
            str(getattr(current, "turn_id", "") or ""),
        )

    def create_dataset(
        workspace_id: str,
        name: str,
        kind: str,
        source_collection_id: str,
        source_spec: dict[str, Any],
        description: str = "",
    ) -> dict[str, Any]:
        require_workspace(workspace_id)
        collection = workspace_service().business.require_collection(
            source_collection_id,
        )
        if collection.workspace_id != workspace_id:
            raise ValueError("Collection does not belong to the Workspace")
        session_id, turn_id = context()
        dataset = service().create(
            workspace_id,
            name=name,
            kind=kind,
            description=description,
            source_collection_id=source_collection_id,
            source_spec=source_spec,
            session_id=session_id,
            turn_id=turn_id,
        )
        return service().snapshot(dataset)

    def recompute_dataset(dataset_id: str, expected_revision: int) -> dict[str, Any]:
        require_dataset(dataset_id)
        session_id, turn_id = context()
        return service().snapshot(service().recompute(
            dataset_id,
            expected_revision=expected_revision,
            session_id=session_id,
            turn_id=turn_id,
        ))

    def list_datasets(workspace_id: str) -> dict[str, Any]:
        require_workspace(workspace_id)
        return {
            "datasets": [
                service().snapshot(item)
                for item in service().list_for_workspace(workspace_id)
            ],
        }

    metric_schema = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "label": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["count", "sum", "average", "minimum", "maximum"],
            },
            "field": {"type": "string"},
            "unit": {"type": "string"},
        },
        "required": ["key", "label", "operation"],
    }
    source_spec_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "filters": {"type": "object", "additionalProperties": True},
            "fields": {"type": "array", "items": {"type": "string"}},
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "metrics": {"type": "array", "items": metric_schema},
            "date_field": {"type": "string"},
            "value_field": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["count", "sum", "average", "minimum", "maximum"],
            },
            "interval": {"type": "string", "enum": ["day", "month"]},
            "label": {"type": "string"},
        },
    }
    return [
        Tool(
            name="create_dataset",
            description=(
                "Create a reusable computed Dataset from one Collection. Use table "
                "for raw or grouped rows, metric_set for KPIs, and time_series for "
                "day/month trends. This is controlled aggregation, not arbitrary SQL."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "name": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["table", "metric_set", "time_series"],
                    },
                    "description": {"type": "string"},
                    "source_collection_id": {"type": "string"},
                    "source_spec": source_spec_schema,
                },
                "required": [
                    "workspace_id", "name", "kind",
                    "source_collection_id", "source_spec",
                ],
            },
            func=create_dataset,
            category="workspace",
        ),
        Tool(
            name="recompute_dataset",
            description=(
                "Explicitly recompute a Dataset from current Collection records. "
                "Stale Datasets bound to a Surface are normally recomputed on demand."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "expected_revision": {"type": "integer", "minimum": 1},
                },
                "required": ["dataset_id", "expected_revision"],
            },
            func=recompute_dataset,
            category="workspace",
        ),
        Tool(
            name="list_datasets",
            description="List reusable Datasets in one Workspace and inspect their bindings.",
            parameters={
                "type": "object",
                "properties": {"workspace_id": {"type": "string"}},
                "required": ["workspace_id"],
            },
            func=list_datasets,
            category="workspace",
        ),
    ]
