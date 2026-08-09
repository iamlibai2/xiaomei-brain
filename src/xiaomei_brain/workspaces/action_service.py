"""Crystallize repeated business changes without turning them into workflows."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .action_store import BusinessActionStore
from .business_service import BusinessWorldService
from .context_service import WorkspaceContextService
from .models import (
    BusinessActionDefinition,
    BusinessActionRun,
    BusinessEvent,
    BusinessRecord,
    RecordChange,
)
from .store import WorkspaceStore

PublishCallback = Callable[..., Any]


class BusinessActionService:
    """Stable business meanings plus an auditable record of each attempt."""

    def __init__(
        self,
        store: BusinessActionStore,
        business: BusinessWorldService,
        workspace_store: WorkspaceStore,
        context: WorkspaceContextService,
        *,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.business = business
        self.workspace_store = workspace_store
        self.context = context
        self._publish = publish
        self._clock = clock

    def establish(
        self,
        workspace_id: str,
        *,
        candidate_id: str,
        name: str,
        description: str,
        completion_criteria: str,
        person_id: str,
        session_id: str = "",
        turn_id: str = "",
    ) -> BusinessActionDefinition:
        resolved_name = name.strip()
        if not resolved_name:
            raise ValueError("Business Action name cannot be empty")
        existing = self.store.get_by_candidate(workspace_id, candidate_id.strip())
        if existing is not None:
            if self.store.get_validation(existing.id) is None:
                self.validate_candidate(workspace_id, candidate_id)
            return existing
        candidate = next((
            item for item in self.business.store.list_action_candidates(
                workspace_id,
                min_occurrences=3,
            )
            if item.id == candidate_id.strip()
        ), None)
        if candidate is None or candidate.status != "candidate":
            raise ValueError("Business Action candidate is not established enough")
        validation = self.validate_candidate(workspace_id, candidate.id)
        if validation["status"] != "passed":
            raise ValueError(
                "Business Action candidate failed historical validation: "
                + "; ".join(validation["reasons"])
            )
        definition = self.store.create_definition(
            workspace_id=workspace_id,
            collection_id=candidate.collection_id,
            source_candidate_id=candidate.id,
            name=resolved_name,
            description=description.strip(),
            operation=candidate.operation,
            field_ids=candidate.field_ids,
            completion_criteria=completion_criteria.strip(),
            evidence_count=candidate.occurrence_count,
            validation=validation,
            created_by_person_id=person_id.strip(),
            now=self._clock(),
        )
        self._publish_to_workspace(
            "business_action.established",
            definition.workspace_id,
            self.definition_snapshot(definition),
            session_id=session_id,
            turn_id=turn_id,
        )
        return definition

    def validate_candidate(
        self,
        workspace_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        """Verify recorded successful changes without executing them again."""
        candidate = next((
            item for item in self.business.store.list_action_candidates(
                workspace_id,
                min_occurrences=1,
            )
            if item.id == candidate_id.strip()
        ), None)
        if candidate is None:
            raise KeyError(candidate_id)
        evidence = self.business.store.list_action_occurrence_evidence(
            workspace_id,
            candidate.id,
        )
        existing = self.store.get_by_candidate(workspace_id, candidate.id)
        establishment_cutoff = (
            existing.created_at if existing is not None else float("inf")
        )
        action_run_change_ids = {
            change_id
            for run in (
                self.store.list_runs(workspace_id, limit=200)
                if existing is not None else []
            )
            if run.action_id == existing.id
            for change_id in run.record_change_ids
        }
        reasons: list[str] = []
        valid_evidence: list[dict[str, Any]] = []
        expected_fields = set(candidate.field_ids)
        expected_operation = candidate.operation
        valid_occurrence_keys: set[str] = set()
        for occurrence in evidence:
            changes = occurrence.get("changes", [])
            actual_fields = {
                str(change.get("field_id", ""))
                for change in changes
                if str(change.get("field_id", ""))
            }
            operations = {
                str(change.get("operation", ""))
                for change in changes
            }
            changed = bool(changes) and all(
                change.get("before") != change.get("after")
                for change in changes
            )
            valid = (
                bool(occurrence.get("business_intent", "").strip())
                and bool(str(occurrence.get("turn_id", "")).strip())
                and actual_fields == expected_fields
                and operations == {expected_operation}
                and changed
            )
            case = {
                "occurrence_key": occurrence["occurrence_key"],
                "record_id": occurrence["record_id"],
                "business_intent": occurrence["business_intent"],
                "session_id": occurrence["session_id"],
                "turn_id": occurrence["turn_id"],
                "observed_at": occurrence["observed_at"],
                "phase": (
                    "subsequent_confirmation"
                    if any(
                        str(change.get("id", "")) in action_run_change_ids
                        for change in changes
                    ) or float(occurrence["observed_at"]) > establishment_cutoff
                    else "establishment_evidence"
                ),
                "field_ids": sorted(actual_fields),
                "change_ids": [
                    str(change.get("id", "")) for change in changes
                ],
                "valid": valid,
            }
            valid_evidence.append(case)
            if valid:
                valid_occurrence_keys.add(str(occurrence["occurrence_key"]))
            else:
                reasons.append(
                    "Historical occurrence does not match the declared business effect: "
                    + str(occurrence["occurrence_key"])
                )
        occurrence_count = len({
            str(item.get("occurrence_key", "")) for item in evidence
        })
        record_count = len({str(item.get("record_id", "")) for item in evidence})
        establishment_keys = {
            item["occurrence_key"]
            for item in valid_evidence
            if item["phase"] == "establishment_evidence"
        }
        subsequent_keys = {
            item["occurrence_key"]
            for item in valid_evidence
            if item["phase"] == "subsequent_confirmation"
        }
        if occurrence_count < 3:
            reasons.append("At least three independent historical Turns are required")
        if record_count < 2:
            reasons.append("Historical evidence must cover at least two business records")
        if len(valid_occurrence_keys) != occurrence_count:
            reasons.append("Not every historical occurrence matches the candidate")
        report = {
            "candidate_id": candidate.id,
            "status": "passed" if not reasons else "failed",
            "occurrence_count": occurrence_count,
            "record_count": record_count,
            "checked_occurrence_count": len(valid_occurrence_keys),
            "establishment_occurrence_count": len(establishment_keys),
            "subsequent_occurrence_count": len(subsequent_keys),
            "reasons": list(dict.fromkeys(reasons)),
            "evidence": valid_evidence,
            "validated_at": self._clock(),
        }
        if existing is not None:
            self.store.save_validation(existing.id, candidate.id, report)
        return report

    def require(self, action_id: str) -> BusinessActionDefinition:
        definition = self.store.get_definition(action_id.strip())
        if definition is None:
            raise KeyError(action_id)
        return definition

    def execute(
        self,
        action_id: str,
        *,
        values: dict[str, Any],
        business_intent: str,
        person_id: str,
        record_id: str = "",
        stable_key: str = "",
        expected_revision: int | None = None,
        observation_id: str = "",
        event_type: str = "",
        event_summary: str = "",
        event_occurred_at: float | None = None,
        event_idempotency_key: str = "",
        event_metadata: dict[str, Any] | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[
        BusinessActionRun,
        BusinessRecord,
        list[RecordChange],
        BusinessEvent | None,
    ]:
        definition = self.require(action_id)
        if definition.status != "active":
            raise ValueError("Business Action is not active")
        fields = self.business.store.list_fields(definition.collection_id)
        normalized = self.business._normalize_record_values(values, fields)
        outside_definition = set(normalized) - set(definition.field_ids)
        if outside_definition:
            labels = [
                field.label for field in fields if field.id in outside_definition
            ]
            raise ValueError(
                "Business Action cannot change fields outside its definition: "
                + ", ".join(labels),
            )
        current_record = None
        if record_id.strip():
            current_record = self.business.store.get_record(record_id.strip())
        elif stable_key.strip():
            current_record = self.business.store.find_record_by_key(
                definition.collection_id,
                stable_key.strip(),
            )
        if (
            current_record is not None
            and current_record.collection_id != definition.collection_id
        ):
            raise ValueError("Record does not belong to the Business Action collection")
        if current_record is not None and not any(
            current_record.values.get(field_id) != value
            for field_id, value in normalized.items()
        ):
            raise ValueError("Business Action would not change the current business state")
        context_snapshot = self.context.build_action_snapshot(
            definition.workspace_id,
            person_id=person_id,
            record_id=current_record.id if current_record is not None else "",
        )
        run = self.store.start_run(
            definition,
            business_intent=business_intent.strip(),
            input_values=normalized,
            person_id=person_id.strip(),
            session_id=session_id,
            turn_id=turn_id,
            observation_id=observation_id.strip(),
            context_snapshot=context_snapshot,
            now=self._clock(),
        )
        try:
            record, changes, event = self.business.upsert_record(
                definition.collection_id,
                values=normalized,
                record_id=record_id,
                stable_key=stable_key,
                expected_revision=expected_revision,
                business_intent=business_intent,
                person_id=person_id,
                session_id=session_id,
                turn_id=turn_id,
                observation_id=observation_id,
                event_type=event_type,
                event_summary=event_summary,
                event_occurred_at=event_occurred_at,
                event_idempotency_key=event_idempotency_key,
                event_metadata=event_metadata,
            )
        except Exception as exc:
            failed = self.store.finish_run(
                run.id,
                status="failed",
                error=str(exc),
                now=self._clock(),
            )
            self._publish_to_workspace(
                "business_action.failed",
                definition.workspace_id,
                self.run_snapshot(failed),
                session_id=session_id,
                turn_id=turn_id,
            )
            raise
        completed = self.store.finish_run(
            run.id,
            status="completed",
            record_id=record.id,
            record_change_ids=tuple(change.id for change in changes),
            event_id=event.id if event is not None else "",
            now=self._clock(),
        )
        self._publish_to_workspace(
            "business_action.completed",
            definition.workspace_id,
            self.run_snapshot(completed),
            session_id=session_id,
            turn_id=turn_id,
        )
        return completed, record, changes, event

    def definition_snapshot(self, item: BusinessActionDefinition) -> dict[str, Any]:
        collection = self.business.require_collection(item.collection_id)
        field_map = {
            field.id: field
            for field in self.business.store.list_fields(item.collection_id)
        }
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "collection_id": item.collection_id,
            "source_candidate_id": item.source_candidate_id,
            "name": item.name,
            "description": item.description,
            "operation": item.operation,
            "field_ids": list(item.field_ids),
            "fields": [
                {
                    "id": field_id,
                    "name": field_map[field_id].name,
                    "label": field_map[field_id].label,
                }
                for field_id in item.field_ids
                if field_id in field_map
            ],
            "collection_name": collection.name,
            "collection_label": collection.label,
            "completion_criteria": item.completion_criteria,
            "status": item.status,
            "evidence_count": item.evidence_count,
            "revision": item.revision,
            "created_by_person_id": item.created_by_person_id,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "validation": self.store.get_validation(item.id),
        }

    @staticmethod
    def run_snapshot(item: BusinessActionRun) -> dict[str, Any]:
        return {
            "id": item.id,
            "action_id": item.action_id,
            "workspace_id": item.workspace_id,
            "collection_id": item.collection_id,
            "record_id": item.record_id,
            "status": item.status,
            "business_intent": item.business_intent,
            "input_values": item.input_values,
            "record_change_ids": list(item.record_change_ids),
            "event_id": item.event_id,
            "error": item.error,
            "person_id": item.person_id,
            "session_id": item.session_id,
            "turn_id": item.turn_id,
            "observation_id": item.observation_id,
            "context_snapshot": item.context_snapshot,
            "started_at": item.started_at,
            "completed_at": item.completed_at,
        }

    def workspace_snapshot(self, workspace_id: str) -> dict[str, Any]:
        return {
            "actions": [
                self.definition_snapshot(item)
                for item in self.store.list_definitions(workspace_id)
            ],
            "action_runs": [
                self.run_snapshot(item)
                for item in self.store.list_runs(workspace_id, limit=50)
            ],
        }

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
