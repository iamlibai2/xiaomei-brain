"""Deterministic schema resolution for a Workspace business world.

The Agent may propose names and structures, but durable IDs and merges are
decided here.  Semantic/vector retrieval may eventually supply candidates;
it must never silently decide that two business concepts are the same.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

from .business_store import BusinessStore
from .models import CollectionDefinition, FieldDefinition


class SchemaAmbiguityError(ValueError):
    """More than one durable schema object matches the proposed identity."""


@dataclass(frozen=True)
class FieldEvolutionPlan:
    additions: tuple[dict[str, Any], ...]
    reused: tuple[FieldDefinition, ...]
    alias_updates: dict[str, tuple[str, ...]]

    @property
    def changed(self) -> bool:
        return bool(self.additions or self.alias_updates)


class SchemaResolver:
    """Keep dynamic Collection structure deterministic and conservative."""

    def __init__(self, store: BusinessStore) -> None:
        self.store = store

    @staticmethod
    def identity_key(value: Any) -> str:
        """Normalize harmless presentation differences, not business meaning."""
        text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
        return re.sub(r"[\s_\-./\\]+", "", text)

    def resolve_collection_identity(
        self,
        workspace_id: str,
        *,
        name: str,
        label: str,
    ) -> CollectionDefinition | None:
        proposed = {
            self.identity_key(identity)
            for identity in (name, label)
            if self.identity_key(identity)
        }
        matches = []
        for collection in self.store.list_collections(workspace_id):
            identities = {
                self.identity_key(collection.id),
                self.identity_key(collection.name),
                self.identity_key(collection.label),
            }
            if proposed.intersection(identities):
                matches.append(collection)
        if len(matches) > 1:
            summary = ", ".join(
                f"{item.label} ({item.id})" for item in matches[:5]
            )
            raise SchemaAmbiguityError(
                "Collection identity is ambiguous; inspect the Workspace and use an "
                f"exact collection_id: {summary}"
            )
        return matches[0] if matches else None

    def resolve_import_collection(
        self,
        workspace_id: str,
        headers: list[str],
    ) -> CollectionDefinition | None:
        """Find one clearly compatible Collection or refuse an ambiguous merge."""
        normalized_headers = {
            self.identity_key(header) for header in headers if self.identity_key(header)
        }
        if len(normalized_headers) < 2:
            return None
        candidates: list[tuple[int, float, CollectionDefinition]] = []
        for collection in self.store.list_collections(workspace_id):
            fields = self.store.list_fields(collection.id)
            identities = set(self.field_index(fields))
            matched = len(normalized_headers.intersection(identities))
            coverage = matched / len(normalized_headers)
            if matched >= 2 and coverage >= 0.5:
                candidates.append((matched, coverage, collection))
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (item[0], item[1], item[2].updated_at),
            reverse=True,
        )
        best = candidates[0]
        tied = [item for item in candidates if item[:2] == best[:2]]
        if len(tied) > 1:
            summary = ", ".join(
                f"{item[2].label} ({item[2].id})" for item in tied[:5]
            )
            raise SchemaAmbiguityError(
                "The imported columns match multiple Collections equally. Specify "
                f"collection_id instead of creating another structure: {summary}"
            )
        return best[2]

    def plan_field_evolution(
        self,
        existing: list[FieldDefinition],
        proposed: list[dict[str, Any]],
    ) -> FieldEvolutionPlan:
        index = self.field_index(existing)
        additions: list[dict[str, Any]] = []
        reused: list[FieldDefinition] = []
        alias_updates: dict[str, tuple[str, ...]] = {}
        reserved_new: dict[str, str] = {}
        resolved_existing: dict[str, str] = {}
        for proposal in proposed:
            identities = self._proposal_identities(proposal)
            matches = {
                field.id
                for identity in identities
                for field in index.get(identity, ())
            }
            if len(matches) > 1:
                labels = [
                    field.label for field in existing if field.id in matches
                ]
                raise SchemaAmbiguityError(
                    "Proposed field matches multiple existing fields: "
                    + ", ".join(labels)
                )
            if matches:
                field = next(item for item in existing if item.id in matches)
                previous = resolved_existing.get(field.id)
                if previous is not None:
                    raise SchemaAmbiguityError(
                        "Multiple proposed fields resolve to the same stable field: "
                        f"{previous} and {proposal['label']}"
                    )
                resolved_existing[field.id] = str(proposal["label"])
                self._require_compatible_type(field, str(proposal["data_type"]))
                reused.append(field)
                merged_aliases = self._merged_aliases(field, proposal)
                if merged_aliases != field.aliases:
                    alias_updates[field.id] = merged_aliases
                continue
            for identity in identities:
                owner = reserved_new.get(identity)
                if owner is not None:
                    raise SchemaAmbiguityError(
                        "Proposed fields overlap after identity normalization: "
                        f"{owner} and {proposal['label']}"
                    )
                reserved_new[identity] = str(proposal["label"])
            additions.append(proposal)
        return FieldEvolutionPlan(
            additions=tuple(additions),
            reused=tuple(reused),
            alias_updates=alias_updates,
        )

    def field_index(
        self,
        fields: list[FieldDefinition],
    ) -> dict[str, tuple[FieldDefinition, ...]]:
        mutable: dict[str, list[FieldDefinition]] = {}
        for field in fields:
            for identity in (field.id, field.name, field.label, *field.aliases):
                key = self.identity_key(identity)
                if not key:
                    continue
                bucket = mutable.setdefault(key, [])
                if all(item.id != field.id for item in bucket):
                    bucket.append(field)
        return {key: tuple(items) for key, items in mutable.items()}

    def resolve_field(
        self,
        fields: list[FieldDefinition],
        identity: Any,
    ) -> FieldDefinition:
        raw = str(identity or "").strip()
        direct = [field for field in fields if field.id == raw]
        if direct:
            return direct[0]
        matches = self.field_index(fields).get(self.identity_key(raw), ())
        if not matches:
            raise ValueError(f"Unknown Collection field: {identity}")
        if len(matches) > 1:
            summary = ", ".join(f"{item.label} ({item.id})" for item in matches)
            raise SchemaAmbiguityError(
                f"Collection field is ambiguous: {identity}; candidates: {summary}"
            )
        return matches[0]

    def normalize_values(
        self,
        values: dict[str, Any],
        fields: list[FieldDefinition],
        *,
        validate: Callable[[FieldDefinition, Any], Any],
    ) -> dict[str, Any]:
        if not isinstance(values, dict) or not values:
            if values == {}:
                return {}
            raise ValueError("Record values must be an object")
        normalized: dict[str, Any] = {}
        source_keys: dict[str, str] = {}
        for key, value in values.items():
            field = self.resolve_field(fields, key)
            validated = validate(field, value)
            if field.id in normalized and normalized[field.id] != validated:
                raise SchemaAmbiguityError(
                    "Multiple input keys resolve to the same field with different "
                    f"values: {source_keys[field.id]} and {key}"
                )
            normalized[field.id] = validated
            source_keys[field.id] = str(key)
        return normalized

    @classmethod
    def _proposal_identities(cls, proposal: dict[str, Any]) -> set[str]:
        return {
            cls.identity_key(identity)
            for identity in (
                proposal.get("name"), proposal.get("label"),
                *(proposal.get("aliases") or ()),
            )
            if cls.identity_key(identity)
        }

    @classmethod
    def _merged_aliases(
        cls,
        field: FieldDefinition,
        proposal: dict[str, Any],
    ) -> tuple[str, ...]:
        canonical = {cls.identity_key(field.name), cls.identity_key(field.label)}
        result = list(field.aliases)
        known = canonical | {cls.identity_key(item) for item in result}
        for identity in (
            proposal.get("name"), proposal.get("label"),
            *(proposal.get("aliases") or ()),
        ):
            text = str(identity or "").strip()
            key = cls.identity_key(text)
            if text and key not in known:
                result.append(text)
                known.add(key)
        return tuple(result)

    @staticmethod
    def _require_compatible_type(
        field: FieldDefinition,
        proposed_type: str,
    ) -> None:
        existing = field.data_type
        proposed = proposed_type.strip().lower()
        compatible = (
            existing == proposed
            or existing == "text"
            or existing == "json"
            or (existing == "number" and proposed == "integer")
            or (existing == "money" and proposed in {"integer", "number"})
            or (existing == "datetime" and proposed == "date")
        )
        if not compatible:
            raise ValueError(
                f"Field {field.label} already has type {existing}; proposed type "
                f"{proposed} is incompatible. Use the existing field or define a "
                "distinct business concept."
            )
