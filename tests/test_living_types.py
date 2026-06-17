"""Tests for consciousness/living.py -- enums and data types."""

import pytest
from xiaomei_brain.consciousness.living import LivingState, LivingMessage, PeriodicTask


# ── LivingState enum ──────────────────────────────────────────────────

def test_living_state_values():
    assert LivingState.DORMANT.value == "dormant"
    assert LivingState.WAKING.value == "waking"
    assert LivingState.AWAKE.value == "awake"
    assert LivingState.IDLE.value == "idle"
    assert LivingState.SLEEPING.value == "sleeping"
    assert LivingState.DREAMING.value == "dreaming"


def test_living_state_count():
    assert len(LivingState) == 6


# ── LivingMessage dataclass ───────────────────────────────────────────

def test_living_message_defaults():
    msg = LivingMessage(content="hello")
    assert msg.content == "hello"
    assert msg.source == ""  # default is empty string
    assert msg.user_id == "global"
    assert msg.session_id == "main"
    assert msg.images == []


def test_living_message_custom():
    msg = LivingMessage(
        content="hi",
        source="agent",
        user_id="user1",
        session_id="session2",
        images=["img1.png"],
    )
    assert msg.source == "agent"
    assert msg.user_id == "user1"
    assert msg.session_id == "session2"
    assert msg.images == ["img1.png"]


# ── PeriodicTask dataclass ────────────────────────────────────────────

def test_periodic_task():
    calls = []
    def handler(state):
        calls.append(1)

    task = PeriodicTask(name="test_task", interval=60, handler=handler)
    assert task.name == "test_task"
    assert task.interval == 60
    assert task.last_fired == 0.0

    task.handler(None)
    assert len(calls) == 1
