"""Tests for purpose/goal.py -- Goal state machine, DAG deps, serialization."""

import pytest
import time
from xiaomei_brain.purpose.goal import (
    Goal, GoalType, GoalStatus, TaskType, CognitiveLogEntry,
)


# ── GoalType / GoalStatus / TaskType enums ────────────────────────────

def test_goal_type_values():
    assert GoalType.STRATEGIC.value == "strategic"
    assert GoalType.PHASE.value == "phase"
    assert GoalType.EXECUTABLE.value == "executable"


def test_goal_status_values():
    assert GoalStatus.PENDING.value == "pending"
    assert GoalStatus.ACTIVE.value == "active"
    assert GoalStatus.COMPLETED.value == "completed"
    assert GoalStatus.ABANDONED.value == "abandoned"
    assert GoalStatus.PAUSED.value == "paused"


def test_task_type_values():
    assert TaskType.EXECUTION.value == "execution"
    assert TaskType.LEARNING.value == "learning"
    assert TaskType.REFLECTION.value == "reflection"
    assert TaskType.RELATIONSHIP.value == "relationship"
    assert TaskType.EXPLORATION.value == "exploration"


# ── Goal defaults ─────────────────────────────────────────────────────

def test_goal_defaults():
    g = Goal()
    assert g.goal_type == GoalType.EXECUTABLE
    assert g.status == GoalStatus.PENDING
    assert g.priority == 0.5
    assert g.progress == 0.0
    assert g.reinforcement_count == 0
    assert g.depth == 0
    assert g.depends_on == []
    assert g.blocked_by == []
    assert len(g.id) == 8


def test_goal_max_depth():
    assert Goal.MAX_DEPTH == 2


# ── State transitions ─────────────────────────────────────────────────

def test_activate():
    g = Goal(description="test")
    g.activate()
    assert g.status == GoalStatus.ACTIVE


def test_complete():
    g = Goal(description="test")
    g.complete()
    assert g.status == GoalStatus.COMPLETED
    assert g.progress == 1.0


def test_abandon():
    g = Goal(description="test")
    g.abandon()
    assert g.status == GoalStatus.ABANDONED


def test_pause_with_context():
    g = Goal(description="test")
    g.pause("cognitive snapshot")
    assert g.status == GoalStatus.PAUSED
    assert g.metadata["context_cache"] == "cognitive snapshot"


def test_pause_without_context():
    g = Goal(description="test")
    g.pause()
    assert g.status == GoalStatus.PAUSED
    assert "context_cache" not in g.metadata


def test_is_paused():
    g = Goal(description="test", status=GoalStatus.PAUSED)
    assert g.is_paused() is True


def test_get_context_cache():
    g = Goal(description="test")
    g.pause("snapshot text")
    assert g.get_context_cache() == "snapshot text"


def test_get_context_cache_empty():
    g = Goal(description="test")
    assert g.get_context_cache() == ""


# ── Progress ──────────────────────────────────────────────────────────

def test_update_progress():
    g = Goal(description="test")
    g.update_progress(0.3)
    assert g.progress == 0.3
    g.update_progress(0.3)
    assert g.progress == 0.6


def test_update_progress_upper_bound():
    g = Goal(description="test")
    g.update_progress(2.0)
    assert g.progress == 1.0


def test_update_progress_lower_bound():
    g = Goal(description="test", progress=0.5)
    g.update_progress(-1.0)
    assert g.progress == 0.0


# ── Reinforcement ─────────────────────────────────────────────────────

def test_reinforce():
    g = Goal(description="test")
    g.reinforce()
    assert g.reinforcement_count == 1
    g.reinforce()
    assert g.reinforcement_count == 2


# ── Status checks ─────────────────────────────────────────────────────

def test_is_active():
    g = Goal(description="test", status=GoalStatus.ACTIVE)
    assert g.is_active() is True
    assert g.is_pending() is False


def test_is_completed():
    g = Goal(description="test", status=GoalStatus.COMPLETED)
    assert g.is_completed() is True


def test_is_pending():
    g = Goal(description="test", status=GoalStatus.PENDING)
    assert g.is_pending() is True


def test_is_abandoned():
    g = Goal(description="test", status=GoalStatus.ABANDONED)
    assert g.is_abandoned() is True


# ── DAG dependencies ──────────────────────────────────────────────────

def test_all_deps_satisfied_no_deps():
    g = Goal(description="test")
    assert g.all_deps_satisfied({}) is True


def test_all_deps_satisfied_all_completed():
    g1 = Goal(id="dep1", description="dep1", status=GoalStatus.COMPLETED)
    g2 = Goal(description="main", depends_on=["dep1"])
    assert g2.all_deps_satisfied({"dep1": g1}) is True


def test_all_deps_satisfied_partial():
    g1 = Goal(id="dep1", description="dep1", status=GoalStatus.PENDING)
    g2 = Goal(id="dep2", description="dep2", status=GoalStatus.COMPLETED)
    g3 = Goal(description="main", depends_on=["dep1", "dep2"])
    assert g3.all_deps_satisfied({"dep1": g1, "dep2": g2}) is False


def test_all_deps_satisfied_missing():
    g = Goal(description="main", depends_on=["missing_dep"])
    assert g.all_deps_satisfied({}) is False


# ── get_task_type ─────────────────────────────────────────────────────

def test_get_task_type_default():
    g = Goal(description="test")
    assert g.get_task_type() == TaskType.EXECUTION


def test_get_task_type_custom():
    g = Goal(description="test", metadata={"task_type": "learning"})
    assert g.get_task_type() == TaskType.LEARNING


def test_get_task_type_invalid():
    g = Goal(description="test", metadata={"task_type": "invalid"})
    assert g.get_task_type() == TaskType.EXECUTION  # fallback


# ── get_summary ───────────────────────────────────────────────────────

def test_get_summary():
    g = Goal(description="完成测试", goal_type=GoalType.EXECUTABLE, status=GoalStatus.ACTIVE, progress=0.5)
    summary = g.get_summary()
    assert "完成测试" in summary
    assert "进行中" in summary
    assert "50%" in summary


# ── to_dict / from_dict round-trip ────────────────────────────────────

def test_goal_to_dict():
    g = Goal(description="test", goal_type=GoalType.EXECUTABLE)
    d = g.to_dict()
    assert d["description"] == "test"
    assert d["goal_type"] == "executable"
    assert d["status"] == "pending"


def test_goal_from_dict():
    g = Goal()
    g.from_dict({"description": "restored", "goal_type": "phase", "priority": 0.8})
    assert g.description == "restored"
    assert g.goal_type == GoalType.PHASE
    assert g.priority == 0.8


def test_goal_to_from_roundtrip():
    g = Goal(description="roundtrip", goal_type=GoalType.PHASE, status=GoalStatus.ACTIVE)
    g.reinforce()
    g.update_progress(0.5)
    d = g.to_dict()
    g2 = Goal()
    g2.from_dict(d)
    assert g2.description == "roundtrip"
    assert g2.goal_type == GoalType.PHASE
    assert g2.reinforcement_count == 1
    assert g2.progress == 0.5


# ── CognitiveLogEntry ─────────────────────────────────────────────────

def test_cognitive_log_entry_defaults():
    entry = CognitiveLogEntry(entry_type="decision", content="chose A")
    assert entry.entry_type == "decision"
    assert entry.content == "chose A"
    assert entry.sub_goal_id is None


def test_cognitive_log_entry_to_from_dict():
    entry = CognitiveLogEntry(entry_type="discovery", content="found bug", sub_goal_id="sg1")
    d = entry.to_dict()
    restored = CognitiveLogEntry.from_dict(d)
    assert restored.entry_type == "discovery"
    assert restored.content == "found bug"
    assert restored.sub_goal_id == "sg1"


# ── append_log ────────────────────────────────────────────────────────

def test_append_log():
    g = Goal(description="test")
    entry = g.append_log("decision", "chose path A")
    assert entry.entry_type == "decision"
    assert entry.content == "chose path A"
    assert len(g.cognitive_log) == 1


# ── add_artifact ──────────────────────────────────────────────────────

def test_add_artifact():
    g = Goal(description="test")
    g.add_artifact("/tmp/output.md", role="output")
    assert len(g.artifacts) == 1
    assert g.artifacts[0]["path"] == "/tmp/output.md"
    assert g.artifacts[0]["role"] == "output"
