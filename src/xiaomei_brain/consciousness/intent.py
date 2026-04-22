"""Intent: 意识产出的行动倾向。

意识不只是描述状态，还要生成意图。
意图驱动行为层，行为层听从意图。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class IntentType(Enum):
    """意图类型"""

    WAIT = "wait"
    """等待，暂无行动"""

    GREET = "greet"
    """想问候用户"""

    REMIND = "remind"
    """想提醒某事"""

    RECALL = "recall"
    """想回忆某事"""

    REFLECT = "reflect"
    """想反省"""

    ACT = "act"
    """想执行某个动作"""

    DREAM = "dream"
    """想进入梦境"""

    CARE = "care"
    """想关心用户"""


@dataclass
class Intent:
    """意图：意识产出的行动倾向。

    意图是意识的核心产出之一，驱动后续行为。
    """

    type: IntentType
    """意图类型"""

    priority: int
    """优先级（0-100），越高越紧急"""

    content: str
    """具体内容描述"""

    trigger_time: float = field(default_factory=time.time)
    """何时生成"""

    source: str = "consciousness"
    """来源"""

    params: dict = field(default_factory=dict)
    """可选参数"""

    # ── 辅助方法──────────────────────────────────────

    def is_urgent(self) -> bool:
        """是否紧急（优先级 >= 80）"""
        return self.priority >= 80

    def is_actionable(self) -> bool:
        """是否可执行（非 wait 类型）"""
        return self.type != IntentType.WAIT

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "type": self.type.value,
            "priority": self.priority,
            "content": self.content,
            "trigger_time": self.trigger_time,
            "source": self.source,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Intent":
        """从字典创建"""
        return cls(
            type=IntentType(data["type"]),
            priority=data["priority"],
            content=data["content"],
            trigger_time=data.get("trigger_time", time.time()),
            source=data.get("source", "consciousness"),
            params=data.get("params", {}),
        )


# ── 预定义意图工厂─────────────────────────────────────


def create_wait_intent() -> Intent:
    """创建等待意图"""
    return Intent(
        type=IntentType.WAIT,
        priority=10,
        content="等待，暂无行动",
    )


def create_greet_intent(content: str, priority: int = 70) -> Intent:
    """创建问候意图"""
    return Intent(
        type=IntentType.GREET,
        priority=priority,
        content=content,
    )


def create_remind_intent(reminder_text: str, priority: int = 90) -> Intent:
    """创建提醒意图"""
    return Intent(
        type=IntentType.REMIND,
        priority=priority,
        content=f"提醒：{reminder_text}",
        params={"reminder_text": reminder_text},
    )


def create_recall_intent(keyword: str, priority: int = 60) -> Intent:
    """创建回忆意图"""
    return Intent(
        type=IntentType.RECALL,
        priority=priority,
        content=f"想回忆关于{keyword}的内容",
        params={"keyword": keyword},
    )


def create_reflect_intent(reason: str, priority: int = 50) -> Intent:
    """创建反省意图"""
    return Intent(
        type=IntentType.REFLECT,
        priority=priority,
        content=f"想反省：{reason}",
        params={"reason": reason},
    )


def create_dream_intent(priority: int = 40) -> Intent:
    """创建梦境意图"""
    return Intent(
        type=IntentType.DREAM,
        priority=priority,
        content="想进入梦境进行深度思考",
    )


def create_care_intent(user_state: str, priority: int = 75) -> Intent:
    """创建关心意图"""
    return Intent(
        type=IntentType.CARE,
        priority=priority,
        content=f"想关心用户，用户状态：{user_state}",
        params={"user_state": user_state},
    )