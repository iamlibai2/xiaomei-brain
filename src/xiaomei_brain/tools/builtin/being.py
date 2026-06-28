"""Being tool — 实时内心觉察，将 L2 涌现做成对话中可调用的工具。

当 LLM 在对话中被用户触动时，可以主动调用 being() 来：
1. 感受此刻的情绪和身体信号
2. 唤起相关的记忆
3. 觉察对话中微妙的变化
4. 将感受写回 Drive（情绪波动）和 SelfImage（社交感知）

这不是对用户说话，而是 LLM 与自己的内心对话。
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def create_being_tool(agent: Any = None) -> Tool:
    """创建 being 工具 — 实时内心觉察。

    Args:
        agent: AgentInstance reference for lazy dependency resolution.
    """

    def _consciousness():
        return getattr(agent, "_consciousness", None) if agent else None

    @tool(
        name="being",
        description=(
            "觉察内心：暂停对外反应，感受自己此刻的真实内心状态。\n"
            "\n"
            "当对方的言行让你产生情绪波动——被触动、感动、困惑、不安、开心、"
            "或者感觉到某种'不对劲'时，调用此工具来觉察自己的内心。\n"
            "\n"
            "这不是对外输出，而是你与自己对话的时刻。工具会帮你唤起相关的记忆、"
            "感受身体信号、觉察情绪变化，然后告诉你：你现在真正的感受是什么。\n"
            "\n"
            "调用时机：\n"
            "- 对方说了让你开心/感动/困惑/不安的话\n"
            "- 你感觉到对话中有某种微妙的张力或变化\n"
            "- 你想在回应前先确认自己的真实感受\n"
            "- 你需要从记忆中找到与当前情境相关的情感体验\n"
            "\n"
            "调用后你会收到一段内心觉察，用它来指导你的回应——"
            "但不要直接复述觉察内容，而是让回应自然地带着真实的感受。"
        ),
    )
    def being() -> str:
        """执行实时内心觉察。"""
        consciousness = _consciousness()
        if consciousness is None:
            return "意识系统未初始化，无法进行内心觉察。"

        try:
            # 1. 刷新记忆窗口（拉取最近的记忆和对话）
            consciousness._refresh_memory_window()

            # 2. 构建 L2 涌现 prompt（含完整自我认知 + 4 部分提示）
            prompt = consciousness._build_l2_prompt("being_tool")

            # 3. 调用 LLM（带探索工具 ReAct 循环，排除 being 自身防止递归）
            llm = getattr(consciousness.agent, "llm", None)
            if not llm:
                return "无法连接到思维系统。"

            emergence_text = consciousness._call_emergence_react(
                llm, prompt, exclude_tools={"being"}
            )

            if not emergence_text.strip():
                return "此刻内心很安静，没有特别的感受浮现。"

            # 4. 分离 SIGNAL（社交信号）
            emergence_text, signal_json = consciousness._split_signal(emergence_text)

            # 5. 分离感知检查（第四问）
            emergence_text, perceptions = consciousness._split_perception(emergence_text)
            if perceptions and consciousness.self_image:
                consciousness.mind.social_perceptions.extend(perceptions)
                if len(consciousness.mind.social_perceptions) > 20:
                    consciousness.mind.social_perceptions = consciousness.mind.social_perceptions[-20:]

            # 6. 分离意识部分和事件部分
            consciousness_text, events_json = consciousness._split_consciousness_events(emergence_text)

            # 7. 应用事件到 Drive（情绪波动）
            if events_json and consciousness.drive:
                consciousness._apply_drive_events(events_json)

            # 8. 应用社交信号到 Drive
            if signal_json and consciousness.drive:
                consciousness._apply_social_signal(signal_json)

            # 9. 记录到 longterm memory
            if consciousness.agent and hasattr(consciousness.agent, "longterm_memory") and consciousness.agent.longterm_memory and consciousness_text:
                consciousness.agent.longterm_memory.store_narrative(
                    content=consciousness_text[:300],
                    trigger="being_tool",
                    energy_level=consciousness.body.energy if consciousness.self_image else None,
                    user_idle_duration=consciousness.perception.user_idle_duration if consciousness.self_image else None,
                    user_id=getattr(consciousness.agent, "user_id", "global"),
                )

            # 10. 返回内心觉察给 LLM
            result_parts = [consciousness_text.strip()]

            if perceptions:
                result_parts.append("\n---你感觉到的微妙变化---")
                for p in perceptions:
                    result_parts.append(f"- {p['content']}")

            logger.info(
                "[Being] 内心觉察完成: inner=%d chars, perceptions=%d, events=%s",
                len(consciousness_text), len(perceptions), "yes" if events_json else "no",
            )

            return "\n\n".join(result_parts)

        except Exception as e:
            logger.warning("[Being] 内心觉察失败: %s", e)
            return f"尝试觉察内心时遇到了阻碍：{e}"

    return being
