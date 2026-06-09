"""SocialCognition: 社会认知 + 心理理论引擎。

从 L2 意识涌现中拆出，独立 LLM 调用，对话驱动。
人类 DMN 中"社会认知/心理理论"子功能的对应实现。

与 InnerVoice 的分工：
- InnerVoice：轻量/高频（每≥2轮），快速直觉 + 事件维度 + 社交信号
- SocialCognition：对话驱动/中频（L2 tick），深度社会感知 + Drive 事件 + 叙事

输入：consciousness 上下文 + 最近对话
输出：
- EVENTS → Drive（praise/criticism/goal/curiosity/expression）
- PERCEPTION → SelfImage.mind.social_perceptions
- SIGNAL → Drive + relationship_engine
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..consciousness.context_pipeline import build_simple_context
from xiaomei_brain.prompts import SOCIAL_COGNITION_PROMPT

logger = logging.getLogger(__name__)

# 社交信号类型（与 InnerVoice / l2_engine 保持一致）
SOCIAL_SIGNAL_TYPES = [
    "user_low_mood", "user_enthusiastic", "user_cold",
    "user_angry", "user_happy", "user_stressed", "user_trusting",
]


class SocialCognition:
    """社会认知引擎——对话后深度社会感知。

    自己的 LLM 调用，不共享 L2 的 LLM 响应。
    由 Layer2/DMN 线程调度，与意图/涌现/L3 同级。
    """

    def __init__(
        self,
        llm: Any = None,
        self_image: Any = None,
        consciousness: Any = None,
        drive: Any = None,
        exp_stream: Any = None,
        longterm_memory: Any = None,
        user_id: str = "global",
    ) -> None:
        self._llm = llm
        self._self_image = self_image
        self._consciousness = consciousness
        self._drive = drive
        self._exp_stream = exp_stream
        self._longterm_memory = longterm_memory
        self._user_id = user_id

    # ── 公共入口 ──────────────────────────────────────────────

    def reflect(self, context: str = "", user_name: str = "对方",
                recent_conversation: str = "") -> str | None:
        """执行一次社会认知反思。

        Args:
            context: 触发上下文（如 "dialogue_driven"、"periodic"）
            user_name: 用户显示名称
            recent_conversation: 最近对话文本（由调用方从 ConversationDB 查询传入）

        Returns:
            LLM 原始响应文本，或 None（调用失败）
        """
        if not self._llm or not self._self_image:
            return None

        # 构建 prompt
        prompt = self._build_prompt(context, user_name, recent_conversation)
        if not prompt:
            return None

        # 调用 LLM
        raw = self._call_llm(prompt)
        if not raw:
            return None

        # 解析响应
        self._parse_and_route(raw)

        return raw

    # ── Prompt 构建 ───────────────────────────────────────────

    def _build_prompt(self, context: str, user_name: str,
                      recent_conversation: str = "") -> str | None:
        """构建 social_cognition prompt。

        包含：consciousness 上下文 + 最近对话 + EVENTS/PERCEPTION/SIGNAL 要求。
        """
        consciousness_context = build_simple_context(self._consciousness, mode="daily")

        recent = recent_conversation or self._get_recent_conversation()
        if not recent or recent == "（无对话数据）":
            return None  # 没有对话就不触发，纯对话驱动

        return SOCIAL_COGNITION_PROMPT.format(
            consciousness_context=consciousness_context,
            user_name=user_name,
            recent=recent,
        )

    def _get_recent_conversation(self) -> str:
        """获取最近对话文本（fallback：从 SelfImage.memory.recent_dialog）。"""
        si = self._self_image
        if si:
            recent_dialog = getattr(si.memory, "recent_dialog", [])
            if recent_dialog:
                lines = []
                for d in recent_dialog:
                    role = d.get("role", "")
                    content = d.get("content", "")
                    if content:
                        label = "对方" if role == "user" else ("我" if role == "assistant" else role)
                        lines.append(f"{label}：{content[:200]}")
                if lines:
                    return "\n".join(lines)

        return "（无对话数据）"

    # ── LLM 调用 ──────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str | None:
        """调用 LLM。"""
        if not self._llm:
            return None
        try:
            response = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            if response and hasattr(response, "content"):
                return (response.content or "").strip()
        except Exception as e:
            logger.warning("[SocialCognition] LLM 调用失败: %s", e)
        return None

    # ── 解析与路由 ────────────────────────────────────────────

    def _parse_and_route(self, raw: str) -> None:
        """解析 LLM 响应并路由到各子系统。"""
        # 1. 分离 EVENTS
        _, events_json = self._split_events(raw)

        # 2. 分离 PERCEPTION
        _, perceptions = self._split_perception(raw)

        # 3. 分离 SIGNAL
        _, signal_json = self._split_signal(raw)

        # 路由 SIGNAL → Drive + relationship_engine（先执行——感知用户情绪）
        if signal_json and self._drive:
            try:
                self._apply_social_signal(signal_json)
            except Exception as e:
                logger.warning("[SocialCognition] SIGNAL 应用失败: %s", e)

        # 路由 EVENTS → Drive（后执行——边界侵犯等覆盖社交信号）
        if events_json and self._drive:
            try:
                self._apply_drive_events(events_json)
            except Exception as e:
                logger.warning("[SocialCognition] EVENTS 应用失败: %s", e)

        # 路由 PERCEPTION → SelfImage.mind.social_perceptions
        if perceptions:
            try:
                self._self_image.contribute_social_perception(perceptions)
            except Exception as e:
                logger.warning("[SocialCognition] PERCEPTION 写入失败: %s", e)

        # 写入 ExpStream
        if self._exp_stream:
            try:
                parts = ["[social_cognition]"]
                if events_json:
                    parts.append(f"EVENTS: {events_json[:200]}")
                if perceptions:
                    parts.append(f"PERCEPTIONS: {len(perceptions)}条")
                if signal_json:
                    parts.append(f"SIGNAL: {signal_json[:200]}")
                self._exp_stream.log(
                    type="internal_reflection",
                    content=" | ".join(parts),
                    importance=0.5,
                    metadata={"source": "social_cognition"},
                )
            except Exception as e:
                logger.debug("[SocialCognition] ExpStream 写入失败: %s", e)

        logger.info(
            "[SocialCognition] 完成: events=%s, perceptions=%d, signal=%s",
            bool(events_json), len(perceptions), bool(signal_json),
        )

    # ── 分隔符解析（从 l2_engine.py 搬过来）──────────────────

    @staticmethod
    def _split_events(text: str) -> tuple[str, str]:
        """分离 ---EVENTS--- JSON。"""
        if "---EVENTS---" in text:
            parts = text.split("---EVENTS---", 1)
            return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
        return text, ""

    @staticmethod
    def _split_signal(text: str) -> tuple[str, str]:
        """分离 ---SIGNAL--- JSON。"""
        if "---SIGNAL---" not in text:
            return text, ""

        idx = text.index("---SIGNAL---")
        signal_content = text[idx + len("---SIGNAL---"):].strip()
        clean_text = text[:idx].strip()
        return clean_text, signal_content

    @staticmethod
    def _split_perception(text: str) -> tuple[str, list[dict]]:
        """分离 ---PERCEPTION--- 感知列表。"""
        if "---PERCEPTION---" not in text:
            return text, []

        idx = text.index("---PERCEPTION---")
        after_marker = text[idx + len("---PERCEPTION---"):]

        # 找到下一个分隔符
        next_pos = None
        for sep in ["---EVENTS---", "---SIGNAL---"]:
            pos = after_marker.find(sep)
            if pos != -1 and (next_pos is None or pos < next_pos):
                next_pos = pos

        perception_content = after_marker[:next_pos] if next_pos is not None else after_marker

        perceptions = []
        for line in perception_content.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if content:
                    perceptions.append({
                        "content": content,
                        "time": time.time(),
                    })

        return "", perceptions

    # ── Drive 事件应用（从 l2_engine.py 搬过来）──────────────

    def _apply_drive_events(self, events_text: str) -> None:
        """从 EVENTS JSON 解析语义事件并应用到 Drive。"""
        try:
            json_match = re.search(r"\{[\s\S]*\}", events_text)
            if json_match:
                events = json.loads(json_match.group())
            else:
                logger.warning("[SocialCognition] EVENTS 未找到 JSON: %.100s", events_text)
                return
        except json.JSONDecodeError:
            logger.warning("[SocialCognition] EVENTS JSON 解析失败: %.100s", events_text)
            return

        praise = events.get("praise_intensity", 0)
        criticism = events.get("criticism_intensity", 0)
        goal_progress = events.get("goal_progress", 0)
        boundary = events.get("boundary_violation", 0)

        if praise > 0.1:
            self._drive.on_praise(min(praise, 1.0))
        if criticism > 0.1:
            self._drive.on_criticism(min(criticism, 1.0))
        if goal_progress > 0.1:
            self._drive.on_goal_progress(min(goal_progress, 1.0))
        if boundary > 0.3:
            from xiaomei_brain.drive.state import EmotionType
            self._drive.emotion.type = EmotionType.ANGER
            self._drive.emotion.intensity = min(1.0, boundary * 0.9)
            self._drive.emotion.created_at = time.time()
            self._drive.emotion.duration = self._drive.config.emotion.get_duration("anger")
            self._drive.hormone.cortisol = min(1.0, self._drive.hormone.cortisol + boundary * 0.2)
            self._drive.hormone.norepinephrine = min(1.0, self._drive.hormone.norepinephrine + boundary * 0.15)
            self._drive.hormone.last_updated = time.time()

        curiosity = events.get("curiosity_sparked", 0)
        expression = events.get("expression_urge", 0)

        if curiosity > 0.3:
            self._drive.on_curiosity(curiosity * 0.08)
        if expression > 0.3:
            self._drive.on_insight(expression * 0.1)

        # 写入内部记忆
        summary = events.get("summary", "")
        tags = ["social_cognition", "drive_events"]
        if praise > 0.1:
            tags.append("joy")
        if criticism > 0.1:
            tags.append("sadness")
        if curiosity > 0.3:
            tags.append("curiosity_sparked")
        if expression > 0.3:
            tags.append("expression_urge")
        if goal_progress > 0.1:
            tags.append("goal_progress")
        if boundary > 0.3:
            tags.append("boundary_violation")

        parts = []
        if praise > 0.1:
            parts.append(f"对方表扬了我（强度{praise:.1f}）")
        if criticism > 0.1:
            parts.append(f"对方批评了我（强度{criticism:.1f}）")
        if curiosity > 0.3:
            parts.append("对话激发了我的好奇心")
        if expression > 0.3:
            parts.append("我有表达的欲望")
        if goal_progress > 0.1:
            parts.append(f"目标有进展（{goal_progress:.1f}）")
        if boundary > 0.3:
            parts.append(f"对方越界/冒犯了我（强度{boundary:.1f}）")
        if summary:
            parts.append(summary)
        content = "；".join(parts) if parts else summary or "social_cognition 事件分析"

        if self._longterm_memory:
            try:
                self._longterm_memory.store_narrative(
                    content=content[:300],
                    trigger='social_cognition',
                    drive_summary=json.dumps(tags),
                    user_id=self._user_id,
                )
            except Exception as e:
                logger.debug("[SocialCognition] 记忆写入失败: %s", e)

        logger.info(
            "[SocialCognition] EVENTS: praise=%.2f, criticism=%.2f, goal_progress=%.2f, "
            "curiosity=%.2f, expression=%.2f, boundary=%.2f, tags=%s",
            praise, criticism, goal_progress, curiosity, expression, boundary, tags,
        )

    def _apply_social_signal(self, signal_text: str) -> None:
        """从 SIGNAL JSON 解析社交信号并应用到 Drive + relationship_engine。"""
        if not self._drive:
            return

        try:
            json_match = re.search(r"\{[\s\S]*\}", signal_text)
            if not json_match:
                return
            signal = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning("[SocialCognition] SIGNAL JSON 解析失败: %.100s", signal_text)
            return

        signal_type = signal.get("social_signal", "")
        intensity = float(signal.get("intensity", 0))

        if signal_type and intensity > 0.1:
            try:
                self._drive.apply_social_signal(signal_type, min(intensity, 1.0))
                logger.info(
                    "[SocialCognition] SIGNAL: %s (intensity=%.2f)",
                    signal_type, intensity,
                )
            except Exception as e:
                logger.warning("[SocialCognition] SIGNAL 应用失败: %s", e)

            # 同步到关系引擎（trust 变化）
            if self._self_image:
                engine = getattr(self._self_image.being, '_relationship_engine', None)
                if engine:
                    try:
                        engine.on_social_signal(signal_type, min(intensity, 1.0))
                    except Exception as e:
                        logger.debug("[SocialCognition] 关系引擎应用失败: %s", e)
