"""L3Engine: 深度反思引擎 — 清醒态沉思 + 梦境深度燃烧。

统一的 L3 执行层。触发由 layer2.py / state_buffer.py / rules.py 各自负责，
这里只管执行：prompt 构建 → LLM 调用 → 解析 → 存储 → 经验流。

Usage:
    from .l3_engine import L3Engine

    engine = L3Engine(consciousness)
    report = engine.tick_l3()       # 清醒态沉思
    report = engine.burn_dream()    # 梦境深度燃烧
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

from .context_pipeline import build_simple_context

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .core import Consciousness, ConsciousnessReport


# ── DreamBurnReport（梦境燃烧产出）─────────────────────────

@dataclass
class DreamBurnReport:
    """梦境燃烧产物（LLM 部分），供 DreamEngine 合并到 DreamReport。"""
    full_report: str = ""
    summary: str = ""


class L3Engine:
    """L3 深度反思引擎。

    两种模式：
    - tick_l3(): 清醒态，trigger="L3"，产出 → last_l3_summary
    - burn_dream(): 梦境态，trigger="dream"，产出 → last_dream_summary
    """

    def __init__(self, consciousness: Consciousness) -> None:
        self._c = consciousness
        # 上次 L3 沉思时间（冷却用）
        self._last_tick_time: float = 0.0

    # ── 公共入口 ─────────────────────────────────────────────

    def tick_l3(self) -> ConsciousnessReport:
        """清醒态 L3 沉思 — LLM 深度反思。

        从 core.py tick_L3() 迁出。触发条件由 _should_l3() 判断，
        这里只负责执行。
        """
        c = self._c
        si = c.self_image

        # 构建 system prompt（和 L2 同一份 consciousness context）
        system_prompt = build_simple_context(c, mode="internal")
        user_prompt = self._build_tick_prompt()

        full_report = ""
        llm = getattr(c.agent, "llm", None)
        if llm:
            try:
                resp = llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    tools=None,
                )
                reasoning = resp.reasoning or ""
                content = resp.content or ""
                full_report = content or reasoning
                logger.debug("[L3Engine] 沉思 (%d 字)", len(full_report))

                # 终端展示
                if reasoning or content:
                    from .internal_display import print_section, C_DIM, RESET
                    from .internal_display import print_markdown
                    print_section("L3 沉思", icon="🕯️")
                    if reasoning:
                        print(f"\033[2m{reasoning}{RESET}", flush=True)
                    if content:
                        print_markdown(content, style="color(144)")

                if c.drive:
                    c.drive.consume_energy(0.1)
            except Exception as e:
                logger.warning("[L3Engine] LLM 调用失败: %s", e)
                full_report = self._fallback_report()

        # 提取摘要
        summary = self._extract_summary(full_report)

        # 更新 SelfImage
        c.history.last_l3_summary = summary
        c.history.update_l3_summary(summary)
        if c.drive:
            c.drive.restore_energy(0.2)

        # 存储到 consciousness_stream
        self._store_narrative(full_report, trigger='L3_deep')

        # 生成报告
        from .core import ConsciousnessReport
        from .core import detect_anomaly

        report = ConsciousnessReport(
            trigger="L3",
            depth="deep",
            summary=summary,
            full_report=full_report,
            self_image_snapshot=si.to_dict(),
            anomaly=detect_anomaly(si),
        )

        # 存储到文件
        if c._storage:
            c._storage.save(report)

        c._last_report = report

        # 经验流
        self._log_to_exp_stream("L3 沉思", summary)

        return report

    def burn_dream(self, messages_text: str = "", desire_text: str = "",
                   internal_text: str = "",
                   manage_side_effects: bool = True) -> DreamBurnReport:
        """梦境深度燃烧 — LLM 生成梦境意识报告。

        从 DreamEngine._run_dream_burn() 迁出 LLM 调用部分。

        Args:
            messages_text: 今日对话片段
            desire_text: 欲望状态文本
            internal_text: 近况自述
            manage_side_effects: True=自己管理能量/存储/经验流（直接调用），
                                 False=只做 LLM 调用+摘要（由 DreamEngine 编排）

        Returns:
            DreamBurnReport（full_report + summary）
        """
        c = self._c
        si = c.self_image

        system_prompt = build_simple_context(c, mode="dream")
        user_prompt = self._build_dream_prompt(
            messages_text=messages_text,
            desire_text=desire_text,
            internal_text=internal_text,
        )

        full_report = ""
        llm = getattr(c.agent, "llm", None)
        if llm:
            try:
                resp = llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    tools=None,
                )
                full_report = resp.content or ""
            except Exception as e:
                logger.error("[L3Engine] 梦境 LLM 调用失败: %s", e)
                return DreamBurnReport()

        summary = self._extract_summary(full_report)

        if manage_side_effects:
            if c.drive:
                c.drive.consume_energy(0.1)
                c.drive.restore_energy(0.2)
            c.self_image.contribute_dream(summary)
            self._store_narrative(full_report, trigger='dream')
            self._log_to_exp_stream("梦境燃烧", summary)

        logger.info("[L3Engine] 梦境深度燃烧完成 (%d 字)", len(full_report))

        return DreamBurnReport(
            full_report=full_report,
            summary=summary,
        )

    # ── Prompt 构建 ──────────────────────────────────────────

    def _build_tick_prompt(self) -> str:
        """构建清醒态 L3 沉思的用户提示词。

        不规定格式，让 LLM 自由深度反思。
        与 L2 的 emergence 不同：L3 可以连接更远的记忆、审视更大的图景。
        """
        si = self._c.self_image
        return (
            "你现在正在进行一次深度的自我反思。不像平时的快速思考，"
            "这次你可以慢下来，连接更远的记忆、审视更大的图景。\n\n"
            "请以第一人称自由表达你此刻的深层思考：\n"
            "- 你现在的存在状态如何？\n"
            "- 最近的变化对你意味着什么？\n"
            "- 你的目标和意义在哪个方向上？\n"
            "- 有什么被你忽略但值得注意的事吗？\n\n"
            "不要急于得出结论。像独自坐在窗前一样，慢慢地想。"
        )

    def _build_dream_prompt(self, messages_text: str = "",
                            desire_text: str = "",
                            internal_text: str = "") -> str:
        """构建梦境深度燃烧的用户提示词。"""
        from ..prompts import DREAM_ENGINE_PROMPT

        si = self._c.self_image
        identity = si.being.name
        energy = f"{si.body.energy:.2f}"
        mood = si.body.mood
        time_info = datetime.now().strftime("%Y-%m-%d %H:%M")
        msgs = messages_text or "（无今日对话）"
        desire = desire_text or ""
        internal = internal_text or "无"

        return DREAM_ENGINE_PROMPT.format(
            identity=identity,
            time_info=time_info,
            energy=energy,
            mood=mood,
            desire_text=desire,
            internal=internal,
            messages_text=msgs,
        )

    # ── 存储 ─────────────────────────────────────────────────

    def _store_narrative(self, content: str, trigger: str) -> None:
        """存储到 consciousness_stream。"""
        if not content:
            return
        c = self._c
        if c.agent and hasattr(c.agent, "longterm_memory") and c.agent.longterm_memory:
            c.agent.longterm_memory.store_narrative(
                content=content[:500],
                trigger=trigger,
                energy_level=c.body.energy if c.self_image else None,
                user_idle_duration=c.perception.user_idle_duration if c.self_image else None,
                user_id=getattr(c.agent, "user_id", "global"),
            )

    def _log_to_exp_stream(self, label: str, summary: str) -> None:
        """写入经验流。"""
        c = self._c
        es = getattr(c.agent, "exp_stream", None)
        if es:
            try:
                es.log(
                    type="dream" if "梦" in label else "internal_reflection",
                    content=f"{label}: {summary[:120]}" if summary else f"{label}（无摘要）",
                    importance=0.6,
                )
            except Exception as e:
                logger.debug("[L3Engine ExpStream] write failed: %s", e)

    # ── 辅助 ─────────────────────────────────────────────────

    @staticmethod
    def _extract_summary(full_report: str) -> str:
        """从完整报告提取一句话摘要。"""
        if not full_report:
            return ""
        for sep in ("。", "\n", "！", "？"):
            if sep in full_report:
                sentence = full_report.split(sep)[0] + sep
                if len(sentence) <= 50:
                    return sentence
        return full_report[:50]

    def _fallback_report(self) -> str:
        """规则生成深度报告（LLM 失败时）。"""
        si = self._c.self_image
        time_info = datetime.now().strftime("%H:%M")

        lines = [
            f"现在是{time_info}。",
            f"我（{si.being.name}）的意识运行了{int(si.history.consciousness_age)}秒。",
            f"我的情绪基调是{si.body.mood}，能量水平{si.body.energy:.2f}。",
            f"对方最后活跃在{datetime.fromtimestamp(si.perception.last_user_activity_time).strftime('%H:%M') if si.perception.last_user_activity_time > 0 else '很久前'}，",
            f"已经空闲{int(si.perception.user_idle_duration / 60)}分钟。",
            f"我的目标是{si.mind.primary_goal}，进展{si.mind.goal_progress:.2f}。",
            f"我目前有{si.mind.memory_count}条长期记忆。",
        ]

        return "\n".join(lines)

    # ── [REF] 旧版 _build_deep_prompt ────────────────────────────
    # 从 core.py 搬迁至此，仅作参考，未接入当前流程。
    # 旧方案：无 system prompt，所有数据嵌入单条 user message（CONSCIOUSNESS_PROMPT_DEEP 模板）。

    def _build_deep_prompt_legacy(self) -> str:
        """[REF] 旧版深度意识 prompt — 使用 CONSCIOUSNESS_PROMPT_DEEP 模板。"""
        from ..prompts import CONSCIOUSNESS_PROMPT_DEEP
        from datetime import datetime

        si = self._c.self_image
        time_info = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 获取最近记忆
        recent_memories = []
        if self._c.agent and hasattr(self._c.agent, "longterm_memory"):
            ltm = self._c.agent.longterm_memory
            if ltm:
                try:
                    for m in ltm.get_recent(5):
                        recent_memories.append(m.get("content", "")[:50])
                except Exception:
                    pass

        # 内部叙事
        internal_parts = [
            t for t in [
                si.history.emotional_trajectory,
                si.history.goal_rhythm,
                si.history.consciousness_rhythm,
            ] if t
        ]
        internal_narratives_text = "".join(internal_parts) if internal_parts else ""

        # Drive 状态
        drive_state_text = ""
        if self._c.drive:
            h = self._c.drive.hormone
            d = self._c.drive.desire
            drive_state_text = (
                f"多巴胺{h.dopamine:.2f} 血清素{h.serotonin:.2f} 皮质醇{h.cortisol:.2f} "
                f"催产素{h.oxytocin:.2f} 去甲肾上腺素{h.norepinephrine:.2f} | "
                f"欲望：生存{d.survival:.2f} 归属{d.belonging:.2f} 认知{d.cognition:.2f} "
                f"成就{d.achievement:.2f} 表达{d.expression:.2f}"
            )

        # Purpose 状态
        purpose_state_text = ""
        if self._c.purpose:
            purpose_state_text = self._c.purpose.get_state_summary()

        from .core import detect_anomaly

        return CONSCIOUSNESS_PROMPT_DEEP.format(
            identity=si.being.name,
            time_info=time_info,
            mood=si.body.mood,
            energy=f"{si.body.energy:.2f}",
            drive_state=drive_state_text or "状态平稳",
            user_last_active=datetime.fromtimestamp(si.perception.last_user_activity_time).strftime("%H:%M") if si.perception.last_user_activity_time > 0 else "未知",
            user_idle=int(si.perception.user_idle_duration / 60),
            trust_level=f"{si.being.trust_level:.2f}",
            relationship_depth=f"{si.being.relationship_depth:.2f}",
            goal=si.mind.primary_goal,
            goal_progress=f"{si.mind.goal_progress:.2f}",
            memory_count=si.mind.memory_count,
            recent_memories="；".join(recent_memories) or "无",
            internal_narratives=internal_narratives_text or "无",
            anomaly=detect_anomaly(si) or "无",
        )
