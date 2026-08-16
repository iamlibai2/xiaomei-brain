"""Tests for consciousness/living.py -- enums and data types."""

import pytest
import xiaomei_brain.consciousness.living as living_module
from types import SimpleNamespace
from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
from xiaomei_brain.consciousness.living import Living, LivingState, LivingMessage, PeriodicTask


# ── LivingState enum ──────────────────────────────────────────────────

def test_living_state_values():
    assert LivingState.DORMANT.value == "dormant"
    assert LivingState.WAKING.value == "waking"
    assert LivingState.AWAKE.value == "awake"
    assert LivingState.IDLE.value == "idle"
    assert LivingState.WORKING.value == "working"
    assert LivingState.SLEEPING.value == "sleeping"
    assert LivingState.DREAMING.value == "dreaming"


def test_living_state_count():
    assert len(LivingState) == 7


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


class _SteerCore:
    def __init__(self):
        self.messages = []

    def steer(self, message):
        self.messages.append(message)

    def take_pending_steers(self):
        messages, self.messages = self.messages, []
        return messages


class _AgentInstance:
    def __init__(self, core):
        self.core = core

    def _get_agent(self):
        return self.core


def _living_with_active_turn():
    core = _SteerCore()
    living = Living(_AgentInstance(core))
    living.begin_active_turn(LivingMessage(
        content="original",
        user_id="person-1",
        session_id="session-1",
        turn_id="active-turn",
    ))
    return living, core


def test_same_person_session_plain_text_steers_active_turn():
    living, core = _living_with_active_turn()

    message = living.put_message(
        "change direction",
        user_id="person-1",
        session_id="session-1",
        source="desktop",
        turn_id="steer-turn",
        message_id=42,
    )

    assert message.steered_into_turn_id == "active-turn"
    assert living._queue.empty()
    assert core.messages[0].turn_id == "steer-turn"
    assert core.messages[0].message_id == 42


@pytest.mark.parametrize("overrides", [
    {"user_id": "person-2"},
    {"session_id": "session-2"},
    {"images": ["image.png"]},
    {"attachments": [{"id": "file-1"}]},
    {"assignment_id": "assignment-1"},
    {"observation_id": "observation-1"},
])
def test_ineligible_message_remains_in_normal_queue(overrides):
    living, core = _living_with_active_turn()
    kwargs = {
        "user_id": "person-1",
        "session_id": "session-1",
        "source": "desktop",
        "turn_id": "next-turn",
        **overrides,
    }

    message = living.put_message("next request", **kwargs)

    assert message.steered_into_turn_id == ""
    assert core.messages == []
    assert living._queue.get_nowait() is message


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


def test_entering_idle_starts_a_separate_sleep_timer(monkeypatch):
    living = Living(_AgentInstance(_SteerCore()), idle_threshold=1800)
    clock = {"now": 100.0}
    monkeypatch.setattr(living_module.time, "time", lambda: clock["now"])

    living._transition(LivingState.AWAKE)
    clock["now"] = 500.0
    living._transition(LivingState.IDLE)

    assert living._idle_started_at == 500.0
    clock["now"] = 2299.0
    assert living._automatic_sleep_due() is False
    clock["now"] = 2300.0
    assert living._automatic_sleep_due() is True


def test_leaving_idle_clears_the_sleep_timer(monkeypatch):
    living = Living(_AgentInstance(_SteerCore()))
    monkeypatch.setattr(living_module.time, "time", lambda: 100.0)

    living._transition(LivingState.IDLE)
    living._transition(LivingState.AWAKE)

    assert living._idle_started_at == 0.0


def test_awake_transitions_to_idle_before_sleep(monkeypatch):
    living = Living(
        _AgentInstance(_SteerCore()),
        idle_short=10,
        idle_threshold=20,
        tick_interval=0,
    )
    living.state = LivingState.AWAKE
    living._last_active = 1.0
    monkeypatch.setattr(living_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(living, "_wait_message", lambda timeout: None)

    living._loop_awake()

    assert living.state == LivingState.IDLE
    assert living._idle_started_at == 100.0


def test_token_budget_exhaustion_requests_sleep_without_an_llm_call():
    living = object.__new__(ConsciousLiving)
    living.drive = SimpleNamespace(
        token_budget_daily=1000,
        token_usage_today=1000,
        token_budget_monthly=0,
        token_usage_month=0,
    )

    assert living._token_sleep_reason() == "今日 Token 预算已用完，暂停自主活动"


def test_unlimited_token_budget_does_not_force_sleep():
    living = object.__new__(ConsciousLiving)
    living.drive = SimpleNamespace(
        token_budget_daily=0,
        token_usage_today=999999,
        token_budget_monthly=0,
        token_usage_month=999999,
    )

    assert living._token_sleep_reason() == ""
