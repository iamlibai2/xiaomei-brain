"""Scoped three-Turn review for short-term memory formation.

This module upgrades the former global periodic extractor.  It does not copy
conversation history or create a second memory system: raw messages remain in
``messages``, the durable cursor remains in ``memory_review_checkpoints``, and
all accepted actions pass through ``MemoryFormationService`` into ``memories0``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from xiaomei_brain.prompts import TURN_BATCH_MEMORY_REVIEW_PROMPT

logger = logging.getLogger(__name__)


class MemoryReviewProtocolError(RuntimeError):
    """The model did not return a usable review document."""


@dataclass(frozen=True)
class MemoryReviewResult:
    person_id: str
    session_id: str
    turn_count: int = 0
    added: int = 0
    updated: int = 0
    merged: int = 0
    reinforced: int = 0
    deleted: int = 0
    noop: int = 0
    rejected: int = 0
    memory_ids: tuple[int, ...] = ()
    processed: bool = False

    @property
    def changed_count(self) -> int:
        return self.added + self.updated + self.merged + self.reinforced + self.deleted

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "session_id": self.session_id,
            "turn_count": self.turn_count,
            "added": self.added,
            "updated": self.updated,
            "merged": self.merged,
            "reinforced": self.reinforced,
            "deleted": self.deleted,
            "noop": self.noop,
            "rejected": self.rejected,
            "count": self.changed_count,
            "memory_ids": list(self.memory_ids),
            "processed": self.processed,
        }


class TurnBatchMemoryReviewer:
    """Review complete Turns within one trusted Person + Session stream."""

    def __init__(
        self,
        *,
        llm_client: Any,
        conversation_db: Any,
        formation_service: Any,
        longterm_memory: Any,
    ) -> None:
        self.llm = llm_client
        self.db = conversation_db
        self.formation = formation_service
        self.longterm = longterm_memory
        self.short_term = formation_service.short_term

    def review_next(
        self,
        *,
        person_id: str,
        session_id: str,
        user_name: str = "",
        batch_turns: int = 3,
        minimum_turns: int | None = None,
    ) -> MemoryReviewResult:
        """Review one available batch and advance its cursor on success."""
        batch = self.db.get_next_memory_review_batch(
            person_id,
            session_id,
            batch_turns=batch_turns,
            minimum_turns=minimum_turns,
        )
        if not batch:
            return MemoryReviewResult(person_id=person_id, session_id=session_id)

        messages_text, evidence_by_turn = self._format_batch(batch)
        query = "\n".join(
            str(message.get("content") or "")
            for message in batch["messages"]
            if message.get("role") == "user"
        )
        embedder = self._embedding_batch
        query_vectors = (
            embedder([query], source="memory.short_term.review")
            if query.strip()
            else []
        )
        query_vector = query_vectors[0] if query_vectors else None
        short_candidates = self._short_term_candidates(
            query,
            person_id=person_id,
            session_id=session_id,
            embedder=embedder,
            query_vector=query_vector,
        )
        long_candidates = self._long_term_candidates(query, person_id=person_id)
        prompt = TURN_BATCH_MEMORY_REVIEW_PROMPT.format(
            user_name=user_name or "对方",
            short_term_memories=self._format_short_candidates(short_candidates),
            long_term_memories=self._format_long_candidates(long_candidates),
            messages=messages_text,
        )
        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            log_level=logging.DEBUG,
        )
        parsed = self._parse_response(str(getattr(response, "content", "") or ""))
        actions = parsed.get("actions")
        if not isinstance(actions, list):
            raise MemoryReviewProtocolError("memory review response has no actions list")

        allowed_target_ids = {int(item["id"]) for item in short_candidates}
        counts = {
            "added": 0,
            "updated": 0,
            "merged": 0,
            "reinforced": 0,
            "deleted": 0,
            "noop": 0,
            "rejected": 0,
        }
        memory_ids: list[int] = []
        labels = {
            "ADD": "added",
            "UPDATE": "updated",
            "MERGE": "merged",
            "REINFORCE": "reinforced",
            "DELETE": "deleted",
        }
        for raw in actions:
            if not isinstance(raw, dict):
                counts["rejected"] += 1
                continue
            raw = dict(raw)
            operation = str(raw.get("operation") or raw.get("type") or "ADD").upper()
            if operation == "NOOP":
                counts["noop"] += 1
                continue
            if operation not in labels:
                counts["rejected"] += 1
                continue
            if operation == "ADD":
                duplicate = self._high_similarity_add_target(raw, short_candidates)
                if duplicate is not None:
                    operation = "MERGE"
                    raw["operation"] = "MERGE"
                    raw["target_memory_id"] = int(duplicate["id"])
            results = self.formation.form_actions(
                [raw],
                source="turn_batch_review",
                user_id=person_id,
                session_id=session_id,
                default_importance=0.5,
                evidence_by_turn=evidence_by_turn,
                allowed_target_ids=allowed_target_ids,
                embedder=embedder,
            )
            if not results:
                counts["rejected"] += 1
                continue
            counts[labels[operation]] += len(results)
            memory_ids.extend(result.memory_id for result in results)

        self.db.advance_memory_review_checkpoint(
            person_id,
            session_id,
            last_message_id=int(batch["max_message_id"]),
            reviewed_turn_count=int(batch["turn_count"]),
        )
        result = MemoryReviewResult(
            person_id=person_id,
            session_id=session_id,
            turn_count=int(batch["turn_count"]),
            memory_ids=tuple(memory_ids),
            processed=True,
            **counts,
        )
        logger.info(
            "[MemoryReview] person=%s session=%s turns=%d add=%d update=%d "
            "merge=%d reinforce=%d noop=%d rejected=%d",
            person_id,
            session_id,
            result.turn_count,
            result.added,
            result.updated,
            result.merged,
            result.reinforced,
            result.noop,
            result.rejected,
        )
        return result

    @staticmethod
    def _high_similarity_add_target(
        action: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Turn an obviously duplicate ADD into a merge of its nearest match."""
        requested_scope = str(action.get("scope_type") or "person").strip().lower()
        for candidate in candidates:
            if str(candidate.get("scope_type") or "") != requested_scope:
                continue
            if float(candidate.get("similarity") or 0.0) >= 0.82:
                return candidate
        return None

    @staticmethod
    def _format_batch(
        batch: dict[str, Any],
    ) -> tuple[str, dict[str, tuple[tuple[str, str], ...]]]:
        grouped: dict[str, list[dict[str, Any]]] = {turn_id: [] for turn_id in batch["turn_ids"]}
        for message in batch["messages"]:
            try:
                metadata = json.loads(message.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            turn_id = str(metadata.get("turn_id") or "")
            if turn_id in grouped:
                grouped[turn_id].append(message)
        lines: list[str] = []
        evidence: dict[str, tuple[tuple[str, str], ...]] = {}
        for turn_id in batch["turn_ids"]:
            lines.append(f'<turn id="{turn_id}">')
            refs: list[tuple[str, str]] = []
            for message in grouped.get(turn_id, []):
                role = str(message.get("role") or "")
                if role not in {"user", "assistant"}:
                    continue
                content = str(message.get("content") or "").strip()
                lines.append(f"[{role}] {content[:2000]}")
                refs.append(("message", str(message.get("id"))))
            lines.append("</turn>")
            evidence[turn_id] = tuple(refs)
        return "\n".join(lines), evidence

    def _short_term_candidates(
        self,
        query: str,
        *,
        person_id: str,
        session_id: str,
        embedder: Any,
        query_vector: list[float] | None,
    ) -> list[dict[str, Any]]:
        combined: dict[int, dict[str, Any]] = {}
        for scope_type, scope_id in (
            ("person", person_id),
            ("agent", "global"),
        ):
            for item in self.short_term.find_similar(
                query,
                scope_type=scope_type,
                scope_id=scope_id,
                embedder=embedder,
                query_vector=query_vector,
                limit=6,
            ):
                combined[int(item["id"])] = item
        return sorted(
            combined.values(),
            key=lambda item: float(item.get("similarity") or 0.0),
            reverse=True,
        )[:10]

    def _long_term_candidates(self, query: str, *, person_id: str) -> list[dict[str, Any]]:
        if not query.strip() or self.longterm is None:
            return []
        try:
            return list(self.longterm.recall(query, user_id=person_id, top_k=5) or [])
        except Exception as exc:
            logger.debug("[MemoryReview] long-term recall failed: %s", exc)
            return []

    def _embedding_batch(
        self,
        texts: list[str],
        *,
        source: str = "memory.short_term.review",
    ) -> list[list[float]]:
        if self.longterm is None:
            return []
        method = getattr(self.longterm, "_embed_batch", None)
        if not callable(method):
            return []
        try:
            return method(texts, source=source)
        except TypeError:
            return method(texts)

    @staticmethod
    def _format_short_candidates(items: list[dict[str, Any]]) -> str:
        if not items:
            return "（无相关短期记忆）"
        return "\n".join(
            f'- [memory_id={item["id"]} scope={item.get("scope_type")}:{item.get("scope_id")}] '
            f'{item.get("content", "")}'
            for item in items
        )

    @staticmethod
    def _format_long_candidates(items: list[dict[str, Any]]) -> str:
        if not items:
            return "（无相关长期记忆）"
        return "\n".join(
            f'- [long_term_id={item.get("id")}] {item.get("content", "")}'
            for item in items
        )

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        block = str(content or "").strip()
        candidates = [block]
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", block, re.DOTALL)
        if fenced:
            candidates.append(fenced.group(1))
        start = block.find("{")
        end = block.rfind("}")
        if start >= 0 and end > start:
            candidates.append(block[start:end + 1])
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        raise MemoryReviewProtocolError("memory review response is not valid JSON")
