"""DreamEngine: 梦境总控。

DREAMING 状态时做深度离线处理。

串行流程：
1. 情绪整理（EmotionProcessor）— 根据梦境内容调整 Drive 欲望/激素
2. 记忆整理（MemoryOrganizer）— ReinforceJob + ExtractJob
3. L3 火焰深度燃烧（LLM）— 完整意识报告
4. 反省（Reflection）— 预留

DreamEngine 由 ConsciousLiving._loop_dreaming() 调用，
不依赖独立调度器。

Usage:
    engine = DreamEngine(
        consciousness=consciousness,
        drive=drive,
        ltm=agent.longterm_memory,
        extractor=agent.memory_extractor,
        llm=agent.llm,
    )
    report = engine.run()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from ...prompts.consciousness import DREAM_ENGINE_PROMPT
from .emotion_processor import EmotionProcessor
from .memory_organizer import MemoryOrganizer
from .reflection import Reflection
from .storage import DreamStorage

logger = logging.getLogger(__name__)


# ── DreamReport ──────────────────────────────────────────────

@dataclass
class DreamReport:
    """梦境产物"""
    summary: str = ""
    """一句话梦境摘要"""
    full_report: str = ""
    """完整 LLM 报告"""
    memories_reinforced: int = 0
    """强化了多少条记忆"""
    memories_extracted: int = 0
    """提取了多少条新记忆"""
    relations_reinforced: int = 0
    """加固了多少条关系"""
    relations_created: int = 0
    """新建了多少条关系"""
    relations_decayed: int = 0
    """衰减了多少条关系"""
    relations_dormant: int = 0
    """休眠了多少条关系"""
    procedures_archived: int = 0
    """归档了多少条 procedure"""
    procedures_decayed: int = 0
    """衰减了多少条 procedure"""
    narratives_archived: int = 0
    """归档了多少条 narrative"""
    narratives_consolidated: int = 0
    """合并了多少条 narrative"""
    emotion_changes: dict = field(default_factory=dict)
    """情绪/欲望变化"""
    elapsed_seconds: float = 0.0
    """总耗时"""
    errors: int = 0
    """错误数"""

    def to_dict(self) -> dict:
        return asdict(self)


# ── DreamEngine ──────────────────────────────────────────────

class DreamEngine:
    """梦境总控"""

    def __init__(
        self,
        consciousness: Any,
        drive: Any | None,
        ltm: Any | None,
        extractor: Any | None,
        llm: Any | None,
        storage: DreamStorage | None = None,
        procedure_memory: Any | None = None,
    ) -> None:
        self.cs = consciousness
        self.drive = drive
        self.ltm = ltm
        self.extractor = extractor
        self.llm = llm
        self.storage = storage or DreamStorage(
            base_dir="~/.xiaomei-brain",
            agent_id=getattr(consciousness, '_agent_id', ''),
        )
        self.procedure_memory = procedure_memory

        # 子系统
        self.emotion_processor = EmotionProcessor()
        self.memory_organizer = MemoryOrganizer(ltm, extractor)
        self.reflection = Reflection()

    def run(self, prior_summary: str = "") -> DreamReport:
        """执行梦境。

        Args:
            prior_summary: 如果之前已有梦境摘要（如 L3 触发后写入的），直接使用，跳过 LLM 调用

        Returns:
            DreamReport
        """
        t0 = time.time()
        report = DreamReport()

        logger.info("[DreamEngine] 开始梦境")

        # ── 阶段1：情绪整理 ─────────────────────────────
        # 基于已有梦境摘要调整 Drive（如果有的话）
        summary_to_process = (
            prior_summary
            or self.cs.self_image.history.last_dream_summary
        )
        if summary_to_process:
            changes = self.emotion_processor.process(self.drive, summary_to_process)
            report.emotion_changes = changes
            logger.info("[DreamEngine] 情绪整理: %s", changes)

        # ── 阶段2：记忆整理 ─────────────────────────────
        try:
            mem_result = self.memory_organizer.organize()
            report.memories_reinforced = mem_result.reinforced
            report.memories_extracted = mem_result.extracted
            report.relations_reinforced = mem_result.relations_reinforced
            report.relations_created = mem_result.relations_created
            report.relations_decayed = mem_result.relations_decayed
            report.relations_dormant = mem_result.relations_dormant
        except Exception as e:
            logger.error("[DreamEngine] 记忆整理失败: %s", e)
            report.errors += 1

        # ── 阶段2.5：Procedure 巩固 ──────────────────────
        if self.procedure_memory:
            try:
                from .procedure_jobs import ProcedureConsolidationJob
                job = ProcedureConsolidationJob(self.procedure_memory)
                proc_result = job.run()
                report.procedures_archived = proc_result.archived
                report.procedures_decayed = proc_result.decayed
                logger.info("[DreamEngine] Procedure巩固: %s", proc_result)
            except Exception as e:
                logger.warning("[DreamEngine] Procedure巩固失败: %s", e)

        # ── 阶段2.x：Narrative 整合 ─────────────────────
        if self.ltm:
            try:
                from .narrative_jobs import NarrativeConsolidationJob
                job = NarrativeConsolidationJob(self.ltm, self.cs)
                narr_result = job.run()
                report.narratives_archived = narr_result.archived
                report.narratives_consolidated = narr_result.consolidated
                logger.info("[DreamEngine] Narrative巩固: archived=%d consolidated=%d",
                            narr_result.archived, narr_result.consolidated)
            except Exception as e:
                logger.warning("[DreamEngine] Narrative巩固失败: %s", e)

        # ── 阶段3：L3 火焰深度燃烧 ─────────────────────
        # 如果已有摘要，直接用；否则调 LLM
        if summary_to_process and not prior_summary:
            # prior_summary 为空但 SelfImage 有 last_dream_summary → 用现成的
            report.summary = summary_to_process
            report.full_report = self.cs.self_image.history.last_dream_summary
            logger.info("[DreamEngine] 使用已有梦境摘要: %s", report.summary[:30])
        elif not summary_to_process:
            # 真的需要 LLM 生成
            self._run_flame_burn(report)
        else:
            # prior_summary 有值 → 这是外部传入的 L3 产物
            report.summary = prior_summary
            logger.info("[DreamEngine] 使用外部梦境摘要: %s", report.summary[:30])

        # ── 阶段4：反省（预留）──────────────────────────
        try:
            self.reflection.reflect(self.cs)
        except Exception as e:
            logger.warning("[DreamEngine] 反省失败: %s", e)

        report.elapsed_seconds = time.time() - t0

        # ── 存储 ────────────────────────────────────────
        self.storage.save(report)

        logger.info(
            "[DreamEngine] 完成: 强化%d条, 提取%d条, 耗时%.1fs",
            report.memories_reinforced,
            report.memories_extracted,
            report.elapsed_seconds,
        )
        return report

    def _run_flame_burn(self, report: DreamReport) -> None:
        """调用 LLM 生成深度意识报告"""
        prompt = self._build_dream_prompt()

        try:
            resp = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            full_report = resp.content or ""
        except Exception as e:
            logger.error("[DreamEngine] LLM 调用失败: %s", e)
            report.errors += 1
            full_report = ""

        report.full_report = full_report
        report.summary = self._extract_summary(full_report)

        # 消耗 + 恢复能量
        if self.drive:
            self.drive.consume_energy(0.1)
            self.drive.restore_energy(0.2)

        # 同步到 SelfImage
        self.cs.history.update_dream_summary(report.summary)

        # 写入长期记忆
        if self.ltm and full_report:
            self.ltm.store(
                content=full_report[:500],
                source="internal",
                tags=["consciousness", "L3", "dream", "deep_burn"],
                importance=0.5,
            )

        # 生成后续 intent
        self._generate_followup_intent(report.summary)

        logger.info("[DreamEngine] L3 燃烧:\n%s", full_report[:200])

    def _generate_followup_intent(self, summary: str) -> None:
        """根据梦境摘要生成后续意图"""
        if not summary:
            return

        from ..intent import (
            create_greet_intent,
            create_reflect_intent,
            create_wait_intent,
        )

        if any(k in summary for k in ["用户", "想念", "连接", "一起", "陪伴"]):
            intent = create_greet_intent(summary[:50], priority=80)
        elif any(k in summary for k in ["目标", "完成", "进展", "失败"]):
            intent = create_reflect_intent(summary[:50], priority=60)
        else:
            intent = create_wait_intent()

        self.cs.intent_buffer.append(intent)
        if self.cs.self_image is not None:
            self.cs.self_image.intent.intent_buffer.append({
                "type": intent.type.value,
                "reason": getattr(intent, "reason", ""),
                "priority": getattr(intent, "priority", 0),
            })
        logger.info("[DreamEngine] 生成后续意图: %s", intent.type.value)

    def _build_dream_prompt(self) -> str:
        """构建梦境 prompt"""
        si = self.cs.self_image
        time_info = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 今日对话
        messages_text = ""
        if self.extractor and self.extractor.db:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0,
            ).timestamp()
            messages = self.extractor.db.query(since=today_start, limit=200)
            if messages:
                lines = []
                for m in messages[-50:]:
                    role = m.get("role", "?")
                    content = m.get("content", "")[:200]
                    lines.append(f"[{role}] {content}")
                messages_text = "\n".join(lines)

        # Drive 状态
        desire_text = ""
        if self.drive:
            d = self.drive.desire
            desire_text = (
                f"归属欲：{d.belonging:.2f}，"
                f"认知欲：{d.cognition:.2f}，"
                f"成就欲：{d.achievement:.2f}，"
                f"表达欲：{d.expression:.2f}"
            )

        history = si.history
        internal = "".join(filter(None, [
            history.emotional_trajectory,
            history.goal_rhythm,
            history.consciousness_rhythm,
        ])) or "无"

        identity = si.being.name
        energy = f"{si.body.energy:.2f}"
        mood = si.body.mood
        msgs = messages_text or "（无今日对话）"
        return DREAM_ENGINE_PROMPT.format(
            identity=identity,
            time_info=time_info,
            energy=energy,
            mood=mood,
            desire_text=desire_text,
            internal=internal,
            messages_text=msgs,
        )

    @staticmethod
    def _extract_summary(full_report: str) -> str:
        """从完整报告提取一句话摘要"""
        if not full_report:
            return ""
        for sep in ["。", "\n", "！", "？"]:
            if sep in full_report:
                sentence = full_report.split(sep)[0] + sep
                if len(sentence) <= 60:
                    return sentence
        return full_report[:60]
