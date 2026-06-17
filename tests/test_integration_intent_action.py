"""Integration tests for Intent → ActionDispatcher rule matching."""

import time
import pytest
from unittest.mock import patch

from xiaomei_brain.drive.engine import DriveEngine
from xiaomei_brain.drive.config import DriveConfig
from xiaomei_brain.consciousness.self_image_proxy import SelfImage
from xiaomei_brain.consciousness.action_dispatcher import ActionDispatcher
from xiaomei_brain.consciousness.rules import RULES, _init_rules


# ── Helpers ───────────────────────────────────────────────────────────

def _setup():
    """Create DriveEngine + SelfImage + ActionDispatcher, wired together."""
    drive = DriveEngine(agent_id="test", load=False, config=DriveConfig())
    si = SelfImage(drive=drive)
    # Clear and re-init rules to avoid stale state between tests
    RULES.clear()
    _init_rules()
    dispatcher = ActionDispatcher()
    dispatcher.load_rules(list(RULES))
    return drive, si, dispatcher


def _push_intent(si, intent_type: str, **kwargs):
    """Push an intent to the SelfImage intent buffer."""
    entry = {"type": intent_type.upper(), "priority": kwargs.get("priority", 50), "content": kwargs.get("content", "")}
    si.intent.intent_buffer.append(entry)


# ── Intent → Action mapping ───────────────────────────────────────────

def test_greet_intent_produces_proactive():
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "proactive"
    assert queue[0].metadata.get("intent_type") == "GREET"
    assert queue[0].source == "intent"


def test_reflect_intent_produces_trigger_l3():
    drive, si, dispatcher = _setup()
    _push_intent(si, "REFLECT")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "trigger_l3"
    assert queue[0].priority == pytest.approx(0.9)


def test_care_intent_produces_proactive():
    drive, si, dispatcher = _setup()
    _push_intent(si, "CARE")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].metadata.get("intent_type") == "CARE"
    assert queue[0].priority == pytest.approx(0.7)


def test_work_intent_produces_work_action():
    drive, si, dispatcher = _setup()
    _push_intent(si, "WORK")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "work"


def test_express_intent_produces_proactive():
    drive, si, dispatcher = _setup()
    _push_intent(si, "EXPRESS")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "proactive"
    assert queue[0].metadata.get("intent_type") == "EXPRESS"


def test_act_intent_produces_proactive():
    drive, si, dispatcher = _setup()
    _push_intent(si, "ACT")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].metadata.get("intent_type") == "ACT"


def test_talk_intent_produces_talk_to_agent():
    drive, si, dispatcher = _setup()
    _push_intent(si, "TALK_AGENT")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "talk_to_agent"


def test_alarm_intent_produces_alarm_action():
    drive, si, dispatcher = _setup()
    _push_intent(si, "ALARM")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "alarm"
    assert queue[0].priority == pytest.approx(0.85)


def test_progress_intent_produces_tool_action():
    drive, si, dispatcher = _setup()
    _push_intent(si, "PROGRESS")
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    assert queue[0].action_type.value == "tool"
    assert queue[0].content == "progress_goal"


# ── No intent → empty queue ───────────────────────────────────────────

def test_no_intent_no_actions():
    drive, si, dispatcher = _setup()
    queue = dispatcher.tick(si)
    # Only system/energy rules might fire; verify no intent-driven actions
    intent_actions = [a for a in queue if a.source == "intent"]
    assert len(intent_actions) == 0


# ── Multiple intents ──────────────────────────────────────────────────

def test_multiple_intents_all_produce_actions():
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    _push_intent(si, "REFLECT")
    _push_intent(si, "CARE")
    queue = dispatcher.tick(si)
    intent_actions = [a for a in queue if a.source == "intent"]
    assert len(intent_actions) == 3


# ── Cooldown ──────────────────────────────────────────────────────────

def test_cooldown_blocks_repeat():
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    # First tick produces action and records cooldown
    queue1 = dispatcher.tick(si)
    assert len(queue1) == 1
    dispatcher._record_fired(queue1[0].cooldown_key)
    # Second tick with same intent should be blocked by cooldown
    _push_intent(si, "GREET")  # push another one (first was consumed? no, tick doesn't consume)
    # Actually, tick doesn't consume intents. Let's just verify cooldown check.
    queue2 = dispatcher.tick(si)
    # GREET intent is still in buffer, but cooldown should block it
    greet_actions = [a for a in queue2 if a.metadata.get("intent_type") == "GREET"]
    assert len(greet_actions) == 0


def test_cooldown_expires():
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    queue1 = dispatcher.tick(si)
    assert len(queue1) == 1
    dispatcher._record_fired(queue1[0].cooldown_key)
    # Manually expire cooldown
    dispatcher._cooldown[queue1[0].cooldown_key] = time.time() - 99999
    # Now it should fire again
    queue2 = dispatcher.tick(si)
    greet_actions = [a for a in queue2 if a.metadata.get("intent_type") == "GREET"]
    assert len(greet_actions) == 1


# ── Energy gating ─────────────────────────────────────────────────────

def test_energy_critical_blocks_proactive():
    drive, si, dispatcher = _setup()
    drive.energy.level = 0.1  # below 0.15 silent threshold
    _push_intent(si, "GREET")
    queue = dispatcher.tick(si)
    proactive = [a for a in queue if a.action_type.value == "proactive"]
    assert len(proactive) == 0


def test_energy_low_allows_intent():
    """At energy 0.2 (between 0.15 and 0.3), intent-driven actions still pass."""
    drive, si, dispatcher = _setup()
    drive.energy.level = 0.2  # below 0.3 low threshold, above 0.15 silent
    _push_intent(si, "GREET")
    queue = dispatcher.tick(si)
    # Intent source should still pass (only desire/idle blocked at low energy)
    intent_actions = [a for a in queue if a.source == "intent"]
    assert len(intent_actions) == 1


# ── Idle trigger ──────────────────────────────────────────────────────

def test_idle_trigger():
    drive, si, dispatcher = _setup()
    # Set idle duration above default threshold (1800s)
    si.perception.user_idle_duration = 3600
    queue = dispatcher.tick(si)
    idle_actions = [a for a in queue if a.source == "idle"]
    assert len(idle_actions) == 1
    assert idle_actions[0].action_type.value == "proactive"


def test_idle_below_threshold_no_trigger():
    drive, si, dispatcher = _setup()
    si.perception.user_idle_duration = 100  # below default 600s
    queue = dispatcher.tick(si)
    idle_actions = [a for a in queue if a.source == "idle"]
    assert len(idle_actions) == 0


# ── Energy low notification ───────────────────────────────────────────

def test_energy_low_notification():
    drive, si, dispatcher = _setup()
    drive.energy.level = 0.05  # very low
    queue = dispatcher.tick(si)
    notify_actions = [a for a in queue if a.action_type.value == "notify"]
    assert len(notify_actions) == 1


# ── Desire rules ──────────────────────────────────────────────────────

def test_desire_cognition_threshold():
    """Cognition desire threshold is > 1.0 (deliberately high). At 0.8 it should not fire."""
    drive, si, dispatcher = _setup()
    drive.desire.cognition = 0.8  # below threshold 1.0
    queue = dispatcher.tick(si)
    desire_actions = [a for a in queue if a.source == "desire"]
    assert len(desire_actions) == 0


# ── Edge cases ─────────────────────────────────────────────────────────

def test_unknown_intent_no_match():
    """Unknown intent type should not crash — just no match."""
    drive, si, dispatcher = _setup()
    _push_intent(si, "UNKNOWN_INTENT_TYPE_XYZ")
    queue = dispatcher.tick(si)
    intent_actions = [a for a in queue if a.source == "intent"]
    assert len(intent_actions) == 0


def test_intent_buffer_not_consumed_by_tick():
    """tick() reads intents but does NOT remove them from buffer.

    This means the same intent can fire on every tick if not cleared externally.
    """
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    initial_len = len(si.intent.intent_buffer)

    dispatcher.tick(si)
    # Buffer should still contain the GREET intent
    assert len(si.intent.intent_buffer) == initial_len


def test_cooldown_key_isolation():
    """Different intents have different cooldown keys — one doesn't block the other."""
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET")
    queue1 = dispatcher.tick(si)
    dispatcher._record_fired(queue1[0].cooldown_key)

    # GREET cooldown should NOT block CARE
    _push_intent(si, "CARE")
    queue2 = dispatcher.tick(si)
    care_actions = [a for a in queue2 if a.metadata.get("intent_type") == "CARE"]
    assert len(care_actions) == 1


def test_empty_intent_buffer_system_rules_still_fire():
    """Even with no intents, system rules (energy notif) can fire."""
    drive, si, dispatcher = _setup()
    drive.energy.level = 0.05  # very low → energy notification fires
    si.intent.intent_buffer.clear()
    queue = dispatcher.tick(si)
    # System rules should still work
    assert len(queue) >= 1


def test_intent_priority_from_rule_not_buffer():
    """Action priority comes from the rule definition, NOT the intent buffer entry."""
    drive, si, dispatcher = _setup()
    _push_intent(si, "GREET", priority=90)  # buffer entry priority is ignored
    queue = dispatcher.tick(si)
    assert len(queue) == 1
    # GREET rule hardcodes priority=0.8, buffer priority=90 has no effect
    assert queue[0].priority == pytest.approx(0.8)
