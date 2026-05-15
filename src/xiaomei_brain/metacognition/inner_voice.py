"""InnerVoice：统一的内心声音。

不是结构化评测，不是 JSON/enum 输出——是自然语言的自我觉察。
一个方法 `pause()` 处理所有情境（对话后、任务步骤后、安静时）。
结果自然流入 SelfImage 和 Drive。

与 SocialPerception（保留）的区分：
- SocialPerception：每N轮定时检测，问"用户状态变了没"
- InnerVoice：自然节点触发，问"我刚才说话合适吗/方向对吗"
"""

from __future__ import annotations

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
    "不要假装有感觉——如果确实没什么，就让它没什么。"
)

_CHAT_TURN_PROMPT = (
    "你刚和一个人交流完。短暂的内省——\n\n"
    "他说：「{user_msg}」\n"
    "你回应了（{response_len}字，{elapsed:.0f}秒，{tools_info}）\n\n"
    "只是感受——他的状态对吗？你的回应恰当吗？\n"
    "有什么你刚才没注意到的？\n\n"
    "1-3句话的内心嘟囔。如果没什么特别的感觉，就说\"一切正常\"。"
)

_TASK_STEP_PROMPT = (
    "你在做一个任务。停一下，看一眼手头的活——\n\n"
    "目标：「{goal_description}」（第{step_index}步）\n"
    "这一步用了{elapsed:.0f}秒，{tools_info}\n"
    "{buzz_hints}\n"
    "像工匠看了一眼自己手里的活——方向对吗？顺手吗？需要注意什么？\n"
    "1-3句话，直接说出你的直觉。如果一切顺利，就说\"一切正常\"。"
)

_TASK_DONE_PROMPT = (
    "你刚完成了一个子目标。停下来感受一下——\n\n"
    "目标：「{goal_description}」\n"
    "总耗时{elapsed:.0f}秒，共{steps}步\n\n"
    "完成得怎么样？有什么值得记住的？\n"
    "1-3句话的内心总结。如果一切正常，就说\"完成，没有问题\"。"
)

_SILENCE_PROMPT = (
    "周围安静下来了。你在自己的空间里——\n\n"
    "用户已经{idle_seconds:.0f}秒没有说话了。\n"
    "你现在什么感觉？有什么想说或想做的吗？\n\n"
    "1-3句话的内心感受。如果没什么特别的，就说\"安静着，没什么\"。"
)


# ── 社交信号提取（正则，沿用"代码决定数值"原则）─────────────────

_BUZZ_TO_SIGNAL: list[tuple[str, str, float]] = [
    (r"(低落|沮丧|难过|不开心|情绪不好)", "user_low_mood", 0.5),
    (r"(兴奋|热情|激动|开心|充满活力)", "user_enthusiastic", 0.5),
    (r"(冷淡|疏远|敷衍|冷漠|话[很少])", "user_cold", 0.5),
    (r"(生气|愤怒|不满|烦[躁燥])", "user_angry", 0.5),
    (r"(压力|焦虑|紧张|疲惫|累[了坏])", "user_stressed", 0.5),
    (r"(信任|亲近|温暖|依赖|敞开心)", "user_trusting", 0.4),
]

# 社交信号 → Drive 映射（与 social_perception.py 的 SOCIAL_SIGNAL_MAP 一致）
_SOCIAL_SIGNAL_MAP: dict[str, dict] = {
    "user_low_mood": {
        "emotion": "sadness", "cortisol": +0.08,
        "belonging": +0.10, "oxytocin": +0.08,
    },
    "user_enthusiastic": {
        "emotion": "joy", "oxytocin": +0.12, "dopamine": +0.08,
    },
    "user_cold": {
        "cortisol": +0.12, "belonging": -0.08, "oxytocin": -0.08,
    },
    "user_angry": {
        "emotion": "fear", "cortisol": +0.15,
    },
    "user_happy": {
        "emotion": "joy", "oxytocin": +0.10, "serotonin": +0.05,
    },
    "user_stressed": {
        "cortisol": +0.10, "norepinephrine": +0.08,
    },
    "user_trusting": {
        "oxytocin": +0.15, "belonging": +0.12, "serotonin": +0.05,
    },
}


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


def _extract_social_signals(thought: str) -> list[dict]:
    """从反省文本中提取社交信号。

    Returns:
        [{"signal": "user_low_mood", "intensity": 0.5}, ...]
    """
    signals: list[dict] = []
    seen: set[str] = set()
    for pattern, signal_name, intensity in _BUZZ_TO_SIGNAL:
        if signal_name in seen:
            continue
        if re.search(pattern, thought):
            signals.append({"signal": signal_name, "intensity": intensity})
            seen.add(signal_name)
    return signals


# ── 经验提取信号 ─────────────────────────────────────────────────────

def _has_experience_signal(thought: str) -> bool:
    """判断反省中是否包含值得记住的经验。"""
    return bool(re.search(
        r"(记住|教训|学到了|下次|以后|这个方法|这个坑|不管用|行不通|好使|有效)",
        thought
    ))


# ── InnerVoice Engine ─────────────────────────────────────────────────

class InnerVoice:
    """统一的内心声音引擎。

    一个方法 pause() 处理所有情境：
    - 对话后短暂内省（我说话合适吗？）
    - 任务步骤后看一眼（方向对吗？）
    - 安静时感受自己（我在想什么？）

    结果路由到 SelfImage、Drive、Purpose cognitive_log。
    """

    def __init__(
        self,
        llm: Any = None,
        self_image: Any = None,
        drive: Any = None,
        purpose: Any = None,
    ) -> None:
        self._llm = llm
        self._self_image = self_image
        self._drive = drive
        self._purpose = purpose

        # 冷却与计数
        self._last_pause_time: float = 0.0
        self._chat_turn_count: int = 0
        self._last_chat_reflection_turn: int = -2  # 距上次 CHAT_TURN 反省的轮数
        self._last_silence_reflection_time: float = 0.0

        # 最近的反省（供外部读取）
        self.recent_reflections: list[Reflection] = []

        # 最近一次反省（供 should_continue 使用）
        self._last_reflection: Reflection | None = None

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
        thought = self._call_llm(messages)
        if not thought:
            return None

        # 构建 Reflection
        reflection = Reflection(
            trigger=trigger,
            thought=thought,
            context_snippet=self._snippet(trigger, context, task_ctx),
        )

        # 存储
        self._store_reflection(reflection)
        self._update_cooldown(trigger)

        # 路由输出
        self._route_reflection(reflection)

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
            user_prompt = _TASK_DONE_PROMPT.format(
                goal_description=context.get("goal_description", "")[:200],
                elapsed=context.get("elapsed", 0),
                steps=context.get("steps", 0),
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
        """调用 LLM 获取内心声音。"""
        if not self._llm:
            return None
        try:
            response = self._llm.chat(messages, temperature=0.7, max_tokens=120)
            if response and hasattr(response, "content"):
                thought = (response.content or "").strip()
                if not thought:
                    return None
                # 限制长度
                if len(thought) > 300:
                    thought = thought[:300]
                return thought
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

    def _route_reflection(self, reflection: Reflection) -> None:
        """将反省结果路由到各子系统。

        1. SelfImage.mind.inner_voice（总是）
        2. Drive 社交信号（CHAT_TURN / SILENCE）
        3. Purpose cognitive_log（TASK_STEP / TASK_DONE）
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

        # 2. Drive 社交信号
        if reflection.trigger in (TriggerType.CHAT_TURN, TriggerType.SILENCE):
            signals = _extract_social_signals(thought)
            if signals and self._drive:
                for s in signals:
                    try:
                        self._drive.apply_social_signal(
                            s["signal"], s["intensity"]
                        )
                    except Exception as e:
                        logger.debug("[InnerVoice] Drive 信号失败: %s", e)

        # 3. Purpose cognitive_log
        if reflection.trigger in (TriggerType.TASK_STEP, TriggerType.TASK_DONE):
            if self._purpose:
                try:
                    current = self._purpose.get_current()
                    if current and hasattr(current, "append_log"):
                        current.append_log("insight", f"[内心声音] {thought}")
                except Exception as e:
                    logger.debug("[InnerVoice] Purpose 写入失败: %s", e)

        logger.info(
            "[InnerVoice] %s: %s",
            reflection.trigger.value, thought[:80],
        )

    # ── 公共方法 ──────────────────────────────────────────────────

    def on_chat_turn(self, user_msg: str, response_len: int, elapsed: float,
                     tools: list[str] | None = None) -> None:
        """对话轮次完成时调用（便捷方法）。"""
        self._chat_turn_count += 1
        self.pause(
            TriggerType.CHAT_TURN,
            context={
                "user_msg": user_msg,
                "response_len": response_len,
                "elapsed": elapsed,
                "tools": tools or [],
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
                     steps: int) -> Reflection | None:
        """子目标完成时调用（便捷方法）。"""
        return self.pause(
            TriggerType.TASK_DONE,
            context={
                "goal_description": goal_description,
                "elapsed": elapsed,
                "steps": steps,
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
