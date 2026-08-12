"""Validate and persist memory candidates through one boundary."""

from __future__ import annotations

import logging
from typing import Any

from .models import FormationResult, MemoryCandidate
from .policies import retention_seconds
from ..short_term import ShortTermMemoryCandidate, ShortTermMemoryStore

logger = logging.getLogger(__name__)


class MemoryFormationService:
    """Own the short-term/long-term persistence decision."""

    VALID_OPERATIONS = {"ADD", "UPDATE", "MERGE", "DELETE", "NOOP"}
    VALID_RETENTION = {"short_term", "long_term"}
    LONG_TERM_SOURCES = {"dream", "task_completion", "manual", "insight", "learned"}

    def __init__(self, *, short_term: ShortTermMemoryStore, long_term: Any, conversation_db: Any = None) -> None:
        self.short_term = short_term
        self.long_term = long_term
        self.conversation_db = conversation_db

    def form_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        source: str,
        user_id: str,
        session_id: str = "",
        turn_id: str = "",
        default_importance: float = 0.5,
    ) -> list[FormationResult]:
        results: list[FormationResult] = []
        evidence = self._evidence_refs(session_id=session_id, turn_id=turn_id)
        for raw in actions:
            candidate = self._candidate_from_action(
                raw,
                source=source,
                user_id=user_id,
                session_id=session_id,
                evidence_refs=evidence,
                default_importance=default_importance,
            )
            if candidate is None:
                continue
            result = self.form(candidate, source=source, user_id=user_id, session_id=session_id)
            if result is not None:
                results.append(result)
        return results

    def form(
        self,
        candidate: MemoryCandidate,
        *,
        source: str,
        user_id: str,
        session_id: str = "",
    ) -> FormationResult | None:
        if candidate.operation == "NOOP" or not candidate.content.strip():
            return None
        if candidate.retention == "long_term":
            memory_id = self.long_term.store(
                content=candidate.content,
                source=source,
                tags=[candidate.tag] if candidate.tag else None,
                importance=candidate.importance,
                user_id="global" if candidate.scope_type == "agent" else user_id,
                scene_tags=list(candidate.scenes),
                mem_type="common",
                confidence=candidate.confidence,
            )
            self._link_long_term_evidence(memory_id, candidate.evidence_refs)
            return FormationResult(
                "long_term", memory_id, candidate.operation, candidate.content,
                candidate.scope_type, candidate.scope_id,
            )

        short_id = self.short_term.remember(
            ShortTermMemoryCandidate(
                content=candidate.content,
                kind=candidate.tag or "event",
                scope_type=candidate.scope_type,
                scope_id=candidate.scope_id,
                person_id=user_id if candidate.scope_type == "person" else "",
                session_id=session_id,
                confidence=candidate.confidence,
                importance=candidate.importance,
                emotion_intensity=candidate.emotion_intensity,
                retention_seconds=retention_seconds(
                    candidate.tag, candidate.importance, candidate.emotion_intensity,
                ),
                structured_value=candidate.structured_value,
                evidence_refs=candidate.evidence_refs,
            )
        )
        return FormationResult(
            "short_term", short_id, candidate.operation, candidate.content,
            candidate.scope_type, candidate.scope_id,
        )

    def consolidate_for_dream(self, *, cutoff: float | None = None) -> dict[str, int]:
        """Consolidate stable memories and let weak expired ones fade.

        The cutoff freezes the memory set seen by one dream. New memories that
        arrive while dreaming remain untouched until the next dream.
        """
        import time

        dream_cutoff = time.time() if cutoff is None else float(cutoff)
        expired = self.short_term.expire_due(now=dream_cutoff)
        rows = self.short_term._get_conn().execute(
            """SELECT * FROM memories0
               WHERE status = 'active' AND created_at <= ?
               ORDER BY created_at ASC""",
            (dream_cutoff,),
        ).fetchall()
        consolidated = 0
        retained = 0
        for raw in rows:
            item = dict(raw)
            stable = (
                int(item.get("reinforcement_count", 1)) >= 3
                or float(item.get("importance", 0.0)) >= 0.8
                or float(item.get("emotion_intensity", 0.0)) >= 0.85
            )
            if not stable:
                retained += 1
                continue
            user_id = item.get("person_id") or "global"
            memory_id = self.long_term.store(
                content=item["content"],
                source="dream",
                tags=[item.get("kind") or "event"],
                importance=float(item.get("importance", 0.5)),
                user_id=user_id,
                mem_type="common",
                confidence=float(item.get("confidence", 0.7)),
            )
            self.short_term.mark_consolidated(int(item["id"]), memory_id)
            consolidated += 1
        return {
            "consolidated": consolidated,
            "retained": retained,
            "expired": expired,
        }

    def _candidate_from_action(
        self,
        raw: dict[str, Any],
        *,
        source: str,
        user_id: str,
        session_id: str,
        evidence_refs: tuple[tuple[str, str], ...],
        default_importance: float,
    ) -> MemoryCandidate | None:
        if not isinstance(raw, dict):
            return None
        operation = str(raw.get("type") or raw.get("operation") or "ADD").upper()
        if operation not in self.VALID_OPERATIONS:
            operation = "ADD"
        content = str(raw.get("content") or "").strip()
        if operation == "NOOP" or not content:
            return None

        self_memory = bool(raw.get("self"))
        requested_scope = str(raw.get("scope_type") or "").strip().lower()
        if requested_scope in {"session", "person", "workspace", "agent", "world"}:
            scope_type = requested_scope
        else:
            scope_type = "agent" if self_memory else "person"
        default_scope_id = {
            "session": session_id,
            "person": user_id,
            "agent": "global",
            "world": "world",
        }.get(scope_type, "")
        scope_id = str(raw.get("scope_id") or default_scope_id).strip()
        if not scope_id:
            logger.warning("[MemoryFormation] rejected candidate without scope id: %s", content[:80])
            return None

        retention = str(raw.get("retention") or "").strip().lower()
        if retention not in self.VALID_RETENTION:
            retention = "long_term" if source in self.LONG_TERM_SOURCES else "short_term"
        confidence = self._clamp(raw.get("confidence"), 0.7)
        importance = self._clamp(raw.get("importance"), default_importance)
        emotion = self._clamp(raw.get("emotion_intensity"), 0.0)
        scenes = raw.get("scenes") if isinstance(raw.get("scenes"), list) else []
        structured = raw.get("structured_value")
        if not isinstance(structured, dict):
            structured = {}
        return MemoryCandidate(
            content=content,
            operation=operation,
            tag=str(raw.get("kind") or raw.get("tag") or "event").strip(),
            retention=retention,
            scope_type=scope_type,
            scope_id=scope_id,
            confidence=confidence,
            importance=importance,
            emotion_intensity=emotion,
            scenes=tuple(str(item).strip() for item in scenes if str(item).strip())[:3],
            structured_value=structured,
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _clamp(value: Any, default: float) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return default

    def _evidence_refs(self, *, session_id: str, turn_id: str) -> tuple[tuple[str, str], ...]:
        if not self.conversation_db or not session_id:
            return ()
        try:
            recent = self.conversation_db.get_recent(20, session_id=session_id)
        except Exception as exc:
            logger.debug("[MemoryFormation] evidence lookup failed: %s", exc)
            return ()
        refs: list[tuple[str, str]] = []
        if turn_id:
            import json
            for message in reversed(recent):
                try:
                    metadata = json.loads(message.get("metadata") or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                if isinstance(metadata, dict) and str(metadata.get("turn_id") or "") == turn_id:
                    if message.get("role") in {"user", "assistant"}:
                        refs.append(("message", str(message.get("id"))))
            if refs:
                return tuple(refs)
        for message in reversed(recent):
            if message.get("role") not in {"user", "assistant"}:
                continue
            refs.append(("message", str(message.get("id"))))
            if len(refs) >= 2:
                break
        return tuple(refs)

    def _link_long_term_evidence(
        self,
        memory_id: int,
        evidence_refs: tuple[tuple[str, str], ...],
    ) -> None:
        if not evidence_refs:
            return
        conn = self.short_term._get_conn()
        import time
        for evidence_type, evidence_id in evidence_refs:
            conn.execute(
                """INSERT OR IGNORE INTO memory_evidence_links
                   (memory_layer, memory_id, evidence_type, evidence_id, created_at)
                   VALUES ('long_term', ?, ?, ?, ?)""",
                (memory_id, evidence_type, evidence_id, time.time()),
            )
        conn.commit()
