"""Structured semantic query used by capability, Skill and Tool retrieval."""

from __future__ import annotations

import math
import re
from typing import Any


PRIMARY_QUERY_WEIGHT = 0.75
CONTEXT_QUERY_WEIGHT = 0.25


class SelectionQuery(str):
    """A readable query string that preserves primary/context boundaries."""

    primary: str
    context: str

    def __new__(cls, primary: str, context: str = "") -> "SelectionQuery":
        normalized_primary = str(primary or "").strip()
        normalized_context = str(context or "").strip()
        combined = "\n\n".join(
            part for part in (normalized_primary, normalized_context) if part
        )
        value = super().__new__(cls, combined)
        value.primary = normalized_primary
        value.context = normalized_context
        return value

    def with_context(self, value: str) -> "SelectionQuery":
        extra = str(value or "").strip()
        context = "\n".join(part for part in (self.context, extra) if part)
        return SelectionQuery(self.primary, context)


def normalize_selection_query(value: Any) -> str | SelectionQuery:
    """Normalize whitespace without discarding structured query boundaries."""

    def clean(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").lower()).strip()

    if isinstance(value, SelectionQuery):
        return SelectionQuery(clean(value.primary), clean(value.context))
    return clean(str(value or ""))


def embed_selection_query(
    embedder: Any,
    value: str | SelectionQuery,
    *,
    source: str,
) -> list[float]:
    """Embed primary/context separately and return one normalized weighted vector."""
    if not isinstance(value, SelectionQuery) or not value.context:
        return embedder.embed(str(value), source=source)

    vectors = embedder.embed_batch(
        [value.primary, value.context],
        source=source,
    )
    primary, context = vectors
    combined = [
        PRIMARY_QUERY_WEIGHT * float(left)
        + CONTEXT_QUERY_WEIGHT * float(right)
        for left, right in zip(primary, context)
    ]
    norm = math.sqrt(sum(component * component for component in combined))
    if norm <= 0:
        return combined
    return [component / norm for component in combined]

