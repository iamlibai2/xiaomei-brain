"""DreamEngine: 梦境总控。

DREAMING 状态时做深度离线处理。

串行流程：
1a. 记忆提取（ExtractJob）— 从今日对话提取新记忆
1b. 记忆强化（ReinforceJob）— 低强度记忆强化 + extinct
1c. 关系强化（RelationReinforceJob）— 共现→关系加固 + 衰减
3.  梦境深度燃烧（LLM）— 完整的梦境意识报告（含 ---EMOTION--- 情绪块）
4.  反省（Reflection）— 预留

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

from .emotion_processor import EmotionProcessor
from .memory_jobs import ReinforceJob, ExtractJob, RelationReinforceJob
from .reflection import Reflection
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
    patterns_extracted: int = 0
    """提取/更新了多少条模式"""
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

        # 子系统
        self.emotion_processor = EmotionProcessor()
        self.reflection = Reflection()

    def run(self) -> DreamReport:
        """执行梦境。

        Returns:
            DreamReport
        """
        t0 = time.time()
        report = DreamReport()

        logger.info("[DreamEngine] 开始梦境")

        # ── 阶段1a：记忆提取 ────────────────────────────
        # 先提取今日对话中的新记忆，让后续阶段（强化、关系、燃烧）都能用到
        # 梦境处理所有用户的消息，不依赖 current_user_id，
        # 每条记忆的归属由消息自身的 user_id 决定
        try:
            if self.extractor and self.extractor.llm:
                ej = ExtractJob(self.extractor)
                e = ej.run()
                report.memories_extracted = e.saved
                logger.info("[DreamEngine] 记忆提取: saved=%d", e.saved)
        except Exception as e:
            logger.error("[DreamEngine] 记忆提取失败: %s", e)
            report.errors += 1

        # ── 阶段1b：记忆强化 ────────────────────────────
        # 梦境处理所有用户的记忆，不限定 user_id
        try:
            if self.ltm:
                rj = ReinforceJob(self.ltm)
                r = rj.run()
                report.memories_reinforced = r.reinforced
                logger.info("[DreamEngine] 记忆强化: reinforced=%d extinct=%d", r.reinforced, r.extinct)
        except Exception as e:
            logger.error("[DreamEngine] 记忆强化失败: %s", e)
            report.errors += 1

        # ── 阶段1c：关系强化 ────────────────────────────
        # 梦境处理所有用户的关系，不限定 user_id
        try:
            if self.ltm:
                rrj = RelationReinforceJob(self.ltm)
                rr = rrj.run()
                report.relations_reinforced = rr.reinforced
                report.relations_created = rr.created
                report.relations_decayed = rr.decayed
                report.relations_dormant = rr.dormant
                logger.info("[DreamEngine] 关系强化: reinforced=%d created=%d", rr.reinforced, rr.created)
        except Exception as e:
            logger.error("[DreamEngine] 关系强化失败: %s", e)
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

        # ── 阶段3：Pattern 提取 ──────────────────────────
        if self.exp_stream and self.ltm:
            try:
                from ...memory.pattern import PatternStorage, PatternExtractor
                pstorage = PatternStorage(self.ltm)
                extractor = PatternExtractor(
                    storage=pstorage,
                    exp_stream=self.exp_stream,
                    conversation_db=getattr(
                        self.extractor, 'db', None,
                    ) if self.extractor else None,
                    ltm=self.ltm,
                )
                patterns = extractor.extract(self.llm)
                report.patterns_extracted = len(patterns)
                logger.info("[DreamEngine] Pattern 提取: %d 条", len(patterns))
            except Exception as e:
                logger.warning("[DreamEngine] Pattern 提取失败: %s", e)

        # ── 阶段4：梦境深度燃烧 ─────────────────────
        # 有新记忆被提取 → 重新生成摘要；否则复用缓存
        last_summary = self.cs.self_image.history.last_dream_summary
        if report.memories_extracted > 0:
            self._run_dream_burn(report)
        elif last_summary:
            report.summary = last_summary
            report.full_report = self.cs.self_image.history.last_dream_summary
            logger.info("[DreamEngine] 无新记忆，复用已有梦境摘要: %s", report.summary[:30])
        else:
            self._run_dream_burn(report)

        # ── 阶段5：反省（预留）──────────────────────────
        try:
            self.reflection.reflect(self.cs)
        except Exception as e:
            logger.warning("[DreamEngine] 反省失败: %s", e)

        report.elapsed_seconds = time.time() - t0

        # ── 存储（可选）───────────────────────────────────
        if self.storage:
            self.storage.save(report)

        logger.info(
            "[DreamEngine] 完成: 强化%d条, 提取%d条, 耗时%.1fs",
            report.memories_reinforced,
            report.memories_extracted,
            report.elapsed_seconds,
        )

        # ── 经验流 ──
        if self.exp_stream:
            try:
                parts = [f"梦境完成: {report.summary[:200]}" if report.summary else "梦境完成（无摘要）"]
                if report.memories_reinforced:
                    parts.append(f"记忆强化{report.memories_reinforced}条")
                if report.memories_extracted:
                    parts.append(f"记忆提取{report.memories_extracted}条")
                if report.patterns_extracted:
                    parts.append(f"模式提取{report.patterns_extracted}条")
                if report.emotion_changes:
                    parts.append(f"情绪变化: {report.emotion_changes}")
                self.exp_stream.log(
                    type="dream",
                    content=" | ".join(parts),
                    importance=0.6,
                )
            except Exception as e:
                logger.debug("[ExpStream] dream write failed: %s", e)
        return report

    def _run_dream_burn(self, report: DreamReport) -> None:
        """梦境深度燃烧 → 委托给 L3Engine。

        与清醒态的 tick_L3() 是不同的路径：
        - tick_L3(): 清醒时触发，产出 → last_l3_summary，trigger="L3"
        - burn_dream(): DREAMING 中触发，产出 → last_dream_summary，trigger="dream"
        """
        # 构建上下文
        messages_text = self._get_today_messages()
        desire_text = self._get_desire_text()
        internal_text = self._get_internal_text()

        # 委托给 L3Engine（manage_side_effects=False，由 DreamEngine 编排后续）
        from ..l3_engine import L3Engine
        l3_engine = L3Engine(self.cs)
        result = l3_engine.burn_dream(
            messages_text=messages_text,
            desire_text=desire_text,
            internal_text=internal_text,
            manage_side_effects=False,
        )

        full_report = result.full_report
        report.full_report = full_report
        report.summary = result.summary

        # 消耗 + 恢复能量
        if self.drive:
            self.drive.consume_energy(0.1)
            self.drive.restore_energy(0.2)

        # 同步到 SelfImage（写 last_dream_summary，不是 last_l3_summary）
        self.cs.self_image.contribute_dream(report.summary)

        # 存储到 consciousness_stream
        if full_report:
            ltm = self.ltm
            if ltm:
                try:
                    ltm.store_narrative(
                        content=full_report[:500],
                        trigger='dream',
                        energy_level=self.cs.body.energy if self.cs.self_image else None,
                        user_id=getattr(self.cs.agent, "user_id", "global"),
                    )
                except Exception as e:
                    logger.debug("[DreamEngine] store_narrative failed: %s", e)

        # 经验流
        if self.exp_stream:
            try:
                self.exp_stream.log(
                    type="dream",
                    content=f"梦境完成: {report.summary[:120]}" if report.summary else "梦境完成（无摘要）",
                    importance=0.6,
                )
            except Exception as e:
                logger.debug("[ExpStream] dream write failed: %s", e)

        # 情绪整理：从梦境报告中提取 ---EMOTION--- 块，应用 Drive 变更，生成后续 intent
        changes = self.emotion_processor.process(self.drive, full_report, self.cs)
        report.emotion_changes = changes
        if changes:
            logger.info("[DreamEngine] 情绪整理: %s", changes)

        logger.info("[DreamEngine] 梦境深度燃烧完成 (%d 字)", len(full_report))

    def _get_today_messages(self) -> str:
        """获取今日对话片段（供 L3Engine.burn_dream() 使用）。"""
        if self.extractor and self.extractor.db:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0,
            ).timestamp()
            messages = self.extractor.db.query(since=today_start, limit=200)
            if messages:
                lines = []
                for m in messages[-50:]:
                    role = m.get("role", "?")
                    uid = m.get("user_id", "")
                    content = m.get("content", "")[:200]
                    label = f"{role}:{uid}" if uid else role
                    lines.append(f"[{label}] {content}")
                return "\n".join(lines)
        return ""

    def _get_desire_text(self) -> str:
        """获取欲望状态文本（供 L3Engine.burn_dream() 使用）。"""
        if self.drive:
            d = self.drive.desire
            return (
                f"归属欲：{d.belonging:.2f}，"
                f"认知欲：{d.cognition:.2f}，"
                f"成就欲：{d.achievement:.2f}，"
                f"表达欲：{d.expression:.2f}"
            )
        return ""

    def _get_internal_text(self) -> str:
        """获取近况自述文本（供 L3Engine.burn_dream() 使用）。"""
        si = self.cs.self_image
        history = si.history
        return "".join(filter(None, [
            history.emotional_trajectory,
            history.goal_rhythm,
            history.consciousness_rhythm,
        ])) or "无"
