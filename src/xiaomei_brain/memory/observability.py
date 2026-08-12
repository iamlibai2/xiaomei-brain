"""Safe, transport-neutral projections of memories used during a turn."""

from __future__ import annotations

from typing import Any, Iterable


def build_memory_references(
    memories: Iterable[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Return public references for memories made available to one answer.

    The projection excludes embeddings, ranking internals, private narratives,
    and model reasoning.  It contains only memory text already injected into
    the conversational context and a small amount of provenance.
    """
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        content = _clean_text(memory.get("content"), 280)
        if not content:
            continue
        memory_id = str(memory.get("id") or "").strip()
        identity = memory_id or content
        if identity in seen:
            continue
        seen.add(identity)
        references.append({
            "id": memory_id,
            "summary": content,
            "source": _clean_text(memory.get("source"), 40),
            "memory_type": _clean_text(memory.get("type"), 40),
            "tags": [
                cleaned
                for tag in (memory.get("tags") or [])
                if (cleaned := _clean_text(tag, 40))
            ][:5],
            "created_at": _number(memory.get("created_at")),
        })
        if len(references) >= max(1, limit):
            break
    return references


def list_person_memory_views(
    longterm_memory: Any,
    person_id: str,
    *,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    """Return bounded, public long-term memory cards for one Person."""
    rows = longterm_memory.list_person_memories(
        person_id,
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(rows) > limit
    memories = []
    for row in rows[:limit]:
        summary = _clean_text(row.get("content"), 500)
        if not _is_complete_memory_summary(summary):
            continue
        memories.append({
            "id": str(row.get("id") or ""),
            "summary": summary,
            "source": _clean_text(row.get("source"), 40),
            "memory_type": _clean_text(row.get("type"), 40),
            "tags": [
                cleaned
                for tag in (row.get("tags") or [])
                if (cleaned := _clean_text(tag, 40))
            ][:8],
            "created_at": _number(row.get("created_at")),
            "last_accessed": _number(row.get("last_accessed")),
        })
    return memories, has_more


def list_person_short_term_memory_views(
    short_term_memory: Any,
    person_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the active memories0 projection visible to one Person."""
    memories: list[dict[str, Any]] = []
    for row in short_term_memory.list_for_person(person_id, limit=limit):
        summary = _clean_text(row.get("content"), 500)
        if not _is_complete_memory_summary(summary):
            continue
        memories.append({
            "id": f"m0:{row.get('id')}",
            "summary": summary,
            "source": _clean_text(row.get("formation_source"), 40) or "short_term",
            "memory_type": _clean_text(row.get("kind"), 40),
            "tags": [],
            "created_at": _number(row.get("created_at")),
            "last_accessed": _number(row.get("last_seen_at")),
            "expires_at": _number(row.get("expires_at")),
            "reinforcement_count": int(row.get("reinforcement_count") or 1),
            "memory_layer": "short_term",
        })
    return memories


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split())
    return text[:limit]


def _is_complete_memory_summary(value: str) -> bool:
    """Keep UI cards useful without encoding language-specific phrases.

    Very short fragments such as an isolated subject and verb are extraction
    debris rather than independently understandable memories. Six visible
    characters still allows concise facts while rejecting those fragments.
    """
    compact = "".join(str(value or "").split())
    return len(compact) >= 6


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
