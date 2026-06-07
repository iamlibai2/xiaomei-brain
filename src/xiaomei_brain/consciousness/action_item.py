"""ActionItem: 结构化动作数据结构。

供 ActionDispatcher 使用，统一所有动作的表示格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(Enum):
    """动作类型"""
    PROACTIVE = "proactive"       # 主动发消息
    ALARM = "alarm"               # 闹钟触发（完整 ReAct）
    WORK = "work"                 # 自由工作（完整 ReAct）
    TRIGGER_L3 = "trigger_l3"     # 触发 L3 沉思
    TOOL = "tool"                 # 执行工具
    NOTIFY = "notify"             # 通知用户
    TALK_TO_AGENT = "talk_to_agent"  # 主动和其他 agent 聊天


@dataclass
class ActionItem:
    """结构化动作

    所有动作（Intent 驱动、欲望驱动、目标驱动、系统触发）
    都表示为 ActionItem，进入统一队列按优先级执行。
    """
    action_type: ActionType
    priority: float               # 优先级 0-1，越高越先执行
    content: str                  # 动作内容（消息文本/工具名/通知内容）
    reason: str                  # 触发原因（供观测/调试）
    source: str                  # 来源: intent | desire | goal | system
    cooldown_key: str            # 冷却 key，同 key 的动作不能重复执行
    metadata: dict[str, Any] = field(default_factory=dict)

    # 用于优先级排序的元组
    _source_order: dict[str, int] = field(default_factory=lambda: {
        "intent": 0,
        "desire": 1,
        "goal": 2,
        "system": 3,
    }, repr=False)

    def sort_key(self) -> tuple[int, float]:
        """排序 key：source 优先级（intent 先于 desire 先于 goal）> priority"""
        source_priority = self._source_order.get(self.source, 3)
        return (source_priority, -self.priority)

    def with_metadata(self, **kwargs) -> ActionItem:
        """链式添加 metadata"""
        self.metadata.update(kwargs)
        return self

    def __repr__(self) -> str:
        return (
            f"ActionItem(type={self.action_type.value}, "
            f"priority={self.priority:.2f}, source={self.source}, "
            f"reason={self.reason[:30] if self.reason else ''})"
        )
