"""Dream1: free dream synthesis over facts prepared by Dream0."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .dream0 import Dream0Report, DreamStageResult
from .emotion_processor import EmotionProcessor

logger = logging.getLogger(__name__)


@dataclass
class Dream1Report:
    summary: str = ""
    full_report: str = ""
    emotion_changes: dict[str, float] = field(default_factory=dict)
    followup_signal: dict[str, Any] = field(default_factory=dict)
    patterns_extracted: int = 0
    stages: list[DreamStageResult] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(stage.status == "failed" for stage in self.stages)


class Dream1:
    """Generate an inner dream without deciding an outward action."""

    def __init__(
        self,
        *,
        consciousness: Any,
        drive: Any | None,
        ltm: Any | None,
        extractor: Any | None,
        exp_stream: Any | None = None,
    ) -> None:
        self.cs = consciousness
        self.drive = drive
        self.ltm = ltm
        self.extractor = extractor
        self.exp_stream = exp_stream
        self.emotion_processor = EmotionProcessor()

    def run(self, dream0: Dream0Report) -> Dream1Report:
        report = Dream1Report()
        self._synthesise(report, dream0)
        self._extract_patterns(report)
        return report

    def _synthesise(self, report: Dream1Report, dream0: Dream0Report) -> None:
        title = "自由梦境"
        try:
            from ..l3_engine import L3Engine

            result = L3Engine(self.cs).burn_dream(
                messages_text=self._recent_experiences(cutoff=dream0.cutoff),
                desire_text=self._desire_text(),
                internal_text=self._internal_text(),
                dream0_text=dream0.prompt_material(),
                manage_side_effects=False,
            )
            report.full_report = result.full_report
            report.summary = result.summary
            if not result.full_report:
                report.stages.append(DreamStageResult("dream1", title, "skipped", "本次没有形成梦境内容"))
                return

            if self.drive:
                self.drive.consume_energy(0.1)
                self.drive.restore_energy(0.2)
            self.cs.self_image.contribute_dream(report.summary)
            self._store_agent_narrative(result.full_report)
            report.emotion_changes = self.emotion_processor.process(
                self.drive, result.full_report, self.cs,
            )
            report.followup_signal = dict(self.emotion_processor.last_signal)
            # The next normal L2 intent decision may consider this observation.
            # It is deliberately not an Intent and cannot execute by itself.
            self.cs._dream_followup_signal = dict(report.followup_signal)
            report.stages.append(DreamStageResult(
                "dream1", title, summary=report.summary or "形成了一段无标题梦境",
                metrics={"characters": len(result.full_report)},
            ))
        except Exception as exc:
            logger.exception("[Dream1] synthesis failed")
            report.stages.append(DreamStageResult(
                "dream1", title, "failed", str(exc) or exc.__class__.__name__, error=str(exc),
            ))

    def _extract_patterns(self, report: Dream1Report) -> None:
        title = "模式联想"
        if self.exp_stream is None or self.ltm is None:
            report.stages.append(DreamStageResult("patterns", title, "skipped", "经验流或长期记忆不可用"))
            return
        try:
            from ...memory.pattern import PatternExtractor, PatternStorage

            extractor = PatternExtractor(
                storage=PatternStorage(self.ltm),
                exp_stream=self.exp_stream,
                conversation_db=getattr(self.extractor, "db", None) if self.extractor else None,
                ltm=self.ltm,
            )
            llm = getattr(getattr(self.cs, "agent", None), "llm", None)
            patterns = extractor.extract(llm)
            report.patterns_extracted = len(patterns)
            report.stages.append(DreamStageResult(
                "patterns", title, summary=f"发现或更新 {len(patterns)} 个模式",
                metrics={"patterns": len(patterns)},
            ))
        except Exception as exc:
            logger.exception("[Dream1] pattern extraction failed")
            report.stages.append(DreamStageResult(
                "patterns", title, "failed", str(exc) or exc.__class__.__name__, error=str(exc),
            ))

    def _recent_experiences(self, *, cutoff: float) -> str:
        db = getattr(self.extractor, "db", None) if self.extractor else None
        if db is None:
            return ""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        messages = db.query(since=today_start, limit=200)
        lines = []
        eligible = [
            message for message in messages
            if float(message.get("created_at") or 0.0) <= cutoff
            and not self._is_unprocessed_human_message(message)
        ]
        for message in eligible[-50:]:
            role = message.get("role", "?")
            user_id = message.get("user_id", "")
            content = str(message.get("content", ""))[:200]
            label = f"{role}:{user_id}" if user_id else role
            lines.append(f"[{label}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _is_unprocessed_human_message(message: dict[str, Any]) -> bool:
        if message.get("role") != "user":
            return False
        metadata = message.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, json.JSONDecodeError):
                metadata = {}
        return isinstance(metadata, dict) and metadata.get("status") in {"queued", "processing"}

    def _desire_text(self) -> str:
        if not self.drive:
            return ""
        desire = self.drive.desire
        return (
            f"归属欲：{desire.belonging:.2f}，认知欲：{desire.cognition:.2f}，"
            f"成就欲：{desire.achievement:.2f}，表达欲：{desire.expression:.2f}"
        )

    def _internal_text(self) -> str:
        history = self.cs.self_image.history
        return "".join(filter(None, (
            history.emotional_trajectory,
            history.goal_rhythm,
            history.consciousness_rhythm,
        ))) or "无"

    def _store_agent_narrative(self, content: str) -> None:
        if not content or self.ltm is None:
            return
        try:
            self.ltm.store_narrative(
                content=content[:500],
                trigger="dream",
                energy_level=self.cs.body.energy if self.cs.self_image else None,
                user_id="global",
            )
        except Exception as exc:
            logger.debug("[Dream1] store narrative failed: %s", exc)
