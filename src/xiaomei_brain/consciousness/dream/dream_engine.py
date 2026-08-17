"""DreamEngine: coordinate deterministic Dream0 and generative Dream1."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .dream0 import Dream0, Dream0Report, DreamStageResult
from .dream1 import Dream1, Dream1Report

logger = logging.getLogger(__name__)


@dataclass
class DreamReport:
    """One complete sleep-cycle report.

    The legacy aggregate fields remain available to existing UI and activity
    projections.  ``stages`` is the authoritative account of what actually
    completed, skipped, or failed.
    """

    summary: str = ""
    full_report: str = ""
    memories_consolidated: int = 0
    memories_created: int = 0
    memories_reused: int = 0
    memories_retained: int = 0
    memories_expired: int = 0
    memories_reinforced: int = 0
    memories_faded: int = 0
    # Compatibility alias: this used to be labelled "extracted" even though
    # it has represented short-term -> long-term consolidation since memories0.
    memories_extracted: int = 0
    relations_reinforced: int = 0
    relations_created: int = 0
    relations_decayed: int = 0
    relations_dormant: int = 0
    procedures_archived: int = 0
    procedures_decayed: int = 0
    narratives_archived: int = 0
    narratives_consolidated: int = 0
    patterns_extracted: int = 0
    emotion_changes: dict[str, float] = field(default_factory=dict)
    followup_signal: dict[str, Any] = field(default_factory=dict)
    stages: list[DreamStageResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DreamEngine:
    """Run one uninterruptible dream cycle, then return to sleeping."""

    def __init__(
        self,
        consciousness: Any,
        drive: Any | None,
        ltm: Any | None,
        extractor: Any | None,
        llm: Any | None,
        storage: Any | None = None,
        procedure_memory: Any | None = None,
        exp_stream: Any | None = None,
    ) -> None:
        self.cs = consciousness
        self.drive = drive
        self.ltm = ltm
        self.extractor = extractor
        self.llm = llm
        self.storage = storage
        self.procedure_memory = procedure_memory
        self.exp_stream = exp_stream
        self.dream0 = Dream0(
            consciousness=consciousness,
            ltm=ltm,
            extractor=extractor,
            procedure_memory=procedure_memory,
        )
        self.dream1 = Dream1(
            consciousness=consciousness,
            drive=drive,
            ltm=ltm,
            extractor=extractor,
            exp_stream=exp_stream,
        )

    def run(self) -> DreamReport:
        started_at = time.time()
        cutoff = started_at
        logger.info("[DreamEngine] 开始梦境周期 cutoff=%.3f", cutoff)

        dream0_report = self.dream0.run(cutoff=cutoff)
        logger.info(
            "[Dream0] 完成: 巩固=%d 保留=%d 淡忘=%d errors=%d",
            dream0_report.memories_consolidated,
            dream0_report.memories_retained,
            dream0_report.memories_expired,
            dream0_report.errors,
        )

        dream1_report = self.dream1.run(dream0_report)
        logger.info(
            "[Dream1] 完成: summary=%s patterns=%d errors=%d",
            dream1_report.summary[:60],
            dream1_report.patterns_extracted,
            dream1_report.errors,
        )

        report = self._combine(dream0_report, dream1_report)
        report.elapsed_seconds = time.time() - started_at
        report.errors = dream0_report.errors + dream1_report.errors

        if not report.summary:
            report.summary = str(
                getattr(self.cs.self_image.history, "last_dream_summary", "") or ""
            )
        if self.storage is not None:
            self.storage.save(report)
        self._record_experience(report)

        logger.info(
            "[DreamEngine] 完成: 巩固=%d 衰减=%d 模式=%d errors=%d elapsed=%.1fs",
            report.memories_consolidated,
            report.memories_faded,
            report.patterns_extracted,
            report.errors,
            report.elapsed_seconds,
        )
        return report

    @staticmethod
    def _combine(dream0: Dream0Report, dream1: Dream1Report) -> DreamReport:
        return DreamReport(
            summary=dream1.summary,
            full_report=dream1.full_report,
            memories_consolidated=dream0.memories_consolidated,
            memories_created=dream0.memories_created,
            memories_reused=dream0.memories_reused,
            memories_retained=dream0.memories_retained,
            memories_expired=dream0.memories_expired,
            memories_reinforced=dream0.memories_reinforced,
            memories_faded=dream0.memories_faded,
            memories_extracted=dream0.memories_consolidated,
            relations_reinforced=dream0.relations_reinforced,
            relations_created=dream0.relations_created,
            relations_decayed=dream0.relations_decayed,
            relations_dormant=dream0.relations_dormant,
            procedures_archived=dream0.procedures_archived,
            procedures_decayed=dream0.procedures_decayed,
            narratives_archived=dream0.narratives_archived,
            narratives_consolidated=dream0.narratives_consolidated,
            patterns_extracted=dream1.patterns_extracted,
            emotion_changes=dream1.emotion_changes,
            followup_signal=dream1.followup_signal,
            stages=[*dream0.stages, *dream1.stages],
        )

    def _record_experience(self, report: DreamReport) -> None:
        if self.exp_stream is None:
            return
        try:
            parts = [
                f"梦境完成: {report.summary[:200]}" if report.summary else "梦境完成（无摘要）",
                f"短期记忆巩固{report.memories_consolidated}条",
                f"长期记忆衰减{report.memories_faded}条",
            ]
            if report.patterns_extracted:
                parts.append(f"模式发现{report.patterns_extracted}条")
            self.exp_stream.log(type="dream", content=" | ".join(parts), importance=0.6)
        except Exception as exc:
            logger.debug("[DreamEngine] experience write failed: %s", exc)
