"""Safe executable projections of durable Workspace Context entries.

Context remains the business-facing source of truth.  This module only stores
and evaluates a deliberately small data grammar; it never executes arbitrary
Python, SQL or shell code.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .business_service import BusinessWorldService
from .context_store import WorkspaceContextStore
from .models import (
    BusinessRecord,
    CollectionDefinition,
    FieldDefinition,
    WorkspaceContextEntry,
    WorkspaceContextExecutable,
)

EXECUTABLE_CONTEXT_TYPES = frozenset({
    "default", "constraint", "decision", "calculation",
})
CONDITION_OPERATORS = frozenset({
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in",
    "is_empty", "not_empty",
})
EXPRESSION_OPERATORS = frozenset({
    "add", "subtract", "multiply", "divide", "round", "min", "max",
})


class WorkspaceContextExecutionService:
    """Compile Context definitions and apply them at the record-write boundary."""

    def __init__(
        self,
        store: WorkspaceContextStore,
        business: BusinessWorldService,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.business = business
        self._clock = clock

    def configure(
        self,
        context_id: str,
        specification: dict[str, Any],
        *,
        person_id: str,
        session_id: str = "",
        turn_id: str = "",
    ) -> WorkspaceContextExecutable:
        context = self.store.get(context_id.strip())
        if context is None:
            raise KeyError(context_id)
        if context.status not in {"established", "formal"}:
            raise ValueError("Only an active Workspace Context can be executable")
        if context.context_type not in EXECUTABLE_CONTEXT_TYPES:
            raise ValueError(
                "Only default, constraint, decision or calculation Context can execute"
            )
        if context.scope_type == "person" and context.scope_id != person_id.strip():
            raise PermissionError(
                "Person Context execution can only be configured by its Person"
            )
        normalized, read_ids, write_ids = self._compile_specification(
            context,
            specification,
        )
        timestamp = self._clock()
        previous = self.store.get_executable(context.id)
        if previous is not None:
            if (
                previous.status == "active"
                and previous.context_revision == context.revision
                and previous.specification == normalized
            ):
                return previous
            raise ValueError(
                "Context execution cannot be changed in place; correct the Context "
                "and attach the replacement execution definition"
            )
        executable = WorkspaceContextExecutable(
            context_id=context.id,
            workspace_id=context.workspace_id,
            collection_id=normalized["target_collection_id"],
            trigger="before_record_write",
            specification=normalized,
            read_field_ids=tuple(sorted(read_ids)),
            write_field_ids=tuple(sorted(write_ids)),
            status="active",
            context_revision=context.revision,
            created_at=timestamp,
            updated_at=timestamp,
        )
        candidates = [
            item
            for item in self._active_executables(
                context.workspace_id,
                executable.collection_id,
            )
            if item.context_id != executable.context_id
        ]
        candidates.append(executable)
        self._ordered(candidates)
        self.store.save_executable(executable)
        return executable

    def validate_specification(
        self,
        context: WorkspaceContextEntry,
        specification: dict[str, Any],
        *,
        replaces_context_id: str = "",
    ) -> None:
        """Validate syntax and business references before Context persistence."""
        if context.context_type not in EXECUTABLE_CONTEXT_TYPES:
            raise ValueError(
                "Only default, constraint, decision or calculation Context can execute"
            )
        normalized, read_ids, write_ids = self._compile_specification(
            context,
            specification,
        )
        candidate = WorkspaceContextExecutable(
            context_id=context.id,
            workspace_id=context.workspace_id,
            collection_id=normalized["target_collection_id"],
            trigger="before_record_write",
            specification=normalized,
            read_field_ids=tuple(sorted(read_ids)),
            write_field_ids=tuple(sorted(write_ids)),
            status="active",
            context_revision=context.revision,
            created_at=context.created_at,
            updated_at=context.updated_at,
        )
        candidates = [
            item
            for item in self._active_executables(
                context.workspace_id,
                candidate.collection_id,
            )
            if item.context_id not in {candidate.context_id, replaces_context_id}
        ]
        candidates.append(candidate)
        self._ordered(candidates)

    def apply_before_record_write(
        self,
        collection: CollectionDefinition,
        values: dict[str, Any],
        current: BusinessRecord | None,
        person_id: str,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """Return derived values plus per-field audit metadata."""
        active = self._applicable_executables(
            collection.workspace_id,
            collection.id,
            person_id=person_id.strip(),
            record_id=current.id if current is not None else "",
        )
        if not active:
            return values, {}
        fields = self.business.store.list_fields(collection.id)
        fields_by_id = {field.id: field for field in fields}
        working = dict(current.values if current is not None else {})
        working.update(values)
        result = dict(values)
        metadata: dict[str, dict[str, Any]] = {}
        applied_values: dict[str, tuple[Any, str]] = {}
        for executable in self._ordered(active):
            spec = executable.specification
            condition = spec.get("condition")
            if condition is not None and not self._condition_matches(condition, working):
                continue
            context = self.store.get(executable.context_id)
            if context is None:
                continue
            for effect in spec.get("effects", []):
                effect_type = effect["type"]
                if effect_type == "reject":
                    raise ValueError(effect["message"])
                field_id = effect["field_id"]
                if effect_type == "set_default" and not self._is_empty(
                    working.get(field_id)
                ):
                    continue
                computed = self._evaluate_expression(effect["value"], working)
                field = fields_by_id[field_id]
                computed = self.business._validate_value(field, computed)
                previous_application = applied_values.get(field_id)
                if (
                    previous_application is not None
                    and previous_application[0] != computed
                ):
                    raise ValueError(
                        "Conflicting Context rules set "
                        f"{field.label} to different values: "
                        f"{previous_application[1]} and {context.id}"
                    )
                applied_values[field_id] = (computed, context.id)
                working[field_id] = computed
                result[field_id] = computed
                metadata[field_id] = {
                    "origin": "workspace_context",
                    "context_id": context.id,
                    "context_revision": context.revision,
                    "reason": context.statement,
                }
        return result, metadata

    def get_snapshot(self, context_id: str) -> dict[str, Any] | None:
        item = self.store.get_executable(context_id)
        return self.snapshot(item) if item is not None else None

    @staticmethod
    def snapshot(item: WorkspaceContextExecutable) -> dict[str, Any]:
        return {
            "context_id": item.context_id,
            "workspace_id": item.workspace_id,
            "target_collection_id": item.collection_id,
            "trigger": item.trigger,
            "specification": item.specification,
            "read_field_ids": list(item.read_field_ids),
            "write_field_ids": list(item.write_field_ids),
            "status": item.status,
            "context_revision": item.context_revision,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    def _compile_specification(
        self,
        context: WorkspaceContextEntry,
        specification: dict[str, Any],
    ) -> tuple[dict[str, Any], set[str], set[str]]:
        if not isinstance(specification, dict):
            raise ValueError("Context execution specification must be an object")
        unknown = set(specification) - {
            "target_collection_id", "trigger", "condition", "effects",
        }
        if unknown:
            raise ValueError(f"Unsupported Context execution key: {sorted(unknown)[0]}")
        collection_id = str(specification.get("target_collection_id") or "").strip()
        collection = self.business.require_collection(collection_id)
        if collection.workspace_id != context.workspace_id:
            raise ValueError("Target Collection does not belong to the Context Workspace")
        trigger = str(specification.get("trigger") or "before_record_write").strip()
        if trigger != "before_record_write":
            raise ValueError("Only before_record_write is supported in this version")
        fields = self.business.store.list_fields(collection.id)
        lookup = self.business.schema.field_index(fields)
        read_ids: set[str] = set()
        write_ids: set[str] = set()
        condition = specification.get("condition")
        normalized_condition = None
        if condition is not None:
            normalized_condition = self._compile_condition(
                condition, lookup, read_ids,
            )
        raw_effects = specification.get("effects")
        if not isinstance(raw_effects, list) or not raw_effects:
            raise ValueError("Context execution requires at least one effect")
        effects = [
            self._compile_effect(effect, lookup, read_ids, write_ids)
            for effect in raw_effects
        ]
        normalized: dict[str, Any] = {
            "target_collection_id": collection.id,
            "trigger": trigger,
            "effects": effects,
        }
        if normalized_condition is not None:
            normalized["condition"] = normalized_condition
        return normalized, read_ids, write_ids

    def _compile_condition(
        self,
        condition: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
        read_ids: set[str],
    ) -> dict[str, Any]:
        if not isinstance(condition, dict) or not condition:
            raise ValueError("Context condition must be a non-empty object")
        combinators = [key for key in ("all", "any", "not") if key in condition]
        if combinators:
            if len(combinators) != 1 or len(condition) != 1:
                raise ValueError("A condition combinator cannot be mixed with other keys")
            key = combinators[0]
            raw = condition[key]
            if key == "not":
                return {"not": self._compile_condition(raw, lookup, read_ids)}
            if not isinstance(raw, list) or not raw:
                raise ValueError(f"Condition {key} requires a non-empty array")
            return {
                key: [self._compile_condition(item, lookup, read_ids) for item in raw]
            }
        unknown = set(condition) - {"field", "operator", "value"}
        if unknown:
            raise ValueError(f"Unsupported condition key: {sorted(unknown)[0]}")
        field = self._resolve_field(condition.get("field"), lookup)
        operator = str(condition.get("operator") or "").strip().lower()
        if operator not in CONDITION_OPERATORS:
            raise ValueError(f"Unsupported condition operator: {operator}")
        read_ids.add(field.id)
        result: dict[str, Any] = {"field_id": field.id, "operator": operator}
        if operator not in {"is_empty", "not_empty"}:
            if "value" not in condition:
                raise ValueError(f"Condition {operator} requires value")
            raw_value = condition["value"]
            if operator in {"in", "not_in"}:
                if not isinstance(raw_value, list) or not raw_value:
                    raise ValueError(f"Condition {operator} requires a non-empty array")
                result["value"] = [
                    self.business._validate_value(field, item) for item in raw_value
                ]
            else:
                result["value"] = self.business._validate_value(field, raw_value)
        return result

    def _compile_effect(
        self,
        effect: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
        read_ids: set[str],
        write_ids: set[str],
    ) -> dict[str, Any]:
        if not isinstance(effect, dict):
            raise ValueError("Each Context effect must be an object")
        effect_type = str(effect.get("type") or "").strip().lower()
        if effect_type == "reject":
            message = str(effect.get("message") or "").strip()
            if not message:
                raise ValueError("Reject effect requires a message")
            if set(effect) - {"type", "message"}:
                raise ValueError("Reject effect only accepts type and message")
            return {"type": "reject", "message": message}
        if effect_type not in {"set", "set_default"}:
            raise ValueError(f"Unsupported Context effect: {effect_type}")
        unknown = set(effect) - {"type", "field", "value"}
        if unknown:
            raise ValueError(f"Unsupported effect key: {sorted(unknown)[0]}")
        field = self._resolve_field(effect.get("field"), lookup)
        if "value" not in effect:
            raise ValueError(f"{effect_type} effect requires value")
        value = self._compile_expression(effect["value"], lookup, read_ids)
        if effect_type == "set_default":
            read_ids.add(field.id)
        write_ids.add(field.id)
        return {"type": effect_type, "field_id": field.id, "value": value}

    def _compile_expression(
        self,
        value: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
        read_ids: set[str],
    ) -> Any:
        if not isinstance(value, dict):
            return value
        if set(value) == {"field"}:
            field = self._resolve_field(value["field"], lookup)
            read_ids.add(field.id)
            return {"field_id": field.id}
        if set(value) == {"literal"}:
            return {"literal": value["literal"]}
        unknown = set(value) - {"operator", "args"}
        if unknown or "operator" not in value or "args" not in value:
            raise ValueError(
                "Expression objects must contain field, literal, or operator and args"
            )
        operator = str(value["operator"] or "").strip().lower()
        if operator not in EXPRESSION_OPERATORS:
            raise ValueError(f"Unsupported expression operator: {operator}")
        args = value["args"]
        if not isinstance(args, list) or not args:
            raise ValueError(f"Expression {operator} requires a non-empty args array")
        if operator in {"subtract", "divide"} and len(args) != 2:
            raise ValueError(f"Expression {operator} requires exactly two arguments")
        if operator == "round" and len(args) not in {1, 2}:
            raise ValueError("Expression round requires one or two arguments")
        return {
            "operator": operator,
            "args": [self._compile_expression(item, lookup, read_ids) for item in args],
        }

    def _active_executables(
        self,
        workspace_id: str,
        collection_id: str,
    ) -> list[WorkspaceContextExecutable]:
        return [
            item
            for item in self.store.list_executables(
                workspace_id,
                collection_id=collection_id,
            )
            if (context := self.store.get(item.context_id)) is not None
            and context.status in {"established", "formal"}
        ]

    def _applicable_executables(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        person_id: str,
        record_id: str,
    ) -> list[WorkspaceContextExecutable]:
        candidates: list[tuple[WorkspaceContextExecutable, WorkspaceContextEntry]] = []
        for executable in self._active_executables(workspace_id, collection_id):
            context = self.store.get(executable.context_id)
            if context is None:
                continue
            if context.scope_type == "person" and context.scope_id != person_id:
                continue
            if context.scope_type == "transaction" and context.scope_id != record_id:
                continue
            candidates.append((executable, context))
        overridden_ids = {
            context.overrides_context_id
            for _executable, context in candidates
            if context.overrides_context_id
        }
        return [
            executable
            for executable, context in candidates
            if context.id not in overridden_ids
        ]

    @staticmethod
    def _ordered(
        executables: list[WorkspaceContextExecutable],
    ) -> list[WorkspaceContextExecutable]:
        by_id = {item.context_id: item for item in executables}
        outgoing = {item.context_id: set() for item in executables}
        indegree = {item.context_id: 0 for item in executables}
        for earlier in executables:
            writes = set(earlier.write_field_ids)
            for later in executables:
                if earlier.context_id == later.context_id:
                    continue
                if writes.intersection(later.read_field_ids):
                    if later.context_id not in outgoing[earlier.context_id]:
                        outgoing[earlier.context_id].add(later.context_id)
                        indegree[later.context_id] += 1
        ready = sorted(
            (key for key, count in indegree.items() if count == 0),
            key=lambda key: (by_id[key].created_at, key),
        )
        ordered: list[WorkspaceContextExecutable] = []
        while ready:
            current = ready.pop(0)
            ordered.append(by_id[current])
            for target in sorted(outgoing[current]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
                    ready.sort(key=lambda key: (by_id[key].created_at, key))
        if len(ordered) != len(executables):
            raise ValueError("Context execution dependencies contain a cycle")
        return ordered

    @classmethod
    def _condition_matches(cls, condition: dict[str, Any], values: dict[str, Any]) -> bool:
        if "all" in condition:
            return all(cls._condition_matches(item, values) for item in condition["all"])
        if "any" in condition:
            return any(cls._condition_matches(item, values) for item in condition["any"])
        if "not" in condition:
            return not cls._condition_matches(condition["not"], values)
        actual = values.get(condition["field_id"])
        operator = condition["operator"]
        if operator == "is_empty":
            return cls._is_empty(actual)
        if operator == "not_empty":
            return not cls._is_empty(actual)
        expected = condition["value"]
        try:
            return {
                "eq": lambda: actual == expected,
                "ne": lambda: actual != expected,
                "gt": lambda: actual is not None and actual > expected,
                "gte": lambda: actual is not None and actual >= expected,
                "lt": lambda: actual is not None and actual < expected,
                "lte": lambda: actual is not None and actual <= expected,
                "in": lambda: actual in expected,
                "not_in": lambda: actual not in expected,
            }[operator]()
        except (TypeError, ValueError):
            return False

    @classmethod
    def _evaluate_expression(cls, expression: Any, values: dict[str, Any]) -> Any:
        if not isinstance(expression, dict):
            return expression
        if "literal" in expression:
            return expression["literal"]
        if "field_id" in expression:
            return values.get(expression["field_id"])
        operator = expression["operator"]
        args = [cls._evaluate_expression(item, values) for item in expression["args"]]
        if any(value is None for value in args):
            return None
        if operator == "add":
            return sum(args)
        if operator == "subtract":
            return args[0] - args[1]
        if operator == "multiply":
            result: Any = 1
            for value in args:
                result *= value
            return result
        if operator == "divide":
            if args[1] == 0:
                raise ValueError("Context calculation cannot divide by zero")
            return args[0] / args[1]
        if operator == "round":
            digits = int(args[1]) if len(args) == 2 else 0
            return round(args[0], digits)
        if operator == "min":
            return min(args)
        if operator == "max":
            return max(args)
        raise ValueError(f"Unsupported expression operator: {operator}")

    def _resolve_field(
        self,
        identity: Any,
        lookup: dict[str, tuple[FieldDefinition, ...]],
    ) -> FieldDefinition:
        key = self.business.schema.identity_key(identity)
        matches = lookup.get(key, ())
        if not matches:
            raise ValueError(f"Unknown Collection field in Context execution: {identity}")
        if len(matches) > 1:
            raise ValueError(
                "Ambiguous Collection field in Context execution: "
                + str(identity)
            )
        return matches[0]

    @staticmethod
    def _is_empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}
