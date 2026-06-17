"""Tests for consciousness/action_item.py -- ActionItem sort key and helpers."""

import pytest
from xiaomei_brain.consciousness.action_item import ActionType, ActionItem


# ── ActionType enum ───────────────────────────────────────────────────

def test_action_type_values():
    assert ActionType.PROACTIVE.value == "proactive"
    assert ActionType.ALARM.value == "alarm"
    assert ActionType.WORK.value == "work"
    assert ActionType.TRIGGER_L3.value == "trigger_l3"
    assert ActionType.TOOL.value == "tool"
    assert ActionType.NOTIFY.value == "notify"
    assert ActionType.TALK_TO_AGENT.value == "talk_to_agent"


def test_action_type_count():
    assert len(ActionType) == 7


# ── ActionItem sort_key ───────────────────────────────────────────────

def _make_item(source: str, priority: float) -> ActionItem:
    return ActionItem(
        action_type=ActionType.PROACTIVE,
        priority=priority,
        content="test",
        reason="test",
        source=source,
        cooldown_key="",
    )


def test_sort_key_source_order():
    """intent (0) < desire (1) < goal (2) < system (3)."""
    intent_item = _make_item("intent", 0.5)
    desire_item = _make_item("desire", 0.9)  # higher priority but lower source order
    # intent has source_priority=0, desire has source_priority=1
    # sort_key returns (source_priority, -priority)
    assert intent_item.sort_key() < desire_item.sort_key()


def test_sort_key_priority_within_source():
    """Same source — higher priority sorts first (more negative)."""
    a = _make_item("intent", 0.9)
    b = _make_item("intent", 0.5)
    assert a.sort_key() < b.sort_key()  # 0.9 has more negative second element


def test_sort_key_unknown_source():
    """Unknown source defaults to priority 3 (lowest)."""
    item = _make_item("unknown_source", 1.0)
    assert item.sort_key()[0] == 3


def test_sort_key_high_priority_but_low_source():
    """Desire with priority=1.0 still loses to intent with priority=0.1."""
    intent_low = _make_item("intent", 0.1)
    desire_high = _make_item("desire", 1.0)
    assert intent_low.sort_key() < desire_high.sort_key()


# ── with_metadata ─────────────────────────────────────────────────────

def test_with_metadata():
    item = _make_item("intent", 0.5)
    result = item.with_metadata(key1="val1", key2="val2")
    assert result is item  # returns self
    assert item.metadata["key1"] == "val1"
    assert item.metadata["key2"] == "val2"


def test_with_metadata_chain():
    item = _make_item("intent", 0.5)
    item.with_metadata(a=1).with_metadata(b=2)
    assert item.metadata == {"a": 1, "b": 2}


# ── default_cooldown_key ──────────────────────────────────────────────

def test_default_cooldown_key():
    item = _make_item("intent", 0.5)
    assert item.cooldown_key == ""
