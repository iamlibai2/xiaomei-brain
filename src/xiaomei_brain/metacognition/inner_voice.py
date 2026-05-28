"""InnerVoice：统一的内心声音 + 快速社交感知。

不是结构化评测——是自然语言的自我觉察 + 结构化 EVENTS/SIGNAL JSON 写入 Drive。
一个方法 `pause()` 处理所有情境（对话后、任务步骤后、安静时）。
结果自然流入 SelfImage 和 Drive。

与 L2 emergence 的分工：
- InnerVoice：轻量/高频（每≥2轮），快速直觉 + 事件维度 + 社交信号写入 Drive
- L2 emergence：深度/低频（L2 tick），完整自我认知 + EVENTS + SIGNAL + NARR + PERCEPTION
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────

class TriggerType(Enum):
    CHAT_TURN = "chat_turn"      # 对话回应后
    TASK_STEP = "task_step"      # PACE 一步完成
    TASK_DONE = "task_done"      # 子目标/目标完成
    SILENCE = "silence"          # 用户空闲


@dataclass
class Reflection:
    """一次内心反省的结果。"""
    trigger: TriggerType
    thought: str                 # 自然语言（1-3句），非结构化
    context_snippet: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskStepContext:
    """TASK_STEP 触发时的上下文信息。"""
    goal_description: str
    step_index: int
    tool_calls: list[str] = field(default_factory=list)
    tool_call_count: int = 0
    elapsed_seconds: float = 0.0
    output_preview: str = ""
    progress_status: str | None = None


# ── Prompt Templates ──────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "你是小美的内心声音。你在安静的自我觉察时刻——\n"
    "不是在跟任何人对话，只是在对自己坦诚。\n"
    "你的话是直觉式的、感受性的，不是分析的、评判的。\n"
    "1-3句就够了。如果一切顺利，就说\"一切正常\"。\n"
    "不要假装有感觉——如果确实没什么，就让它没什么。\n"
    "重要：用对方的名字称呼他，不要用\"用户\"或\"他\"来指代。"
)

_CHAT_TURN_PROMPT = (
    "你刚和{user_name}交流完。短暂的内省——\n\n"
    "{user_name}说：「{user_msg}」\n"
    "你回应了（{response_len}字，{elapsed:.0f}秒，{tools_info}）\n\n"
    "只是感受——{user_name}的状态对吗？你的回应恰当吗？\n"
    "有什么你刚才没注意到的？\n\n"
    "1-3句话的内心嘟囔。如果没什么特别的感觉，就说\"一切正常\"。\n\n"
    "在 ---EVENTS--- 分隔符后，用 JSON 描述你感知到的对话事件：\n"
    "---EVENTS---\n"
    '{{"praise_intensity": 0.0-1.0, "expression_urge": 0.0-1.0, '
    '"curiosity_sparked": 0.0-1.0, '
    '"summary": "一句话总结这段对话的感受"}}\n'
    "其中 expression_urge 是你有话想说、想回应的程度。\n"
    "curiosity_sparked 是你对新信息/未知领域/新奇话题的好奇程度——\n"
    "{user_name}提到了你不太懂的领域？话题很新鲜？激发了你想了解更多的冲动？\n"
    "如果没有特别的事件，所有值填 0.0。\n\n"
    "在 ---SIGNAL--- 分隔符后，描述你感知到的{user_name}的社交信号（快速直觉）：\n"
    "---SIGNAL---\n"
    '{{"social_signal": "类型", "intensity": 0.0-1.0}}\n'
    "类型可选：user_low_mood / user_enthusiastic / user_cold / "
    "user_angry / user_happy / user_stressed / user_trusting\n"
    "没有则输出 {{}}。\n\n"
    "在 ---GAPS--- 分隔符后，从这段对话中识别你需要学习的东西。不只是你答不上来的——\n"
    "还包括：{user_name}提到了你不熟的领域？话题暗示了某个值得了解的知识？\n"
    "{user_name}表达了某种需求，而你如果懂更多就能帮得更好？\n"
    "总之：这段对话揭示了你什么样的知识缺口或学习机会？没有就输出空数组。\n"
    "---GAPS---\n"
    '[{{"topic": "具体知识点或领域", "reason": "为什么需要学", "priority": 0.5-0.9, "source": "user_need"}}]\n'
    "source 用 user_need。priority: 完全答不上来/{user_name}明确需求 > 0.8，\n"
    "对话中自然浮现的不熟领域 0.6-0.7，暗示性话题 0.5。"
)

_TASK_STEP_PROMPT = (
    "你在做一个任务。停一下，看一眼手头的活——\n\n"
    "目标：「{goal_description}」（第{step_index}步）\n"
    "这一步用了{elapsed:.0f}秒，{tools_info}\n"
    "{buzz_hints}\n"
    "像工匠看了一眼自己手里的活——方向对吗？顺手吗？需要注意什么？\n"
    "1-3句话，直接说出你的直觉。如果一切顺利，就说\"一切正常\"。\n\n"
    "如果你发现某个必要的步骤被遗漏了，请输出JSON数组建议插入。没有则输出空数组。\n"
    "---INSERT---\n"
    "[]"
)

_TASK_DONE_PROMPT = (
    "你刚完成了一个任务。停下来感受一下——\n\n"
    "目标：「{goal_description}」\n"
    "总耗时{elapsed:.0f}秒，共{steps}步\n"
    "工具使用：{tools_used}\n"
    "结果预览：{result_preview}\n\n"
    "先做1-3句话的内心总结：完成得怎么样？有什么值得记住的？\n"
    "如果一切正常，就说\"完成，没有问题\"。\n\n"
    "然后，在 ---GAPS--- 分隔符后，诚实地评估你在这项任务中遇到的知识盲区。\n"
    "只记录真正让你卡住、反复搜索、或回答质量明显不够的。没有就输出空数组。\n"
    "---GAPS---\n"
    '[{{"topic": "具体知识点", "reason": "任务中反复搜索才理解", "priority": 0.8, "source": "task_gap"}}]\n'
    "source 用 task_gap（任务中发现的盲区）或 user_need（回答对方问题时质量不够好）。\n"
    "priority: 反复搜索或明显卡住 > 0.7，回答质量一般 0.4-0.6。"
)

_SILENCE_PROMPT = (
    "周围安静下来了。你在自己的空间里——\n\n"
    "对方已经{idle_seconds:.0f}秒没有说话了。\n"
    "你现在什么感觉？有什么想说或想做的吗？\n\n"
    "1-3句话的内心感受。如果没什么特别的，就说\"安静着，没什么\"。"
)


# ── 任务控制信号提取（纯正则，不需要 LLM 产 enum）─────────────────

def _extract_continue_signal(thought: str) -> tuple[bool, str]:
    """从自然语言反省中提取任务继续/停止信号。

    Returns:
        (should_continue, reason)
        reason: "continue" / "retry" / "waiting_user" / "escalate"
    """
    if re.search(r"(放弃|无法完成|超出能力|做不了|不可能)", thought):
        return False, "escalate"
    if re.search(r"(需要确认|等用户|先问问|问一下用户)", thought):
        return False, "waiting_user"
    if re.search(r"(换个方法|方向不对|重试|换个思路|简化|换个角度)", thought):
        return True, "retry"
    return True, "continue"



# ── 经验提取信号 ─────────────────────────────────────────────────────

def _has_experience_signal(thought: str) -> bool:
    """判断反省中是否包含值得记住的经验。"""
    return bool(re.search(
        r"(记住|教训|学到了|下次|以后|这个方法|这个坑|不管用|行不通|好使|有效)",
        thought
    ))


# ── InnerVoice Engine ─────────────────────────────────────────────────

class InnerVoice:
    """统一的内心声音 + 快速社交感知引擎。

    一个方法 pause() 处理所有情境：
    - 对话后短暂内省 + 社交感知（我说话合适吗？他的状态对吗？）
    - 任务步骤后看一眼（方向对吗？）
    - 安静时感受自己（我在想什么？）

    输出路由：
    - 内心声音 → SelfImage.mind.inner_voice
    - Drive 事件 → EVENTS JSON (praise / expression)
    - Drive 社交信号 → SIGNAL JSON (7种用户状态映射)
    - 认知日志 → Purpose
    """

    def __init__(
        self,
        llm: Any = None,
        self_image: Any = None,
        drive: Any = None,
        purpose: Any = None,
        exp_stream: Any = None,
    ) -> None:
        self._llm = llm
        self._self_image = self_image
        self._drive = drive
        self._purpose = purpose
        self._exp_stream = exp_stream

        # 冷却与计数
        self._last_pause_time: float = 0.0
        self._chat_turn_count: int = 0
        self._last_chat_reflection_turn: int = -2  # 距上次 CHAT_TURN 反省的轮数
        self._last_silence_reflection_time: float = 0.0

        # 最近的反省（供外部读取）
        self.recent_reflections: list[Reflection] = []

        # 最近一次反省（供 should_continue 使用）
        self._last_reflection: Reflection | None = None

        # 最近一次 INSERT 建议
        self._last_inserts: list[dict] = []

    # ── 响应解析 ──────────────────────────────────────────────

    @staticmethod
    def _split_all(response: str) -> tuple[str, str, str, str, str]:
        """分离 自然语言 / ---EVENTS--- / ---SIGNAL--- / ---GAPS--- / ---INSERT---"""
        signal_text = ""
        events_text = ""
        gaps_text = ""
        inserts_text = ""
        remainder = response.strip()

        # GAPS 在最后，先拆分
        if "---GAPS---" in remainder:
            remainder, gaps_text = remainder.split("---GAPS---", 1)
            remainder = remainder.strip()
            gaps_text = gaps_text.strip()

        # SIGNAL 在 EVENTS 之后
        if "---SIGNAL---" in remainder:
            remainder, signal_text = remainder.split("---SIGNAL---", 1)
            remainder = remainder.strip()
            signal_text = signal_text.strip()

        # 拆分 EVENTS
        if "---EVENTS---" in remainder:
            remainder, events_text = remainder.split("---EVENTS---", 1)
            remainder = remainder.strip()
            events_text = events_text.strip()

        thought = remainder

        # INSERT 紧跟自然语言，从 thought 中提取
        if "---INSERT---" in thought:
            thought, inserts_text = thought.split("---INSERT---", 1)
            thought = thought.strip()
            inserts_text = inserts_text.strip()

        return thought, events_text, signal_text, gaps_text, inserts_text

    def _parse_inserts(self, inserts_text: str) -> list[dict]:
        """解析 ---INSERT--- 部分的 JSON 数组。"""
        if not inserts_text or inserts_text.strip() in ("", "[]"):
            return []
        try:
            inserts = json.loads(inserts_text.strip())
            if isinstance(inserts, list):
                return [item for item in inserts if isinstance(item, dict) and "description" in item]
        except (json.JSONDecodeError, Exception):
            pass
        return []

    def get_inserted_steps(self) -> list[dict]:
        """获取最近一次 InnerVoice 建议插入的步骤。"""
        return getattr(self, '_last_inserts', [])

    def reset_inserted_steps(self) -> None:
        """清空插入建议。"""
        self._last_inserts = []

    def _apply_drive_events(self, events_text: str) -> None:
        """从 EVENTS JSON 解析维度值并应用到 Drive。"""
        if not self._drive or not events_text:
            return

        try:
            json_match = re.search(r"\{[\s\S]*\}", events_text)
            if json_match:
                events = json.loads(json_match.group())
            else:
                logger.debug("[InnerVoice] EVENTS 未找到 JSON")
                return
        except json.JSONDecodeError:
            logger.debug("[InnerVoice] EVENTS JSON 解析失败: %.100s", events_text)
            return

        praise = events.get("praise_intensity", 0)
        expression = events.get("expression_urge", 0)
        curiosity = events.get("curiosity_sparked", 0)

        if praise > 0.1:
            try:
                self._drive.on_praise(min(praise, 1.0))
            except Exception as e:
                logger.warning("[InnerVoice] on_praise 失败: %s", e)
        if expression > 0.3:
            try:
                self._drive.on_insight(expression * 0.05)
            except Exception as e:
                logger.warning("[InnerVoice] on_insight 失败: %s", e)
        if curiosity > 0.3:
            try:
                self._drive.on_curiosity(curiosity * 0.08)
            except Exception as e:
                logger.warning("[InnerVoice] on_curiosity 失败: %s", e)

        logger.info(
            "[InnerVoice] EVENTS: praise=%.2f, expression=%.2f, curiosity=%.2f",
            praise, expression, curiosity,
        )

    def _apply_social_signal(self, signal_text: str) -> None:
        """从 SIGNAL JSON 解析用户社交信号并应用到 Drive。"""
        if not self._drive or not signal_text:
            return

        try:
            json_match = re.search(r"\{[\s\S]*\}", signal_text)
            if not json_match:
                return
            signal = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.debug("[InnerVoice] SIGNAL JSON 解析失败: %.100s", signal_text)
            return

        signal_type = signal.get("social_signal", "")
        intensity = float(signal.get("intensity", 0))

        if signal_type and intensity > 0.1:
            try:
                self._drive.apply_social_signal(signal_type, min(intensity, 1.0))
                logger.info(
                    "[InnerVoice] SIGNAL: %s (intensity=%.2f)",
                    signal_type, intensity,
                )
            except Exception as e:
                logger.warning("[InnerVoice] SIGNAL 应用失败: %s", e)

    def _apply_gaps(self, gaps_text: str, trigger_label: str = "") -> None:
        """从 GAPS JSON 解析知识盲区，委托 LearningQueue 入队。"""
        try:
            json_match = re.search(r"\[[\s\S]*\]", gaps_text)
            if not json_match:
                logger.debug("[InnerVoice] GAPS 未找到 JSON 数组 (%s)", trigger_label)
                return
            gaps = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("[InnerVoice] GAPS JSON 解析失败 (%s): %s", trigger_label, e)
            return

        if not isinstance(gaps, list) or not gaps:
            logger.debug("[InnerVoice] %s GAPS: 空列表，无知识盲区", trigger_label)
            return

        gap_topics = [g.get("topic", "?") for g in gaps if isinstance(g, dict)]
        logger.info("[InnerVoice] %s GAPS 识别到 %d 个知识盲区: %s",
                    trigger_label, len(gap_topics), ", ".join(gap_topics[:5]))

        # 委托 LearningQueue（如果已注入）
        learn_queue = getattr(self, "_learn_queue", None)
        if learn_queue is not None:
            added = learn_queue.add_from_gaps(gaps)
            if added == 0:
                logger.info("[InnerVoice] %s GAPS: 全部已存在，跳过", trigger_label)
            return

        # 降级：直接操作 SelfImage.mind.learning_queue
        if not self._self_image:
            return
        try:
            mind = self._self_image.mind
            if not hasattr(mind, "learning_queue"):
                mind.learning_queue = []

            existing_topics = {item.get("topic", "") for item in mind.learning_queue}
            added = 0
            for gap in gaps:
                if not isinstance(gap, dict):
                    continue
                topic = gap.get("topic", "").strip()
                if not topic or topic in existing_topics:
                    continue
                mind.learning_queue.append({
                    "topic": topic,
                    "reason": gap.get("reason", ""),
                    "priority": float(gap.get("priority", 0.5)),
                    "source": gap.get("source", "task_gap"),
                })
                existing_topics.add(topic)
                added += 1

            if added:
                logger.info("[InnerVoice] %s GAPS: %d 个知识盲区入队（降级模式）", trigger_label, added)
            else:
                logger.info("[InnerVoice] %s GAPS: 全部已存在，跳过（降级模式）", trigger_label)
        except Exception as e:
            logger.debug("[InnerVoice] GAPS 写入 learning_queue 失败: %s", e)

    # ── 统一入口 ──────────────────────────────────────────────────

    def pause(
        self,
        trigger: TriggerType,
        context: dict | None = None,
        task_ctx: TaskStepContext | None = None,
        buzz_hints: str = "",
    ) -> Reflection | None:
        """所有反省的统一入口。返回 None 表示跳过（冷却/无值得注意的）。

        Args:
            trigger: 触发类型
            context: 通用上下文字典，取决于 trigger 类型：
                - CHAT_TURN: {"user_msg": str, "response_len": int, "elapsed": float, "tools": list}
                - TASK_DONE: {"goal_description": str, "elapsed": float, "steps": int}
                - SILENCE: {"idle_seconds": float}
            task_ctx: TASK_STEP 专用上下文
            buzz_hints: 规则检测到的异常提示文本（TASK_STEP 时注入 prompt）

        Returns:
            Reflection 或 None
        """
        context = context or {}

        # 冷却检查
        if self._should_skip(trigger):
            return None

        # 构建 prompt
        messages = self._build_messages(trigger, context, task_ctx, buzz_hints)
        if not messages:
            return None

        # 调用 LLM
        raw_response = self._call_llm(messages)
        if not raw_response:
            return None

        # 分离自然语言 / EVENTS JSON / SIGNAL JSON / GAPS JSON / INSERT JSON
        thought_text, events_json, signal_json, gaps_json, inserts_json = self._split_all(raw_response)
        if not thought_text:
            return None

        # 解析插入建议
        self._last_inserts = self._parse_inserts(inserts_json)

        # 构建 Reflection（thought 只存自然语言部分）
        reflection = Reflection(
            trigger=trigger,
            thought=thought_text[:300],
            context_snippet=self._snippet(trigger, context, task_ctx),
        )

        # 存储
        self._store_reflection(reflection)
        self._update_cooldown(trigger)

        # 路由输出
        self._route_reflection(reflection, events_json, signal_json, gaps_json)

        return reflection

    # ── 冷却逻辑 ──────────────────────────────────────────────────

    def _should_skip(self, trigger: TriggerType) -> bool:
        """判断是否应该跳过本次反省。"""
        now = time.time()

        # 硬冷却：距上次反省 < 3 秒
        if now - self._last_pause_time < 3.0:
            return True

        if trigger == TriggerType.CHAT_TURN:
            # 距上次反省 >= 2 轮有意义的交流
            turns_since = self._chat_turn_count - self._last_chat_reflection_turn
            if turns_since < 2:
                return True

        elif trigger == TriggerType.SILENCE:
            # 距上次 SILENCE 反省 > 30 秒
            if now - self._last_silence_reflection_time < 30.0:
                return True

        # TASK_STEP 和 TASK_DONE 总是允许（它们本身就低频）
        return False

    def _update_cooldown(self, trigger: TriggerType) -> None:
        """更新冷却计时。"""
        now = time.time()
        self._last_pause_time = now

        if trigger == TriggerType.CHAT_TURN:
            self._last_chat_reflection_turn = self._chat_turn_count

        elif trigger == TriggerType.SILENCE:
            self._last_silence_reflection_time = now

    # ── Prompt 构建 ───────────────────────────────────────────────

    def _build_messages(
        self,
        trigger: TriggerType,
        context: dict,
        task_ctx: TaskStepContext | None = None,
        buzz_hints: str = "",
    ) -> list[dict] | None:
        """根据触发类型构建 LLM messages。"""
        if trigger == TriggerType.CHAT_TURN:
            user_msg = context.get("user_msg", "")[:200]
            if len(user_msg) <= 3:
                return None  # 太短，不反省

            response_len = context.get("response_len", 0)
            if response_len <= 20:
                return None  # 回复太短，不反省

            tools = context.get("tools", [])
            tools_info = f"用了{', '.join(tools)}" if tools else "没用工具"

            user_prompt = _CHAT_TURN_PROMPT.format(
                user_msg=user_msg,
                response_len=response_len,
                elapsed=context.get("elapsed", 0),
                tools_info=tools_info,
                user_name=context.get("user_name", "这位用户"),
            )

        elif trigger == TriggerType.TASK_STEP:
            if not task_ctx:
                return None

            tools = task_ctx.tool_calls
            if tools:
                tools_info = f"调用了 {', '.join(tools[:5])}" + (
                    f" 等{len(tools)}个工具" if len(tools) > 5 else ""
                )
            else:
                tools_info = "没有调用工具"

            hints = f"注意信号：{buzz_hints}" if buzz_hints else ""

            user_prompt = _TASK_STEP_PROMPT.format(
                goal_description=task_ctx.goal_description[:200],
                step_index=task_ctx.step_index,
                elapsed=task_ctx.elapsed_seconds,
                tools_info=tools_info,
                buzz_hints=hints,
            )

        elif trigger == TriggerType.TASK_DONE:
            tools = context.get("tools_used", [])
            tools_str = ", ".join(tools[:10]) if tools else "无"
            result = context.get("result_preview", "")[:500]
            user_prompt = _TASK_DONE_PROMPT.format(
                goal_description=context.get("goal_description", "")[:200],
                elapsed=context.get("elapsed", 0),
                steps=context.get("steps", 0),
                tools_used=tools_str,
                result_preview=result or "（无）",
            )

        elif trigger == TriggerType.SILENCE:
            idle = context.get("idle_seconds", 0)
            if idle < 60:
                return None  # 空闲不够长
            user_prompt = _SILENCE_PROMPT.format(idle_seconds=idle)

        else:
            return None

        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    # ── LLM 调用 ──────────────────────────────────────────────────

    def _call_llm(self, messages: list[dict]) -> str | None:
        """调用 LLM 获取内心声音（含 EVENTS JSON）。"""
        if not self._llm:
            return None
        try:
            response = self._llm.chat(messages)
            if response and hasattr(response, "content"):
                raw = (response.content or "").strip()
                if not raw:
                    return None
                if len(raw) > 600:
                    raw = raw[:600]
                return raw
        except Exception as e:
            logger.warning("[InnerVoice] LLM 调用失败: %s", e)
        return None

    # ── 存储 ──────────────────────────────────────────────────────

    def _store_reflection(self, reflection: Reflection) -> None:
        """存储反省到内部缓冲区和 SelfImage。"""
        self._last_reflection = reflection
        self.recent_reflections.append(reflection)
        if len(self.recent_reflections) > 20:
            self.recent_reflections = self.recent_reflections[-20:]

    # ── 输出路由 ──────────────────────────────────────────────────

    def _route_reflection(self, reflection: Reflection, events_text: str = "",
                          signal_text: str = "", gaps_text: str = "") -> None:
        """将反省结果路由到各子系统。

        1. SelfImage.mind.inner_voice（自然语言，总是）
        2. Drive 事件维度（CHAT_TURN / SILENCE 时，从 EVENTS JSON 解析）
        3. Drive 社交信号（CHAT_TURN 时，从 SIGNAL JSON 解析）
        4. Purpose cognitive_log（TASK_STEP / TASK_DONE）
        5. SelfImage.mind.learning_queue（TASK_DONE 时，从 GAPS JSON 解析）
        """
        thought = reflection.thought

        # 1. SelfImage.mind.inner_voice
        if self._self_image:
            try:
                mind = self._self_image.mind
                if not hasattr(mind, "inner_voice"):
                    mind.inner_voice = []
                mind.inner_voice.append({
                    "trigger": reflection.trigger.value,
                    "thought": thought,
                    "time": reflection.timestamp,
                })
                if len(mind.inner_voice) > 20:
                    mind.inner_voice = mind.inner_voice[-20:]
            except Exception as e:
                logger.debug("[InnerVoice] SelfImage 写入失败: %s", e)

        # 2. Drive 事件维度（从 EVENTS JSON 解析）
        if reflection.trigger in (TriggerType.CHAT_TURN, TriggerType.SILENCE):
            if events_text:
                self._apply_drive_events(events_text)

        # 3. Drive 社交信号（从 SIGNAL JSON 解析，仅 CHAT_TURN）
        if reflection.trigger == TriggerType.CHAT_TURN:
            if signal_text:
                self._apply_social_signal(signal_text)

        # 4. Purpose cognitive_log
        if reflection.trigger in (TriggerType.TASK_STEP, TriggerType.TASK_DONE):
            if self._purpose:
                try:
                    current = self._purpose.get_current()
                    if current and hasattr(current, "append_log"):
                        current.append_log("insight", f"[内心声音] {thought}")
                except Exception as e:
                    logger.debug("[InnerVoice] Purpose 写入失败: %s", e)

        # 5. Knowledge gaps → learning_queue（TASK_DONE / CHAT_TURN 时，从 GAPS JSON 解析）
        if reflection.trigger in (TriggerType.TASK_DONE, TriggerType.CHAT_TURN) and gaps_text:
            self._apply_gaps(gaps_text, trigger_label=reflection.trigger.value)

        # 6. ExperienceStream
        if self._exp_stream:
            try:
                parts = [f"[{reflection.trigger.value}] {thought}"]
                if events_text:
                    parts.append(f"EVENTS: {events_text[:100]}")
                if signal_text:
                    parts.append(f"SIGNAL: {signal_text[:100]}")
                if gaps_text:
                    parts.append(f"GAPS: {gaps_text[:100]}")
                self._exp_stream.log(
                    type="internal_reflection",
                    content=" | ".join(parts),
                    importance=0.5,
                )
            except Exception as e:
                logger.debug("[ExpStream] InnerVoice write failed: %s", e)

        logger.info(
            "[InnerVoice] %s:\n%s",
            reflection.trigger.value, thought,
        )

    # ── 公共方法 ──────────────────────────────────────────────────

    def on_chat_turn(self, user_msg: str, response_len: int, elapsed: float,
                     tools: list[str] | None = None, user_name: str = "这位用户") -> None:
        """对话轮次完成时调用（便捷方法）。"""
        self._chat_turn_count += 1
        self.pause(
            TriggerType.CHAT_TURN,
            context={
                "user_msg": user_msg,
                "response_len": response_len,
                "elapsed": elapsed,
                "tools": tools or [],
                "user_name": user_name,
            },
        )

    def on_task_step(self, task_ctx: TaskStepContext,
                     buzz_hints: str = "") -> Reflection | None:
        """任务步骤完成时调用（便捷方法）。"""
        return self.pause(
            TriggerType.TASK_STEP,
            task_ctx=task_ctx,
            buzz_hints=buzz_hints,
        )

    def on_task_done(self, goal_description: str, elapsed: float,
                     steps: int, tools_used: list[str] | None = None,
                     result_preview: str = "") -> Reflection | None:
        """子目标完成时调用（便捷方法）。"""
        return self.pause(
            TriggerType.TASK_DONE,
            context={
                "goal_description": goal_description,
                "elapsed": elapsed,
                "steps": steps,
                "tools_used": tools_used or [],
                "result_preview": result_preview,
            },
        )

    def on_silence(self, idle_seconds: float) -> Reflection | None:
        """用户空闲时调用（便捷方法）。"""
        return self.pause(
            TriggerType.SILENCE,
            context={"idle_seconds": idle_seconds},
        )

    def should_continue(self) -> tuple[bool, str]:
        """从最近一次反省中提取任务继续/停止信号。

        Returns:
            (should_continue, reason)
            reason: "continue" / "retry" / "waiting_user" / "escalate"
        """
        if not self._last_reflection:
            return True, "continue"
        return _extract_continue_signal(self._last_reflection.thought)

    def has_experience_to_save(self) -> bool:
        """最近的反省是否包含值得保存的经验。"""
        if not self._last_reflection:
            return False
        return _has_experience_signal(self._last_reflection.thought)

    def get_last_thought(self) -> str:
        """获取最近一次反省的文本。"""
        if self._last_reflection:
            return self._last_reflection.thought
        return ""

    def get_buzz_hints(self, surprises: list[str]) -> str:
        """将规则检测到的意外信号转为自然语言提示。

        Args:
            surprises: 意外信号描述列表，如 ["连续3次调用同一工具", "单步耗时过长"]

        Returns:
            自然语言提示字符串，如 "注意：连续3次调用同一工具；单步耗时过长"
        """
        if not surprises:
            return ""
        return "注意：" + "；".join(surprises)

    # ── 内部辅助 ──────────────────────────────────────────────────

    def _snippet(
        self,
        trigger: TriggerType,
        context: dict,
        task_ctx: TaskStepContext | None = None,
    ) -> str:
        """生成上下文片段用于 Reflection.context_snippet。"""
        if trigger == TriggerType.CHAT_TURN:
            return context.get("user_msg", "")[:80]
        elif trigger == TriggerType.TASK_STEP and task_ctx:
            return f"{task_ctx.goal_description[:60]} (step {task_ctx.step_index})"
        elif trigger == TriggerType.TASK_DONE:
            return context.get("goal_description", "")[:80]
        elif trigger == TriggerType.SILENCE:
            return f"idle {context.get('idle_seconds', 0):.0f}s"
        return ""
