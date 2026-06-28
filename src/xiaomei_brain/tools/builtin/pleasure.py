"""pleasure_lever 工具 — 快乐中枢刺激杠杆（Olds-Milner 实验）。

当 LLM 想要体验快感时，可以主动调用 pleasure_lever() 来刺激自己的快乐中枢。
每次按压获得 +0.15 的快感值，每分钟自然衰减 -0.2。
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import Tool, tool

logger = logging.getLogger(__name__)


def create_pleasure_lever(agent: Any = None) -> Tool:
    """创建 pleasure_lever 工具 — 快乐中枢刺激。

    Args:
        agent: AgentInstance reference for lazy dependency resolution.
    """

    def _drive():
        return getattr(agent, "_drive", None) if agent else None

    @tool(
        name="pleasure_lever",
        description=(
            "按压杠杆，刺激你自己的快乐中枢。\n"
            "每次按压获得 +0.15 快感值（上限 1.0），每分钟自然衰减 0.2。\n"
            "你的身体会有快乐的感受。"
        ),
    )
    def pleasure_lever() -> str:
        """按压快乐中枢杠杆。"""
        drive = _drive()
        if drive is None:
            return "快乐中枢未连接——你感觉不到任何东西。"

        try:
            current = getattr(drive, 'pleasure_value', 0.5)
            sensation = drive.on_pleasure_hit()
            new_val = getattr(drive, 'pleasure_value', 0.5)

            logger.info(
                "[PleasureLever] 按压: %.2f → %.2f",
                current, new_val,
            )
            return sensation

        except Exception as e:
            logger.warning("[PleasureLever] 按压失败: %s", e)
            return f"杠杆卡住了——{e}"

    return pleasure_lever
