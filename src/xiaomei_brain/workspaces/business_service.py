"""Reliable services for a Workspace's evolving business facts."""

from __future__ import annotations

import datetime as dt
import math
import re
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from .business_store import BusinessStore
from .schema_resolver import SchemaResolver
from .models import (
    BusinessActionCandidate,
    BusinessEvent,
    BusinessRecord,
    CollectionDefinition,
    DataSource,
    FieldDefinition,
    Observation,
    RecordChange,
)
from .store import WorkspaceStore

PublishCallback = Callable[..., Any]

ALLOWED_SOURCE_KINDS = frozenset({
    "conversation", "file", "channel", "email", "manual", "external_api",
    "import",
})
ALLOWED_FIELD_TYPES = frozenset({
    "text", "integer", "number", "boolean", "date", "datetime", "money",
    "enum", "reference", "json",
})
ALLOWED_MATURITY = frozenset({"provisional", "candidate", "established"})

_NUMERIC_TEXT_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?$",
)


class BusinessWorldService:
    """Facade over business sources, observations and current facts."""

    def __init__(
        self,
        store: BusinessStore,
        workspace_store: WorkspaceStore,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.workspace_store = workspace_store
        self._publish = publish
        self._clock = clock
        self._on_collection_changed: Callable[..., Any] | None = None
        self._context_executor: Callable[..., Any] | None = None
        self.schema = SchemaResolver(store)

    def set_context_executor(self, executor: Callable[..., Any] | None) -> None:
        """Attach the Context rule boundary without coupling the two services."""
        self._context_executor = executor

    def create_data_source(
        self,
        workspace_id: str,
        *,
        kind: str,
        name: str,
        locator: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> DataSource:
        self._require_workspace(workspace_id)
        resolved_kind = kind.strip().lower()
        if resolved_kind not in ALLOWED_SOURCE_KINDS:
            raise ValueError(f"Unsupported data source kind: {resolved_kind}")
        resolved_name = name.strip()
        if not resolved_name:
            raise ValueError("Data source name cannot be empty")
        source = self.store.create_data_source(
            workspace_id,
            kind=resolved_kind,
            name=resolved_name,
            locator=locator.strip(),
            now=self._clock(),
        )
        self._publish_to_workspace(
            "data_source.created", workspace_id, self.data_source_snapshot(source),
            session_id=session_id, turn_id=turn_id,
        )
        return source

    def observe(
        self,
        workspace_id: str,
        *,
        content: str,
        data_source_id: str = "",
        source_person_id: str = "",
        external_ref: str = "",
        attributes: dict[str, Any] | None = None,
        asset_id: str = "",
        occurred_at: float | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Observation:
        self._require_workspace(workspace_id)
        if data_source_id:
            source = self.store.get_data_source(data_source_id)
            if source is None or source.workspace_id != workspace_id:
                raise ValueError("Data source does not belong to the Workspace")
            if external_ref.strip():
                existing = self.store.find_observation(
                    data_source_id,
                    external_ref.strip(),
                )
                if existing is not None:
                    return existing
        resolved_content = content.strip()
        if not resolved_content and not asset_id.strip() and not attributes:
            raise ValueError("Observation requires content, attributes or an Asset")
        observation = self.store.create_observation(
            workspace_id,
            data_source_id=data_source_id.strip(),
            source_person_id=source_person_id.strip(),
            external_ref=external_ref.strip(),
            content=resolved_content,
            attributes=dict(attributes or {}),
            asset_id=asset_id.strip(),
            session_id=session_id.strip(),
            turn_id=turn_id.strip(),
            occurred_at=occurred_at,
            now=self._clock(),
        )
        self._publish_to_workspace(
            "observation.created", workspace_id,
            self.observation_snapshot(observation),
            session_id=session_id, turn_id=turn_id,
        )
        return observation

    def attach_observation_asset(
        self,
        workspace_id: str,
        *,
        observation_id: str,
        asset_id: str,
        attribute_updates: dict[str, Any] | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> Observation:
        """Backfill the durable Asset created for an existing Observation."""
        self._require_workspace(workspace_id)
        current = self.store.get_observation(observation_id.strip())
        if current is None:
            raise KeyError(observation_id)
        if current.workspace_id != workspace_id:
            raise ValueError("Observation does not belong to the Workspace")
        updated, changed = self.store.attach_asset_to_observation(
            current.id,
            asset_id,
            attribute_updates=attribute_updates,
        )
        if changed:
            self._publish_to_workspace(
                "observation.updated",
                workspace_id,
                self.observation_snapshot_with_links(updated),
                session_id=session_id,
                turn_id=turn_id,
            )
        return updated

    def create_collection(
        self,
        workspace_id: str,
        *,
        name: str,
        label: str,
        purpose: str,
        fields: list[dict[str, Any]],
        maturity: str = "candidate",
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[CollectionDefinition, list[FieldDefinition]]:
        self._require_workspace(workspace_id)
        normalized_fields = self._normalize_fields(fields)
        resolved_name = name.strip()
        resolved_label = label.strip()
        resolved_maturity = maturity.strip().lower()
        if not resolved_name or not resolved_label:
            raise ValueError("Collection name and label cannot be empty")
        if resolved_maturity not in ALLOWED_MATURITY:
            raise ValueError(f"Unsupported collection maturity: {resolved_maturity}")
        existing = self.schema.resolve_collection_identity(
            workspace_id,
            name=resolved_name,
            label=resolved_label,
        )
        if existing is not None:
            current_fields = self.store.list_fields(existing.id)
            plan = self.schema.plan_field_evolution(
                current_fields,
                normalized_fields,
            )
            self._validate_required_additions(existing, list(plan.additions))
            if plan.changed:
                existing, current_fields = self.store.add_collection_fields(
                    existing.id,
                    fields=list(plan.additions),
                    alias_updates=plan.alias_updates,
                    expected_revision=existing.revision,
                    now=self._clock(),
                )
                payload = self.collection_snapshot(existing, current_fields)
                payload["schema_resolution"] = {
                    "outcome": "reused_and_evolved",
                    "added_field_count": len(plan.additions),
                    "reused_field_ids": [item.id for item in plan.reused],
                    "updated_alias_field_ids": list(plan.alias_updates),
                }
                self._publish_to_workspace(
                    "collection.updated", workspace_id, payload,
                    session_id=session_id, turn_id=turn_id,
                )
            return existing, current_fields
        collection, definitions = self.store.create_collection(
            workspace_id,
            name=resolved_name,
            label=resolved_label,
            purpose=purpose.strip(),
            maturity=resolved_maturity,
            fields=normalized_fields,
            now=self._clock(),
        )
        payload = self.collection_snapshot(collection, definitions)
        self._publish_to_workspace(
            "collection.created", workspace_id, payload,
            session_id=session_id, turn_id=turn_id,
        )
        return collection, definitions

    def upsert_record(
        self,
        collection_id: str,
        *,
        values: dict[str, Any],
        record_id: str = "",
        stable_key: str = "",
        expected_revision: int | None = None,
        business_intent: str,
        person_id: str = "",
        session_id: str = "",
        turn_id: str = "",
        observation_id: str = "",
        event_type: str = "",
        event_summary: str = "",
        event_occurred_at: float | None = None,
        event_idempotency_key: str = "",
        event_metadata: dict[str, Any] | None = None,
        notify: bool = True,
    ) -> tuple[BusinessRecord, list[RecordChange], BusinessEvent | None]:
        collection = self.require_collection(collection_id)
        fields = self.store.list_fields(collection.id)
        normalized = self._normalize_record_values(values, fields)
        current = None
        if record_id.strip():
            current = self.store.get_record(record_id.strip())
            if current is None:
                raise KeyError(record_id)
        elif stable_key.strip():
            current = self.store.find_record_by_key(collection.id, stable_key.strip())
        if current is not None:
            if current.collection_id != collection.id:
                raise ValueError("Record does not belong to the collection")
            if expected_revision is None:
                raise ValueError(
                    "expected_revision is required when updating an existing record",
                )
            record_id = current.id
            resolved_key = stable_key.strip() or current.stable_key
        else:
            record_id = ""
            resolved_key = stable_key.strip()
        change_metadata: dict[str, dict[str, Any]] = {}
        if self._context_executor is not None:
            normalized, change_metadata = self._context_executor(
                collection,
                normalized,
                current,
                person_id,
            )
        if current is None:
            missing = [
                field.label for field in fields
                if field.required and field.id not in normalized
            ]
            if missing:
                raise ValueError(f"Missing required fields: {', '.join(missing)}")
        resolved_summary = event_summary.strip()
        resolved_type = event_type.strip()
        if bool(resolved_summary) != bool(resolved_type):
            raise ValueError("Business Event requires both event_type and event_summary")
        if observation_id:
            observation = self.store.get_observation(observation_id)
            if observation is None or observation.workspace_id != collection.workspace_id:
                raise ValueError("Observation does not belong to the Workspace")
        record, changes, event = self.store.write_record(
            workspace_id=collection.workspace_id,
            collection_id=collection.id,
            record_id=record_id,
            stable_key=resolved_key,
            values=normalized,
            expected_revision=expected_revision,
            business_intent=business_intent.strip(),
            person_id=person_id.strip(),
            session_id=session_id,
            turn_id=turn_id,
            observation_id=observation_id.strip(),
            event_type=resolved_type,
            event_summary=resolved_summary,
            event_occurred_at=event_occurred_at,
            event_idempotency_key=event_idempotency_key.strip(),
            event_metadata=dict(event_metadata or {}),
            change_metadata=change_metadata,
            now=self._clock(),
        )
        action_candidate_payload = None
        if notify and changes:
            observed = self.store.observe_action_occurrence(changes)
            if observed is not None:
                fingerprint, previous_count, current_count = observed
                if previous_count < 3 <= current_count:
                    candidate = next((
                        item for item in self.store.list_action_candidates(
                            collection.workspace_id,
                            min_occurrences=3,
                        )
                        if item.id.endswith(fingerprint[:24])
                    ), None)
                    if candidate is not None:
                        action_candidate_payload = self.action_candidate_snapshot(
                            candidate,
                        )
        if notify and self._on_collection_changed is not None:
            self._on_collection_changed(
                collection.id,
                reason=(
                    event.summary if event is not None
                    else business_intent.strip() or "Business record changed"
                ),
            )
        payload = {
            "record": self.record_snapshot(record, fields),
            "changes": [self.change_snapshot(item, fields) for item in changes],
            "event": self.event_snapshot(event) if event is not None else None,
        }
        if notify:
            self._publish_to_workspace(
                "record.changed", collection.workspace_id, payload,
                session_id=session_id, turn_id=turn_id,
            )
            if event is not None:
                self._publish_to_workspace(
                    "business_event.created", collection.workspace_id,
                    self.event_snapshot(event),
                    session_id=session_id, turn_id=turn_id,
                )
            if action_candidate_payload is not None:
                self._publish_to_workspace(
                    "business_action.candidate", collection.workspace_id,
                    action_candidate_payload,
                    session_id=session_id, turn_id=turn_id,
                )
        return record, changes, event

    def require_collection(self, collection_id: str) -> CollectionDefinition:
        collection = self.store.get_collection(collection_id.strip())
        if collection is None:
            raise KeyError(collection_id)
        return collection

    def add_collection_fields(
        self,
        collection_id: str,
        *,
        fields: list[dict[str, Any]],
        expected_revision: int,
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[CollectionDefinition, list[FieldDefinition]]:
        collection = self.require_collection(collection_id)
        if collection.revision != expected_revision:
            raise WorkspaceConflictError(
                "Collection revision changed: expected "
                f"{expected_revision}, current {collection.revision}"
            )
        normalized = self._normalize_fields(fields)
        existing = self.store.list_fields(collection.id)
        plan = self.schema.plan_field_evolution(existing, normalized)
        self._validate_required_additions(collection, list(plan.additions))
        if not plan.changed:
            return collection, existing
        updated, definitions = self.store.add_collection_fields(
            collection.id,
            fields=list(plan.additions),
            alias_updates=plan.alias_updates,
            expected_revision=expected_revision,
            now=self._clock(),
        )
        payload = self.collection_snapshot(updated, definitions)
        self._publish_to_workspace(
            "collection.updated", updated.workspace_id, payload,
            session_id=session_id, turn_id=turn_id,
        )
        return updated, definitions

    def query_records(
        self,
        collection_id: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        collection = self.require_collection(collection_id)
        fields = self.store.list_fields(collection.id)
        normalized_filters = self._normalize_filters(filters or {}, fields)
        records = self.store.query_records(
            collection.id, filters=normalized_filters, limit=limit,
        )
        return [self.record_snapshot(record, fields) for record in records]

    def workspace_snapshot(
        self,
        workspace_id: str,
        *,
        include_records: bool = False,
        record_limit: int = 50,
    ) -> dict[str, Any]:
        self._require_workspace(workspace_id)
        collections = []
        for collection in self.store.list_collections(workspace_id):
            fields = self.store.list_fields(collection.id)
            item = self.collection_snapshot(collection, fields)
            if include_records:
                item["records"] = [
                    self.record_snapshot(record, fields)
                    for record in self.store.list_records(
                        collection.id, limit=record_limit,
                    )
                ]
            collections.append(item)
        return {
            "summary": self.store.summary(workspace_id),
            "data_sources": [
                self.data_source_snapshot(item)
                for item in self.store.list_data_sources(workspace_id)
            ],
            "observations": [
                self.observation_snapshot_with_links(item)
                for item in self.store.list_observations(workspace_id, limit=100)
            ],
            "collections": collections,
            "events": [
                self.event_snapshot(item)
                for item in self.store.list_events(workspace_id, limit=100)
            ],
            "action_candidates": [
                self.action_candidate_snapshot(item)
                for item in self.store.list_action_candidates(
                    workspace_id,
                    min_occurrences=2,
                )
            ],
        }

    @staticmethod
    def data_source_snapshot(source: DataSource) -> dict[str, Any]:
        return {
            "id": source.id, "workspace_id": source.workspace_id,
            "kind": source.kind, "name": source.name, "locator": source.locator,
            "status": source.status, "created_at": source.created_at,
            "updated_at": source.updated_at,
        }

    @staticmethod
    def observation_snapshot(item: Observation) -> dict[str, Any]:
        return {
            "id": item.id, "workspace_id": item.workspace_id,
            "data_source_id": item.data_source_id,
            "source_person_id": item.source_person_id,
            "external_ref": item.external_ref, "content": item.content,
            "attributes": item.attributes, "asset_id": item.asset_id,
            "session_id": item.session_id, "turn_id": item.turn_id,
            "status": item.status, "occurred_at": item.occurred_at,
            "received_at": item.received_at,
            "resolved_collection_id": item.resolved_collection_id,
            "resolved_record_id": item.resolved_record_id,
        }

    def observation_snapshot_with_links(self, item: Observation) -> dict[str, Any]:
        payload = self.observation_snapshot(item)
        payload["resolved_record_ids"] = self.store.linked_record_ids(item.id)
        source = (
            self.store.get_data_source(item.data_source_id)
            if item.data_source_id else None
        )
        payload["data_source"] = (
            self.data_source_snapshot(source) if source is not None else None
        )
        return payload

    def action_candidate_snapshot(
        self,
        item: BusinessActionCandidate,
    ) -> dict[str, Any]:
        collection = self.require_collection(item.collection_id)
        field_map = {
            field.id: field for field in self.store.list_fields(item.collection_id)
        }
        fields = [
            {
                "id": field_id,
                "name": field_map[field_id].name,
                "label": field_map[field_id].label,
            }
            for field_id in item.field_ids
            if field_id in field_map
        ]
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "collection_id": item.collection_id,
            "collection_name": collection.name,
            "collection_label": collection.label,
            "operation": item.operation,
            "fields": fields,
            "occurrence_count": item.occurrence_count,
            "record_count": item.record_count,
            "example_intents": list(item.example_intents),
            "status": item.status,
            "first_seen_at": item.first_seen_at,
            "last_seen_at": item.last_seen_at,
        }

    def publish_import_completed(
        self,
        workspace_id: str,
        payload: dict[str, Any],
        *,
        collection_id: str,
        reason: str,
        session_id: str = "",
        turn_id: str = "",
    ) -> None:
        if self._on_collection_changed is not None:
            self._on_collection_changed(collection_id, reason=reason)
        self._publish_to_workspace(
            "data_import.completed", workspace_id, payload,
            session_id=session_id, turn_id=turn_id,
        )

    @staticmethod
    def collection_snapshot(
        collection: CollectionDefinition,
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        return {
            "id": collection.id, "workspace_id": collection.workspace_id,
            "name": collection.name, "label": collection.label,
            "purpose": collection.purpose, "maturity": collection.maturity,
            "status": collection.status, "revision": collection.revision,
            "created_at": collection.created_at, "updated_at": collection.updated_at,
            "fields": [
                {
                    "id": field.id, "name": field.name, "label": field.label,
                    "data_type": field.data_type, "required": field.required,
                    "aliases": list(field.aliases), "status": field.status,
                    "revision": field.revision,
                }
                for field in fields
            ],
        }

    def record_snapshot(
        self,
        record: BusinessRecord,
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        by_id = {field.id: field for field in fields}
        values = {
            by_id[field_id].name if field_id in by_id else field_id: value
            for field_id, value in record.values.items()
        }
        display_values = {
            by_id[field_id].name if field_id in by_id else field_id: (
                self.resolve_reference_value(record.workspace_id, value)
                if field_id in by_id and by_id[field_id].data_type == "reference"
                else value
            )
            for field_id, value in record.values.items()
        }
        return {
            "id": record.id, "workspace_id": record.workspace_id,
            "collection_id": record.collection_id, "stable_key": record.stable_key,
            "values": values, "display_values": display_values,
            "values_by_field_id": record.values,
            "status": record.status, "revision": record.revision,
            "created_at": record.created_at, "updated_at": record.updated_at,
        }

    def resolve_reference_value(self, workspace_id: str, value: Any) -> Any:
        """Project a stable record reference as a human-readable business label."""
        if not isinstance(value, str) or not value:
            return value
        record = self.store.get_record(value)
        if record is None or record.workspace_id != workspace_id:
            return value
        fields = self.store.list_fields(record.collection_id)
        ranked_fields = sorted(
            enumerate(fields),
            key=lambda item: self._display_field_priority(item[1], item[0]),
        )
        for _index, field in ranked_fields:
            candidate = record.values.get(field.id)
            if (
                isinstance(candidate, str)
                and candidate.strip()
                and not candidate.startswith("record_")
            ):
                return candidate.strip()
        return record.stable_key or record.id

    @staticmethod
    def _display_field_priority(
        field: FieldDefinition,
        index: int,
    ) -> tuple[int, int]:
        name = field.name.casefold()
        label = field.label.casefold()
        if name in {"name", "title", "display_name", "code", "number"}:
            return (0, index)
        if name.endswith(("_name", "_title", "_code", "_number")):
            return (1, index)
        if any(token in label for token in ("名称", "姓名", "标题", "编号", "代码")):
            return (2, index)
        if field.required and field.data_type in {"text", "enum"}:
            return (3, index)
        if field.data_type in {"text", "enum"}:
            return (4, index)
        return (5, index)

    @staticmethod
    def change_snapshot(
        change: RecordChange,
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        field = next((item for item in fields if item.id == change.field_id), None)
        return {
            "id": change.id, "record_id": change.record_id,
            "operation": change.operation, "field_id": change.field_id,
            "field_name": field.name if field is not None else change.field_id,
            "before": change.before_value, "after": change.after_value,
            "business_intent": change.business_intent,
            "person_id": change.person_id, "session_id": change.session_id,
            "turn_id": change.turn_id, "observation_id": change.observation_id,
            "origin": change.origin, "context_id": change.context_id,
            "context_revision": change.context_revision,
            "reason": change.reason,
            "changed_at": change.changed_at,
        }

    @staticmethod
    def event_snapshot(event: BusinessEvent) -> dict[str, Any]:
        return {
            "id": event.id, "workspace_id": event.workspace_id,
            "event_type": event.event_type, "summary": event.summary,
            "collection_id": event.collection_id, "record_id": event.record_id,
            "person_id": event.person_id, "observation_id": event.observation_id,
            "record_change_ids": list(event.record_change_ids),
            "occurred_at": event.occurred_at, "recorded_at": event.recorded_at,
            "supersedes_event_id": event.supersedes_event_id,
            "idempotency_key": event.idempotency_key,
            "metadata": event.metadata,
        }

    def _require_workspace(self, workspace_id: str) -> None:
        if self.workspace_store.get(workspace_id.strip()) is None:
            raise KeyError(workspace_id)

    def _publish_to_workspace(
        self,
        event: str,
        workspace_id: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        turn_id: str,
    ) -> None:
        if self._publish is None:
            return
        for person_id in self.workspace_store.linked_person_ids(workspace_id):
            targeted = dict(payload)
            targeted["_target_person_id"] = person_id
            self._publish(event, targeted, session_id=session_id, turn_id=turn_id)

    def _normalize_fields(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not fields:
            raise ValueError("Collection requires at least one field")
        if len(fields) > 128:
            raise ValueError("Collection supports at most 128 fields")
        normalized = []
        identities: set[str] = set()
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                raise ValueError(f"Field {index + 1} must be an object")
            name = str(field.get("name") or "").strip()
            label = str(field.get("label") or name).strip()
            data_type = str(field.get("data_type") or "text").strip().lower()
            if not name or not label:
                raise ValueError("Field name and label cannot be empty")
            if data_type not in ALLOWED_FIELD_TYPES:
                raise ValueError(f"Unsupported field type: {data_type}")
            aliases = tuple(
                str(item).strip() for item in (field.get("aliases") or [])
                if str(item).strip()
            )
            # A machine name and its display label may intentionally be the
            # same (common for English spreadsheet headers). Treat that as one
            # identity while still rejecting collisions across fields.
            field_identities = list(dict.fromkeys(
                self.schema.identity_key(identity)
                for identity in (name, label, *aliases)
            ))
            for folded in field_identities:
                if folded in identities:
                    raise ValueError(f"Duplicate field name or alias: {folded}")
                identities.add(folded)
            normalized.append({
                "name": name, "label": label, "data_type": data_type,
                "required": bool(field.get("required", False)),
                "aliases": aliases,
            })
        return normalized

    def _normalize_record_values(
        self,
        values: dict[str, Any],
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        return self.schema.normalize_values(
            values,
            fields,
            validate=self._validate_value,
        )

    def _normalize_filters(
        self,
        filters: dict[str, Any],
        fields: list[FieldDefinition],
    ) -> dict[str, Any]:
        """Normalize a small typed filter grammar without exposing SQL."""
        if not isinstance(filters, dict):
            raise ValueError("Record filters must be an object")
        allowed = {"$eq", "$ne", "$in", "$not_in", "$gt", "$gte", "$lt", "$lte", "$is_null"}
        normalized: dict[str, Any] = {}
        for key, raw in filters.items():
            field = self.schema.resolve_field(fields, key)
            if field.id in normalized:
                raise ValueError(
                    f"Multiple filters resolve to the same field: {field.label}"
                )
            if not isinstance(raw, dict):
                normalized[field.id] = self._validate_value(field, raw)
                continue
            unknown = set(raw) - allowed
            if unknown:
                raise ValueError(f"Unsupported filter operator: {sorted(unknown)[0]}")
            if not raw:
                raise ValueError(f"Filter for {field.label} cannot be empty")
            operators: dict[str, Any] = {}
            for operator, operand in raw.items():
                if operator in {"$in", "$not_in"}:
                    if not isinstance(operand, list) or not operand:
                        raise ValueError(f"{operator} requires a non-empty array")
                    operators[operator] = [
                        self._validate_value(field, item) for item in operand
                    ]
                elif operator == "$is_null":
                    if not isinstance(operand, bool):
                        raise ValueError("$is_null requires true or false")
                    operators[operator] = operand
                else:
                    operators[operator] = self._validate_value(field, operand)
            normalized[field.id] = operators
        return normalized

    def _validate_required_additions(
        self,
        collection: CollectionDefinition,
        additions: list[dict[str, Any]],
    ) -> None:
        if any(field["required"] for field in additions):
            if self.store.list_records(collection.id, limit=1):
                raise ValueError(
                    "Cannot add a required field after records exist without a default value",
                )

    @staticmethod
    def _validate_value(field: FieldDefinition, value: Any) -> Any:
        if value is None:
            if field.required:
                raise ValueError(f"Field {field.label} is required")
            return None
        kind = field.data_type
        if kind == "integer":
            value = BusinessWorldService._coerce_numeric_text(
                value,
                integer=True,
            )
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Field {field.label} requires an integer")
        elif kind in {"number", "money"}:
            value = BusinessWorldService._coerce_numeric_text(value)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Field {field.label} requires a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"Field {field.label} requires a finite number")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"Field {field.label} requires true or false")
        elif kind == "date":
            if not isinstance(value, str):
                raise ValueError(f"Field {field.label} requires an ISO date")
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"Field {field.label} requires an ISO date") from exc
        elif kind == "datetime":
            if not isinstance(value, str):
                raise ValueError(f"Field {field.label} requires an ISO datetime")
            try:
                dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Field {field.label} requires an ISO datetime") from exc
        elif kind != "json" and not isinstance(value, str):
            raise ValueError(f"Field {field.label} requires text")
        return value

    @staticmethod
    def _coerce_numeric_text(value: Any, *, integer: bool = False) -> Any:
        """Convert an unambiguous JSON string number to its stored scalar type.

        Dynamic ``values`` keys cannot express each Collection field's schema
        in the static tool definition, and LLMs commonly emit ``"4800"`` for
        such values.  Keep coercion deliberately narrow: currency symbols,
        units, malformed thousands separators, blanks and booleans remain
        invalid instead of being guessed.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text or _NUMERIC_TEXT_PATTERN.fullmatch(text) is None:
            return value
        normalized = text.replace(",", "")
        try:
            parsed = Decimal(normalized)
            if not parsed.is_finite():
                return value
            if integer:
                if parsed == parsed.to_integral_value():
                    return int(parsed)
                return value
            if re.fullmatch(r"[+-]?\d+", normalized):
                return int(normalized)
            return float(parsed)
        except (InvalidOperation, OverflowError, ValueError):
            return value
