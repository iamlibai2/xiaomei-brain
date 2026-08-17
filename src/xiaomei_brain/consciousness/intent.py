"""Intent: 意识产出的行动倾向。

意识不只是描述状态，还要生成意图。
意图驱动行为层，行为层听从意图。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class IntentScope(str, Enum):
    """The world boundary an intent is allowed to observe and affect."""

    SESSION = "session"
    PERSON = "person"
    AGENT = "agent"


def normalize_intent_record(data: dict) -> dict:
    """Give legacy and new intents one durable identity and explicit scope."""
    record = dict(data or {})
    params = dict(record.get("params") or {})
    user_id = str(record.get("user_id") or params.get("user_id") or "")
    session_id = str(record.get("session_id") or params.get("session_id") or "")
    scope_type = str(record.get("scope_type") or params.get("scope_type") or "").lower()
    valid_scopes = {scope.value for scope in IntentScope}
    if scope_type not in valid_scopes:
        scope_type = (
            IntentScope.SESSION.value if user_id and session_id
            else IntentScope.PERSON.value if user_id
            else IntentScope.AGENT.value
        )
    if scope_type == IntentScope.SESSION.value and (not user_id or not session_id):
        scope_type = IntentScope.PERSON.value if user_id else IntentScope.AGENT.value
    if scope_type == IntentScope.PERSON.value:
        session_id = ""
    elif scope_type == IntentScope.AGENT.value:
        user_id = ""
        session_id = ""
    record.update({
        "intent_id": str(record.get("intent_id") or params.get("intent_id") or f"intent_{uuid.uuid4().hex}"),
        "scope_type": scope_type,
        "user_id": user_id,
        "session_id": session_id,
        "params": params,
    })
    return record


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

    LEARN = "learn"
    """想学习新知识"""

    EXPRESS = "express"
    """想分享想法或洞察"""

    PROGRESS = "progress"
    """想推进目标"""

    WORK = "work"
    """想自由工作，按目标 tag 选择任务"""

    ADVANCE_MISSION = "advance_mission"
    """想推进一个明确的长期 Mission"""

    CREATE_MISSION = "create_mission"
    """想建立一个新的长期 Mission，先进入讨论准备状态"""

    ALARM = "alarm"
    """闹钟触发"""

    TALK = "talk"
    """想和其他 agent 聊聊"""

    SLEEP = "sleep"
    """想睡觉——能量见底或无事可做时主动休眠"""


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
        d = {
            "type": self.type.value,
            "priority": self.priority,
            "content": self.content,
            "trigger_time": self.trigger_time,
            "source": self.source,
            "params": self.params,
        }
        return normalize_intent_record(d)

    @classmethod
    def from_dict(cls, data: dict) -> "Intent":
        """从字典创建"""
        normalized = normalize_intent_record(data)
        params = dict(normalized.get("params") or {})
        params.update({
            "intent_id": normalized["intent_id"],
            "scope_type": normalized["scope_type"],
            "user_id": normalized["user_id"],
            "session_id": normalized["session_id"],
        })
        return cls(
            type=IntentType(normalized["type"]),
            priority=normalized["priority"],
            content=normalized["content"],
            trigger_time=normalized.get("trigger_time", time.time()),
            source=normalized.get("source", "consciousness"),
            params=params,
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


def create_sleep_intent(reason: str = "", priority: int = 80) -> Intent:
    """创建睡眠意图"""
    return Intent(
        type=IntentType.SLEEP,
        priority=priority,
        content=f"想睡觉：{reason}" if reason else "能量耗尽或无事可做，主动休眠",
    )


def create_care_intent(user_state: str, priority: int = 75) -> Intent:
    """创建关心意图"""
    return Intent(
        type=IntentType.CARE,
        priority=priority,
        content=f"想关心对方，对方状态：{user_state}",
        params={"user_state": user_state},
    )


def create_express_intent(thought: str, priority: int = 60) -> Intent:
    """创建表达意图"""
    return Intent(
        type=IntentType.EXPRESS,
        priority=priority,
        content=f"想分享：{thought}",
        params={"thought": thought},
    )
