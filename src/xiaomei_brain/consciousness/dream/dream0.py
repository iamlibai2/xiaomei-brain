"""Dream0: deterministic sleep maintenance.

Dream0 owns repeatable data maintenance.  It never asks an LLM what should be
stored and it never creates an outward intent.  Its structured result becomes
the factual material consumed by Dream1.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .memory_jobs import ReinforceJob, RelationReinforceJob
from .narrative_jobs import NarrativeConsolidationJob
from .procedure_jobs import ProcedureConsolidationJob

logger = logging.getLogger(__name__)


@dataclass
class DreamStageResult:
    """One truthful Dream0/Dream1 stage outcome."""

    name: str
    title: str
    status: str = "completed"  # completed | skipped | failed
    summary: str = ""
    metrics: dict[str, int] = field(default_factory=dict)
    error: str = ""


@dataclass
class Dream0Report:
    """Facts produced by deterministic sleep maintenance."""

    cutoff: float
    stages: list[DreamStageResult] = field(default_factory=list)
    memories_consolidated: int = 0
    memories_created: int = 0
    memories_reused: int = 0
    memories_retained: int = 0
    memories_expired: int = 0
    memories_reinforced: int = 0
    memories_faded: int = 0
    relations_reinforced: int = 0
    relations_created: int = 0
    relations_decayed: int = 0
    relations_dormant: int = 0
    procedures_archived: int = 0
    procedures_decayed: int = 0
    narratives_archived: int = 0
    narratives_consolidated: int = 0
    material: list[str] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(stage.status == "failed" for stage in self.stages)

    @property
    def has_changes(self) -> bool:
        return any(
            (
                self.memories_consolidated,
                self.memories_expired,
                self.memories_reinforced,
                self.memories_faded,
                self.relations_reinforced,
                self.relations_created,
                self.relations_decayed,
                self.relations_dormant,
                self.procedures_archived,
                self.procedures_decayed,
                self.narratives_archived,
                self.narratives_consolidated,
            )
        )

    def prompt_material(self) -> str:
        lines = ["【Dream0 确定性整理结果】"]
        for stage in self.stages:
            if stage.status == "completed" and stage.summary:
                lines.append(f"- {stage.title}：{stage.summary}")
            elif stage.status == "failed":
                lines.append(f"- {stage.title}：处理失败，本次不据此形成结论")
        if self.material:
            lines.append("【本轮被巩固或重点保留的经历】")
            lines.extend(f"- {item}" for item in self.material[:20])
        return "\n".join(lines)


class Dream0:
    """Run deterministic maintenance once against a frozen cutoff."""

    def __init__(
        self,
        *,
        consciousness: Any | None,
        ltm: Any | None,
        extractor: Any | None,
        procedure_memory: Any | None = None,
    ) -> None:
        self.consciousness = consciousness
        self.ltm = ltm
        self.extractor = extractor
        self.procedure_memory = procedure_memory

    def run(self, *, cutoff: float | None = None) -> Dream0Report:
        report = Dream0Report(cutoff=float(cutoff or time.time()))
        self._consolidate_short_term(report)
        self._maintain_long_term(report)
        self._maintain_relations(report)
        self._maintain_procedures(report)
        self._maintain_narratives(report)
        return report

    @staticmethod
    def _failed(name: str, title: str, exc: Exception) -> DreamStageResult:
        logger.exception("[Dream0] %s failed", name)
        return DreamStageResult(
            name=name,
            title=title,
            status="failed",
            summary=str(exc) or exc.__class__.__name__,
            error=str(exc) or exc.__class__.__name__,
        )

    def _consolidate_short_term(self, report: Dream0Report) -> None:
        title = "短期记忆巩固"
        formation = getattr(self.extractor, "formation_service", None)
        if formation is None:
            report.stages.append(DreamStageResult("memory", title, "skipped", "记忆形成服务不可用"))
            return
        try:
            outcome = formation.consolidate_for_dream(cutoff=report.cutoff)
            report.memories_consolidated = int(outcome.get("consolidated", 0))
            report.memories_created = int(outcome.get("created", report.memories_consolidated))
            report.memories_reused = int(outcome.get("reused", 0))
            report.memories_retained = int(outcome.get("retained", 0))
            report.memories_expired = int(outcome.get("expired", 0))
            report.material.extend(str(item) for item in outcome.get("material", []) if str(item).strip())
            summary = (
                f"巩固 {report.memories_consolidated} 条"
                f"（新建 {report.memories_created}，复用 {report.memories_reused}），"
                f"保留 {report.memories_retained}，淡忘 {report.memories_expired}"
            )
            report.stages.append(DreamStageResult(
                "memory", title, summary=summary,
                metrics={
                    "consolidated": report.memories_consolidated,
                    "created": report.memories_created,
                    "reused": report.memories_reused,
                    "retained": report.memories_retained,
                    "expired": report.memories_expired,
                },
            ))
        except Exception as exc:
            report.stages.append(self._failed("memory", title, exc))

    def _maintain_long_term(self, report: Dream0Report) -> None:
        title = "长期记忆衰减与强化"
        if self.ltm is None:
            report.stages.append(DreamStageResult("long_term", title, "skipped", "长期记忆不可用"))
            return
        try:
            outcome = ReinforceJob(self.ltm).run()
            report.memories_reinforced = outcome.reinforced
            report.memories_faded = int(getattr(outcome, "faded", 0))
            summary = (
                f"自然衰减 {report.memories_faded} 条，"
                f"因再次使用而强化 {report.memories_reinforced} 条，"
                f"休眠 {outcome.extinct} 条"
            )
            report.stages.append(DreamStageResult(
                "long_term", title, summary=summary,
                metrics={"faded": report.memories_faded, "reinforced": outcome.reinforced, "extinct": outcome.extinct},
            ))
        except Exception as exc:
            report.stages.append(self._failed("long_term", title, exc))

    def _maintain_relations(self, report: Dream0Report) -> None:
        title = "记忆关系维护"
        if self.ltm is None:
            report.stages.append(DreamStageResult("relations", title, "skipped", "长期记忆不可用"))
            return
        try:
            outcome = RelationReinforceJob(self.ltm).run()
            report.relations_reinforced = outcome.reinforced
            report.relations_created = outcome.created
            report.relations_decayed = outcome.decayed
            report.relations_dormant = outcome.dormant
            report.stages.append(DreamStageResult(
                "relations", title, summary=outcome.details,
                metrics={
                    "reinforced": outcome.reinforced, "created": outcome.created,
                    "decayed": outcome.decayed, "dormant": outcome.dormant,
                },
            ))
        except Exception as exc:
            report.stages.append(self._failed("relations", title, exc))

    def _maintain_procedures(self, report: Dream0Report) -> None:
        title = "过程记忆维护"
        if self.procedure_memory is None:
            report.stages.append(DreamStageResult("procedures", title, "skipped", "过程记忆未启用"))
            return
        try:
            outcome = ProcedureConsolidationJob(self.procedure_memory).run()
            report.procedures_archived = outcome.archived
            report.procedures_decayed = outcome.decayed
            report.stages.append(DreamStageResult(
                "procedures", title, summary=str(outcome),
                metrics={"archived": outcome.archived, "decayed": outcome.decayed},
            ))
        except Exception as exc:
            report.stages.append(self._failed("procedures", title, exc))

    def _maintain_narratives(self, report: Dream0Report) -> None:
        title = "叙事记忆维护"
        if self.ltm is None:
            report.stages.append(DreamStageResult("narratives", title, "skipped", "长期记忆不可用"))
            return
        try:
            outcome = NarrativeConsolidationJob(self.ltm, self.consciousness).run()
            report.narratives_archived = outcome.archived
            report.narratives_consolidated = outcome.consolidated
            summary = f"归档 {outcome.archived} 条，整合 {outcome.consolidated} 条"
            report.stages.append(DreamStageResult(
                "narratives", title, summary=summary,
                metrics={"archived": outcome.archived, "consolidated": outcome.consolidated},
            ))
        except Exception as exc:
            report.stages.append(self._failed("narratives", title, exc))
