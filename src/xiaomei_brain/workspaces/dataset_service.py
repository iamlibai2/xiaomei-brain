"""Controlled computation and invalidation of reusable Workspace datasets."""

from __future__ import annotations

import copy
import datetime as dt
import json
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .business_service import BusinessWorldService
from .dataset_store import DatasetStore
from .models import BusinessRecord, Dataset, FieldDefinition

PublishCallback = Callable[..., Any]
ALLOWED_KINDS = frozenset({"table", "metric_set", "time_series"})
ALLOWED_OPERATIONS = frozenset({
    "count", "distinct_count", "sum", "average", "minimum", "maximum",
})


class DatasetService:
    def __init__(
        self,
        store: DatasetStore,
        business: BusinessWorldService,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.business = business
        self._publish = publish
        self._clock = clock

    def create(
        self,
        workspace_id: str,
        *,
        name: str,
        kind: str,
        description: str,
        source_collection_id: str,
        source_spec: dict[str, Any],
        session_id: str = "",
        turn_id: str = "",
    ) -> Dataset:
        collection = self.business.require_collection(source_collection_id)
        if collection.workspace_id != workspace_id:
            raise ValueError("Collection does not belong to the Workspace")
        resolved_kind = kind.strip().lower()
        if resolved_kind not in ALLOWED_KINDS:
            raise ValueError(f"Unsupported Dataset kind: {resolved_kind}")
        resolved_name = name.strip()
        if not resolved_name:
            raise ValueError("Dataset name cannot be empty")
        fields = self.business.store.list_fields(collection.id)
        canonical_spec = self._normalize_spec(resolved_kind, source_spec, fields)
        schema, data = self._compute(resolved_kind, collection.id, canonical_spec, fields)
        dataset = self.store.create(
            workspace_id=workspace_id,
            name=resolved_name,
            kind=resolved_kind,
            description=description.strip(),
            source_collection_id=collection.id,
            source_spec=canonical_spec,
            schema=schema,
            data=data,
            now=self._clock(),
        )
        self._publish_dataset(
            "dataset.created", dataset, session_id=session_id, turn_id=turn_id,
        )
        return dataset

    def require(self, dataset_id: str, *, refresh_stale: bool = True) -> Dataset:
        dataset = self.store.get(dataset_id.strip())
        if dataset is None:
            raise KeyError(dataset_id)
        if refresh_stale and dataset.status == "stale":
            return self.recompute(dataset.id, expected_revision=dataset.revision, publish=False)
        return dataset

    def recompute(
        self,
        dataset_id: str,
        *,
        expected_revision: int | None = None,
        publish: bool = True,
        session_id: str = "",
        turn_id: str = "",
    ) -> Dataset:
        current = self.store.get(dataset_id.strip())
        if current is None:
            raise KeyError(dataset_id)
        if expected_revision is not None and expected_revision != current.revision:
            from .models import WorkspaceConflictError
            raise WorkspaceConflictError(
                f"Dataset revision changed: expected {expected_revision}, current {current.revision}",
            )
        fields = self.business.store.list_fields(current.source_collection_id)
        schema, data = self._compute(
            current.kind, current.source_collection_id, current.source_spec, fields,
        )
        updated = self.store.update_result(
            current.id,
            schema=schema,
            data=data,
            expected_revision=current.revision,
            now=self._clock(),
        )
        if publish:
            self._publish_dataset(
                "dataset.updated", updated,
                session_id=session_id, turn_id=turn_id,
            )
        return updated

    def invalidate_collection(self, collection_id: str, *, reason: str) -> list[str]:
        return self.store.invalidate_collection(
            collection_id, reason=reason, now=self._clock(),
        )

    def list_for_workspace(
        self, workspace_id: str, *, refresh_stale: bool = False,
    ) -> list[Dataset]:
        datasets = self.store.list_for_workspace(workspace_id)
        if not refresh_stale:
            return datasets
        return [self.require(item.id, refresh_stale=True) for item in datasets]

    def present_data(
        self,
        workspace_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve internal reference IDs for human-facing Dataset projections.

        Dataset results deliberately retain stable record IDs so recomputation and
        joins do not depend on mutable names.  A Surface is a presentation layer,
        however, and must never make people interpret those internal IDs.
        """
        presented = copy.deepcopy(data)
        columns = presented.get("columns")
        rows = presented.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            return presented
        reference_keys = {
            str(column.get("key") or "")
            for column in columns
            if isinstance(column, dict)
            and str(column.get("data_type") or "") == "reference"
            and str(column.get("key") or "")
        }
        if not reference_keys:
            return presented
        labels: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in reference_keys:
                value = row.get(key)
                if not isinstance(value, str) or not value:
                    continue
                if value not in labels:
                    labels[value] = self.business.resolve_reference_value(
                        workspace_id,
                        value,
                    )
                row[key] = labels[value]
        return presented

    @staticmethod
    def snapshot(dataset: Dataset) -> dict[str, Any]:
        return {
            "id": dataset.id, "workspace_id": dataset.workspace_id,
            "name": dataset.name, "kind": dataset.kind,
            "description": dataset.description,
            "source_collection_id": dataset.source_collection_id,
            "source_spec": dataset.source_spec, "schema": dataset.schema,
            "data": dataset.data, "status": dataset.status,
            "revision": dataset.revision, "created_at": dataset.created_at,
            "updated_at": dataset.updated_at, "computed_at": dataset.computed_at,
            "invalidated_at": dataset.invalidated_at,
            "invalidation_reason": dataset.invalidation_reason,
        }

    def _compute(
        self,
        kind: str,
        collection_id: str,
        spec: dict[str, Any],
        fields: list[FieldDefinition],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        filters = dict(spec.get("filters") or {})
        records = self.business.store.query_records(
            collection_id, filters=filters, limit=None,
        )
        by_id = {field.id: field for field in fields}
        if kind == "metric_set":
            metrics = [
                self._metric(metric, records, by_id)
                for metric in spec["metrics"]
            ]
            return (
                {"kind": kind, "metrics": [
                    {key: value for key, value in item.items() if key != "value"}
                    for item in metrics
                ]},
                {"metrics": metrics},
            )
        if kind == "time_series":
            date_field = spec["date_field_id"]
            interval = spec["interval"]
            grouped: dict[str, list[BusinessRecord]] = defaultdict(list)
            for record in records:
                raw = record.values.get(date_field)
                if not isinstance(raw, str):
                    continue
                try:
                    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        parsed = dt.datetime.combine(dt.date.fromisoformat(raw), dt.time())
                    except ValueError:
                        continue
                period = parsed.strftime("%Y-%m" if interval == "month" else "%Y-%m-%d")
                grouped[period].append(record)
            metric_spec = {
                "key": "value", "label": spec.get("label") or "Value",
                "operation": spec["operation"],
                "field_id": spec.get("value_field_id", ""),
            }
            points = [
                {"period": period, "value": self._metric(metric_spec, group, by_id)["value"]}
                for period, group in sorted(grouped.items())
            ]
            return (
                {"kind": kind, "interval": interval, "columns": [
                    {"key": "period", "label": "Period", "data_type": "date"},
                    {"key": "value", "label": str(metric_spec["label"]), "data_type": "number"},
                ]},
                {"points": points},
            )
        dimensions = list(spec.get("dimension_field_ids") or [])
        metrics_spec = list(spec.get("metrics") or [])
        if dimensions or metrics_spec:
            grouped_records: dict[tuple[Any, ...], list[BusinessRecord]] = defaultdict(list)
            for record in records:
                grouped_records[tuple(record.values.get(field_id) for field_id in dimensions)].append(record)
            rows = []
            for dimension_values, group in grouped_records.items():
                row = {
                    by_id[field_id].name: value
                    for field_id, value in zip(dimensions, dimension_values)
                }
                for metric in metrics_spec:
                    result = self._metric(metric, group, by_id)
                    row[str(metric["key"])] = result["value"]
                rows.append(row)
            columns = [
                {"key": by_id[field_id].name, "label": by_id[field_id].label, "data_type": by_id[field_id].data_type}
                for field_id in dimensions
            ] + [
                {"key": str(metric["key"]), "label": str(metric["label"]), "data_type": "number"}
                for metric in metrics_spec
            ]
            return {"kind": kind, "columns": columns}, {"columns": columns, "rows": rows}
        selected = list(spec.get("field_ids") or [field.id for field in fields])
        columns = [
            {"key": by_id[field_id].name, "label": by_id[field_id].label, "data_type": by_id[field_id].data_type}
            for field_id in selected
        ]
        rows = [
            {by_id[field_id].name: record.values.get(field_id) for field_id in selected}
            for record in records
        ]
        return {"kind": kind, "columns": columns}, {"columns": columns, "rows": rows}

    @staticmethod
    def _metric(
        spec: dict[str, Any],
        records: list[BusinessRecord],
        by_id: dict[str, FieldDefinition],
    ) -> dict[str, Any]:
        operation = str(spec["operation"])
        field_id = str(spec.get("field_id") or "")
        if operation == "count":
            value: int | float = len(records)
        elif operation == "distinct_count":
            value = len({
                json.dumps(
                    record.values.get(field_id),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                for record in records
                if record.values.get(field_id) is not None
            })
        else:
            values = [
                float(record.values[field_id])
                for record in records
                if isinstance(record.values.get(field_id), (int, float))
                and not isinstance(record.values.get(field_id), bool)
            ]
            if not values:
                value = 0
            elif operation == "sum":
                value = sum(values)
            elif operation == "average":
                value = sum(values) / len(values)
            elif operation == "minimum":
                value = min(values)
            else:
                value = max(values)
        return {
            "key": str(spec["key"]), "label": str(spec["label"]),
            "operation": operation,
            "field": by_id[field_id].name if field_id in by_id else "",
            "value": value,
            "unit": str(spec.get("unit") or ""),
        }

    def _normalize_spec(
        self,
        kind: str,
        source_spec: dict[str, Any],
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        if not isinstance(source_spec, dict):
            raise ValueError("Dataset source_spec must be an object")
        lookup = self.business.schema.field_index(fields)
        filters = self.business._normalize_filters(
            dict(source_spec.get("filters") or {}), fields,
        )
        result: dict[str, Any] = {"filters": filters}
        if kind == "metric_set":
            result["metrics"] = self._normalize_metrics(source_spec.get("metrics"), lookup)
            return result
        if kind == "time_series":
            result["date_field_id"] = self._resolve_field(
                source_spec.get("date_field"), lookup,
            ).id
            result["interval"] = str(source_spec.get("interval") or "day").lower()
            if result["interval"] not in {"day", "month"}:
                raise ValueError("Time series interval must be day or month")
            operation = str(source_spec.get("operation") or "count").lower()
            if operation not in ALLOWED_OPERATIONS:
                raise ValueError(f"Unsupported aggregation: {operation}")
            result["operation"] = operation
            result["label"] = str(source_spec.get("label") or "Value")
            if operation != "count":
                result["value_field_id"] = self._resolve_field(
                    source_spec.get("value_field"), lookup,
                ).id
            return result
        fields_value = source_spec.get("fields") or []
        result["field_ids"] = [
            self._resolve_field(value, lookup).id for value in fields_value
        ]
        dimensions = source_spec.get("dimensions") or []
        result["dimension_field_ids"] = [
            self._resolve_field(value, lookup).id for value in dimensions
        ]
        table_metrics = source_spec.get("metrics") or []
        result["metrics"] = (
            self._normalize_metrics(table_metrics, lookup) if table_metrics else []
        )
        return result

    def _normalize_metrics(
        self,
        metrics: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
    ) -> list[dict[str, Any]]:
        if not isinstance(metrics, list) or not metrics:
            raise ValueError("Dataset requires at least one metric")
        result = []
        seen: set[str] = set()
        for metric in metrics:
            if not isinstance(metric, dict):
                raise ValueError("Metric must be an object")
            key = str(metric.get("key") or "").strip()
            label = str(metric.get("label") or key).strip()
            operation = str(metric.get("operation") or "").strip().lower()
            if not key or key in seen:
                raise ValueError("Metric keys must be non-empty and unique")
            if operation not in ALLOWED_OPERATIONS:
                raise ValueError(f"Unsupported aggregation: {operation}")
            item = {"key": key, "label": label, "operation": operation}
            if operation != "count":
                item["field_id"] = self._resolve_field(
                    metric.get("field"), lookup,
                ).id
            if metric.get("unit"):
                item["unit"] = str(metric["unit"])
            result.append(item)
            seen.add(key)
        return result

    def _resolve_field(
        self,
        value: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
    ) -> FieldDefinition:
        matches = lookup.get(self.business.schema.identity_key(value), ())
        if not matches:
            raise ValueError(f"Unknown Collection field: {value}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous Collection field: {value}")
        return matches[0]

    def _publish_dataset(
        self,
        event: str,
        dataset: Dataset,
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        self.business._publish_to_workspace(
            event, dataset.workspace_id, self.snapshot(dataset),
            session_id=session_id, turn_id=turn_id,
        )
