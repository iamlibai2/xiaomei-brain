"""Tests for consciousness/intent.py -- Intent types, factories, and serialization."""

import pytest
import time
from xiaomei_brain.consciousness.intent import (
    IntentType,
    Intent,
    create_wait_intent,
    create_greet_intent,
    create_remind_intent,
    create_recall_intent,
    create_reflect_intent,
    create_dream_intent,
    create_sleep_intent,
    create_care_intent,
    create_express_intent,
)


# ── IntentType enum ──────────────────────────────────────────────────

def test_intent_type_values():
    assert IntentType.WAIT.value == "wait"
    assert IntentType.GREET.value == "greet"
    assert IntentType.REMIND.value == "remind"
    assert IntentType.RECALL.value == "recall"
    assert IntentType.REFLECT.value == "reflect"
    assert IntentType.ACT.value == "act"
    assert IntentType.DREAM.value == "dream"
    assert IntentType.CARE.value == "care"
    assert IntentType.LEARN.value == "learn"
    assert IntentType.EXPRESS.value == "express"
    assert IntentType.PROGRESS.value == "progress"
    assert IntentType.WORK.value == "work"
    assert IntentType.ALARM.value == "alarm"
    assert IntentType.TALK.value == "talk"
    assert IntentType.SLEEP.value == "sleep"


def test_intent_type_count():
    assert len(IntentType) == 15


# ── Intent dataclass ──────────────────────────────────────────────────

def test_intent_is_urgent():
    assert Intent(type=IntentType.GREET, priority=80, content="").is_urgent() is True
    assert Intent(type=IntentType.GREET, priority=79, content="").is_urgent() is False


def test_intent_is_actionable_wait():
    intent = Intent(type=IntentType.WAIT, priority=10, content="")
    assert intent.is_actionable() is False


def test_intent_is_actionable_greet():
    intent = Intent(type=IntentType.GREET, priority=70, content="hello")
    assert intent.is_actionable() is True


def test_intent_defaults():
    intent = Intent(type=IntentType.WAIT, priority=10, content="")
    assert intent.source == "consciousness"
    assert intent.params == {}


def test_intent_to_dict():
    intent = create_greet_intent("你好", priority=70)
    d = intent.to_dict()
    assert d["type"] == "greet"
    assert d["priority"] == 70
    assert d["content"] == "你好"
    assert d["source"] == "consciousness"


def test_intent_to_dict_with_user_id():
    intent = create_greet_intent("你好", priority=70)
    intent.params["user_id"] = "user1"
    d = intent.to_dict()
    assert d["user_id"] == "user1"


def test_intent_from_dict():
    data = {"type": "greet", "priority": 70, "content": "hello", "trigger_time": 1000.0, "source": "consciousness", "params": {}}
    intent = Intent.from_dict(data)
    assert intent.type == IntentType.GREET
    assert intent.priority == 70
    assert intent.content == "hello"


def test_intent_to_dict_from_dict_roundtrip():
    intent = create_greet_intent("你好", priority=70)
    d = intent.to_dict()
    restored = Intent.from_dict(d)
    assert restored.type == intent.type
    assert restored.priority == intent.priority
    assert restored.content == intent.content


# ── Factory functions ─────────────────────────────────────────────────

def test_create_wait_intent():
    intent = create_wait_intent()
    assert intent.type == IntentType.WAIT
    assert intent.priority == 10
    assert "等待" in intent.content


def test_create_greet_intent():
    intent = create_greet_intent("早上好")
    assert intent.type == IntentType.GREET
    assert intent.priority == 70
    assert intent.content == "早上好"


def test_create_greet_intent_custom_priority():
    intent = create_greet_intent("你好", priority=80)
    assert intent.priority == 80


def test_create_remind_intent():
    intent = create_remind_intent("开会")
    assert intent.type == IntentType.REMIND
    assert intent.priority == 90
    assert "提醒" in intent.content
    assert "开会" in intent.content
    assert intent.params["reminder_text"] == "开会"


def test_create_recall_intent():
    intent = create_recall_intent("童年")
    assert intent.type == IntentType.RECALL
    assert intent.priority == 60
    assert "童年" in intent.content
    assert intent.params["keyword"] == "童年"


def test_create_reflect_intent():
    intent = create_reflect_intent("刚才说话太冲了")
    assert intent.type == IntentType.REFLECT
    assert intent.priority == 50
    assert "反省" in intent.content
    assert "刚才说话太冲了" in intent.content


def test_create_dream_intent():
    intent = create_dream_intent()
    assert intent.type == IntentType.DREAM
    assert intent.priority == 40
    assert "梦境" in intent.content


def test_create_dream_intent_custom_priority():
    intent = create_dream_intent(priority=60)
    assert intent.priority == 60


def test_create_sleep_intent_with_reason():
    intent = create_sleep_intent("太累了")
    assert intent.type == IntentType.SLEEP
    assert intent.priority == 80
    assert "太累了" in intent.content


def test_create_sleep_intent_without_reason():
    intent = create_sleep_intent()
    assert intent.type == IntentType.SLEEP
    assert "能量耗尽" in intent.content or "休眠" in intent.content


def test_create_care_intent():
    intent = create_care_intent("心情低落")
    assert intent.type == IntentType.CARE
    assert intent.priority == 75
    assert "心情低落" in intent.content
    assert intent.params["user_state"] == "心情低落"


def test_create_express_intent():
    intent = create_express_intent("AI 发展的未来")
    assert intent.type == IntentType.EXPRESS
    assert intent.priority == 60
    assert "AI 发展的未来" in intent.content
    assert intent.params["thought"] == "AI 发展的未来"
