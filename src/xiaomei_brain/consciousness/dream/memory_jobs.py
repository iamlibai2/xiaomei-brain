"""Deterministic memory maintenance jobs used exclusively by Dream0."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...memory.longterm import LongTermMemory

logger = logging.getLogger(__name__)

STRENGTH_DECAY_BASE = 0.9995
STRENGTH_L4 = 0.2
MEMORY_REINFORCE_BOOST = 0.1
MEMORY_EXTINCT_DAYS = 30
STATUS_ACTIVE = "active"
STATUS_EXTINCT = "extinct"


@dataclass
class DreamResult:
    job: str
    saved: int = 0
    retained: int = 0
    reinforced: int = 0
    faded: int = 0
    extinct: int = 0
    errors: int = 0
    details: str = ""


class ConsolidateShortTermJob:
    """Apply the memories0 consolidation boundary at one frozen cutoff."""

    def __init__(self, formation_service) -> None:
        self.formation_service = formation_service

    def run(self, *, cutoff: float | None = None) -> DreamResult:
        try:
            outcome = self.formation_service.consolidate_for_dream(
                cutoff=float(cutoff or time.time()),
            )
            return DreamResult(
                job="consolidate_short_term",
                saved=outcome["consolidated"],
                retained=outcome["retained"],
                extinct=outcome["expired"],
                details=(
                    f"consolidated={outcome['consolidated']} "
                    f"retained={outcome['retained']} expired={outcome['expired']}"
                ),
            )
        except Exception as exc:
            logger.exception("[ConsolidateShortTermJob] failed")
            return DreamResult(
                job="consolidate_short_term",
                errors=1,
                details=str(exc),
            )


class ReinforceJob:
    """Decay unused long-term memories and reinforce only recalled memories."""

    def __init__(
        self,
        ltm: "LongTermMemory",
        user_id: str | None = None,
        boost: float = MEMORY_REINFORCE_BOOST,
        batch_size: int = 50,
    ) -> None:
        self.ltm = ltm
        self.user_id = user_id
        self.boost = boost
        self.batch_size = batch_size

    def run(self) -> DreamResult:
        conn = self.ltm._get_conn()
        now = time.time()
        cutoff = now - 24 * 3600
        if self.user_id:
            safe_uid = self.ltm._safe_user_id(self.user_id)
            where_user = f"AND user_id = '{safe_uid}'"
        else:
            where_user = ""
        rows = conn.execute(
            f"""SELECT * FROM memories
                WHERE status = ? AND last_strengthen < ? {where_user}
                ORDER BY strength ASC LIMIT ?""",
            (STATUS_ACTIVE, cutoff, self.batch_size),
        ).fetchall()

        reinforced = faded = extinct = errors = 0
        for row in rows:
            memory_id = row["id"]
            try:
                current = float(row["strength"])
                last_accessed = float(row["last_accessed"] or 0.0)
                last_strengthen = float(row["last_strengthen"] or row["created_at"] or now)
                elapsed_hours = max(0.0, now - last_strengthen) / 3600.0
                effective = max(0.0, current * (STRENGTH_DECAY_BASE ** elapsed_hours))
                if last_accessed > last_strengthen:
                    new_strength = min(0.95, effective + self.boost * (1.0 - effective))
                    reinforced += 1
                else:
                    new_strength = effective
                    if new_strength < current:
                        faded += 1

                conn.execute(
                    "UPDATE memories SET strength = ?, last_strengthen = ? WHERE id = ?",
                    (new_strength, now, memory_id),
                )
                if (
                    new_strength < STRENGTH_L4
                    and now - last_accessed > MEMORY_EXTINCT_DAYS * 86400
                ):
                    conn.execute(
                        "UPDATE memories SET status = ? WHERE id = ?",
                        (STATUS_EXTINCT, memory_id),
                    )
                    self.ltm._delete_from_lance(memory_id)
                    extinct += 1
            except Exception as exc:
                logger.warning("[ReinforceJob] failed for #%s: %s", memory_id, exc)
                errors += 1
        conn.commit()
        return DreamResult(
            job="reinforce",
            reinforced=reinforced,
            faded=faded,
            extinct=extinct,
            errors=errors,
            details=f"faded={faded} reinforced={reinforced} extinct={extinct}",
        )


@dataclass
class RelationReinforceResult:
    reinforced: int = 0
    created: int = 0
    decayed: int = 0
    dormant: int = 0
    errors: int = 0
    details: str = ""


class RelationReinforceJob:
    """Maintain co-occurrence relations and decay unused relation weights."""

    def __init__(self, ltm: "LongTermMemory", user_id: str | None = None) -> None:
        self.ltm = ltm
        self.user_id = user_id

    def run(self) -> RelationReinforceResult:
        result = RelationReinforceResult()
        try:
            co_result = self._reinforce_from_co_occurrence()
            result.reinforced = co_result["reinforced"]
            result.created = co_result["created"]
            decay = self.ltm.decay_relation_weights(decay_days=7, decay_factor=0.95)
            result.decayed = decay.get("decayed", 0)
            result.dormant = decay.get("dormant", 0)
            result.details = (
                f"加固{result.reinforced}条(新建{result.created}条), "
                f"衰减{result.decayed}条(休眠{result.dormant}条)"
            )
        except Exception as exc:
            logger.error("[RelationReinforceJob] failed: %s", exc)
            result.errors = 1
            result.details = str(exc)
        return result

    def _reinforce_from_co_occurrence(self) -> dict[str, int]:
        conn = self.ltm._get_conn()
        cutoff = time.time() - 7 * 86400
        if self.user_id:
            rows = conn.execute(
                """SELECT co.memory_a_id, co.memory_b_id, co.co_count,
                          rel.id AS rel_id, rel.weight AS rel_weight
                   FROM memory_co_occurrence co
                   JOIN memories ma ON ma.id = co.memory_a_id
                   JOIN memories mb ON mb.id = co.memory_b_id
                   LEFT JOIN memory_relations rel
                     ON rel.from_memory_id = co.memory_a_id
                    AND rel.to_memory_id = co.memory_b_id
                   WHERE co.last_seen > ?
                     AND ma.user_id IN (?, 'global')
                     AND mb.user_id IN (?, 'global')
                   ORDER BY co.co_count DESC LIMIT 50""",
                (cutoff, self.user_id, self.user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT co.memory_a_id, co.memory_b_id, co.co_count,
                          rel.id AS rel_id, rel.weight AS rel_weight
                   FROM memory_co_occurrence co
                   JOIN memories ma ON ma.id = co.memory_a_id
                   JOIN memories mb ON mb.id = co.memory_b_id
                   LEFT JOIN memory_relations rel
                     ON rel.from_memory_id = co.memory_a_id
                    AND rel.to_memory_id = co.memory_b_id
                   WHERE co.last_seen > ?
                     AND (ma.user_id = mb.user_id OR ma.user_id = 'global' OR mb.user_id = 'global')
                   ORDER BY co.co_count DESC LIMIT 50""",
                (cutoff,),
            ).fetchall()

        reinforced = created = 0
        now = time.time()
        for row in rows:
            relation_id = row["rel_id"]
            if relation_id:
                weight = row["rel_weight"] if row["rel_weight"] is not None else 0.5
                conn.execute(
                    "UPDATE memory_relations SET weight = ?, last_reinforced = ? WHERE id = ?",
                    (min(0.95, weight + 0.1 * (1 - weight)), now, relation_id),
                )
                reinforced += 1
            elif row["co_count"] >= 3:
                conn.execute(
                    """INSERT OR IGNORE INTO memory_relations
                       (from_memory_id, to_memory_id, relation_type, context,
                        created_at, weight, last_reinforced)
                       VALUES (?, ?, 'co_occurrence', 'from:co_occurrence', ?, 0.2, ?)""",
                    (row["memory_a_id"], row["memory_b_id"], now, now),
                )
                created += 1
        conn.commit()
        return {"reinforced": reinforced, "created": created}
