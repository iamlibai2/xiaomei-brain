"""Tests for purpose/purpose_engine.py -- PurposeEngine with load=False."""

import time
import pytest
from unittest.mock import patch
from xiaomei_brain.purpose.purpose_engine import PurposeEngine
from xiaomei_brain.purpose.goal import Goal, GoalType, GoalStatus


# ── Helpers ───────────────────────────────────────────────────────────

def _make_engine() -> PurposeEngine:
    """Create a PurposeEngine with load=False (no I/O)."""
    return PurposeEngine(agent_id="test", load=False)


# ── add_goal ──────────────────────────────────────────────────────────

def test_add_goal_simple():
    eng = _make_engine()
    goal = eng.add_goal("Test goal")
    assert goal.description == "Test goal"
    assert goal.goal_type == GoalType.EXECUTABLE
    assert goal.priority == 0.5
    assert goal.id in eng.goals
    # auto-activates when no current goal
    assert eng.current_goal is not None
    assert eng.current_goal.id == goal.id


def test_add_goal_with_parent_id():
    eng = _make_engine()
    parent = eng.add_goal("Parent", goal_type=GoalType.PHASE)
    child = eng.add_goal("Child", parent_id=parent.id)
    assert child.parent_id == parent.id


def test_add_goal_with_depends_on():
    eng = _make_engine()
    dep1 = eng.add_goal("Dep 1")
    eng.current_goal = None  # reset so auto-activate doesn't interfere
    dep2 = eng.add_goal("Dep 2", depends_on=[dep1.id])
    assert dep2.depends_on == [dep1.id]
    # blocked_by should be recomputed
    assert dep2.id in eng.goals[dep1.id].blocked_by


def test_add_goal_pending_queue():
    """When a goal is added but NOT auto-activated, it goes to pending queue."""
    eng = _make_engine()
    eng.current_goal = None  # reset
    # PHASE goals don't auto-activate
    goal = eng.add_goal("Pending goal", goal_type=GoalType.PHASE)
    assert goal.id in eng.pending_queue


def test_add_goal_auto_activate_only_executable():
    """auto-activate only for EXECUTABLE goals."""
    eng = _make_engine()
    eng.current_goal = None
    goal = eng.add_goal("Phase", goal_type=GoalType.PHASE)
    assert eng.current_goal is None  # PHASE doesn't auto-activate


def test_add_goal_depends_on_blocks_auto_activate():
    """add_goal auto-activates even if depends_on not satisfied (set_current doesn't check DAG)."""
    eng = _make_engine()
    dep = eng.add_goal("Dep")
    eng.current_goal = None
    child = eng.add_goal("Child", depends_on=[dep.id])
    # add_goal auto-activates via set_current (which doesn't check DAG)
    assert eng.current_goal is not None
    assert eng.current_goal.id == child.id


# ── set_current ───────────────────────────────────────────────────────

def test_set_current():
    eng = _make_engine()
    g1 = eng.add_goal("First")
    g2 = eng.add_goal("Second")
    # g1 was auto-activated, now switch to g2
    eng.set_current(g2.id)
    assert eng.current_goal.id == g2.id
    assert eng.goals[g1.id].status == GoalStatus.PENDING


def test_set_current_unknown():
    eng = _make_engine()
    eng.set_current("nonexistent")  # should not raise
    assert eng.current_goal is None


def test_set_current_does_not_touch_completed():
    """set_current should not change status of COMPLETED goals."""
    eng = _make_engine()
    g1 = eng.add_goal("First")
    g1.complete()
    g2 = eng.add_goal("Second")
    eng.current_goal = g1
    g1.status = GoalStatus.COMPLETED
    eng.set_current(g2.id)
    # completed goal should stay completed
    assert eng.goals[g1.id].status == GoalStatus.COMPLETED


# ── get_next ──────────────────────────────────────────────────────────

def test_get_next_empty_queue():
    eng = _make_engine()
    eng.pending_queue = []
    assert eng.get_next() is None


def test_get_next_by_priority():
    eng = _make_engine()
    eng.current_goal = None
    g1 = eng.add_goal("Low", priority=0.3)
    g2 = eng.add_goal("High", priority=0.9)
    # Reset current so both go to pending
    eng.current_goal = None
    eng.set_current("nonexistent")  # force current_goal = None
    # Manually set both to PENDING
    eng.goals[g1.id].status = GoalStatus.PENDING
    eng.goals[g2.id].status = GoalStatus.PENDING
    eng.pending_queue = [g1.id, g2.id]
    next_goal = eng.get_next()
    assert next_goal is not None
    assert next_goal.id == g2.id  # higher priority


def test_get_next_dag_blocks():
    """get_next should skip goals with unsatisfied dependencies."""
    eng = _make_engine()
    eng.current_goal = None
    dep = eng.add_goal("Dep", priority=0.9)
    child = eng.add_goal("Child", priority=0.5, depends_on=[dep.id])
    eng.current_goal = None
    eng.goals[dep.id].status = GoalStatus.PENDING
    eng.goals[child.id].status = GoalStatus.PENDING
    eng.pending_queue = [dep.id, child.id]
    eng._recompute_blocked_by()
    next_goal = eng.get_next()
    assert next_goal is not None
    assert next_goal.id == dep.id  # child blocked by dep


def test_get_next_all_blocked():
    """When all pending goals are blocked, return None."""
    eng = _make_engine()
    eng.current_goal = None
    dep = eng.add_goal("Dep")
    child = eng.add_goal("Child", depends_on=[dep.id])
    eng.current_goal = None
    eng.pending_queue = [child.id]  # only child is pending
    eng.goals[child.id].status = GoalStatus.PENDING
    eng._recompute_blocked_by()
    assert eng.get_next() is None


def test_get_next_after_dep_completed():
    """After dependency completes, child becomes available."""
    eng = _make_engine()
    eng.current_goal = None
    dep = eng.add_goal("Dep")
    child = eng.add_goal("Child", depends_on=[dep.id])
    eng.current_goal = None
    eng.goals[dep.id].status = GoalStatus.PENDING
    eng.goals[child.id].status = GoalStatus.PENDING
    eng.pending_queue = [dep.id, child.id]
    eng._recompute_blocked_by()
    # Complete dep and remove from pending (as would happen in normal flow)
    eng.complete_goal(dep.id)
    eng.pending_queue.remove(dep.id)
    next_goal = eng.get_next()
    assert next_goal is not None
    assert next_goal.id == child.id


# ── complete_goal ─────────────────────────────────────────────────────

def test_complete_goal():
    eng = _make_engine()
    goal = eng.add_goal("To complete")
    eng.complete_goal(goal.id)
    assert eng.goals[goal.id].is_completed()
    assert eng.goals[goal.id].progress == 1.0


def test_complete_goal_unknown():
    eng = _make_engine()
    eng.complete_goal("nonexistent")  # should not raise


# ── calculate_priority ────────────────────────────────────────────────

def test_calculate_priority_base():
    eng = _make_engine()
    goal = eng.add_goal("Test", priority=0.5)
    # base(0.5) + reinforcement(0) + deadline(0) + type_weight(EXECUTABLE=0.3) = 0.8
    assert eng.calculate_priority(goal) == 0.8


def test_calculate_priority_capped():
    eng = _make_engine()
    goal = eng.add_goal("Test", priority=1.0)
    # 1.0 + 0 + 0 + 0.3 = 1.3 → capped at 1.0
    assert eng.calculate_priority(goal) == 1.0


def test_calculate_priority_with_reinforcement():
    eng = _make_engine()
    goal = eng.add_goal("Test", priority=0.3)
    goal.reinforce()
    goal.reinforce()
    # base(0.3) + reinforcement(2*0.05=0.1) + deadline(0) + type(0.3) = 0.7
    assert eng.calculate_priority(goal) == pytest.approx(0.7)


def test_calculate_priority_with_deadline():
    eng = _make_engine()
    future = time.time() + 86400  # 1 day from now
    goal = eng.add_goal("Test", priority=0.3, deadline=future)
    # base(0.3) + reinforcement(0) + deadline(remaining/86400, cap 0.1) + type(0.3)
    # remaining ≈ 86400, deadline_boost = min(0.1, 86400/86400) = 0.1
    # total = 0.3 + 0 + 0.1 + 0.3 = 0.7
    assert eng.calculate_priority(goal) == pytest.approx(0.7, rel=0.1)


def test_calculate_priority_type_weights():
    eng = _make_engine()
    eng.current_goal = None
    exe = eng.add_goal("Executable", goal_type=GoalType.EXECUTABLE, priority=0.3)
    phase = eng.add_goal("Phase", goal_type=GoalType.PHASE, priority=0.3)
    strategic = eng.add_goal("Strategic", goal_type=GoalType.STRATEGIC, priority=0.3)
    assert eng.calculate_priority(exe) == pytest.approx(0.6)
    assert eng.calculate_priority(phase) == pytest.approx(0.5)
    assert eng.calculate_priority(strategic) == pytest.approx(0.4)


# ── decompose_goal ────────────────────────────────────────────────────

def test_decompose_goal():
    eng = _make_engine()
    parent = eng.add_goal("Learn Python", goal_type=GoalType.PHASE)
    subs = eng.decompose_goal(parent.id, ["Read docs", "Write code", "Review"])
    assert len(subs) == 3
    for sub in subs:
        assert sub.parent_id == parent.id
        assert sub.goal_type == GoalType.EXECUTABLE
        assert sub.depth == 1  # parent.depth(0) + 1


def test_decompose_goal_max_depth():
    eng = _make_engine()
    parent = eng.add_goal("Root")
    # First decomposition
    subs = eng.decompose_goal(parent.id, ["Sub 1"])
    assert len(subs) == 1
    assert subs[0].depth == 1
    # Second decomposition should be rejected (depth 1 >= MAX_DEPTH 2? No, 1 < 2)
    subs2 = eng.decompose_goal(subs[0].id, ["Sub-sub 1"])
    assert len(subs2) == 1
    assert subs2[0].depth == 2
    # Third decomposition rejected (depth 2 >= MAX_DEPTH 2)
    subs3 = eng.decompose_goal(subs2[0].id, ["Sub-sub-sub 1"])
    assert len(subs3) == 0


def test_decompose_goal_unknown():
    eng = _make_engine()
    result = eng.decompose_goal("nonexistent", ["Sub"])
    assert result == []


# ── get_sub_goals ─────────────────────────────────────────────────────

def test_get_sub_goals():
    eng = _make_engine()
    parent = eng.add_goal("Parent", goal_type=GoalType.PHASE)
    eng.decompose_goal(parent.id, ["Sub 1", "Sub 2"])
    subs = eng.get_sub_goals(parent.id)
    assert len(subs) == 2


def test_get_sub_goals_empty():
    eng = _make_engine()
    assert eng.get_sub_goals("nonexistent") == []


# ── get_goal_tree ─────────────────────────────────────────────────────

def test_get_goal_tree():
    eng = _make_engine()
    eng.add_goal("Test")
    # With load=False, meaning is not set; mock it for get_goal_tree
    from xiaomei_brain.purpose.meaning import Meaning
    eng.meaning = Meaning()
    tree = eng.get_goal_tree()
    assert "goals" in tree
    assert "current" in tree
    assert "pending" in tree


# ── pause / resume ────────────────────────────────────────────────────

def test_pause_goal():
    eng = _make_engine()
    goal = eng.add_goal("To pause")
    result = eng.pause_goal(goal.id)
    assert result is not None
    assert result.is_paused()


def test_pause_goal_unknown():
    eng = _make_engine()
    assert eng.pause_goal("nonexistent") is None


def test_resume_goal():
    eng = _make_engine()
    goal = eng.add_goal("To resume")
    eng.pause_goal(goal.id)
    result = eng.resume_goal(goal.id)
    assert result is not None
    assert result.is_active()


def test_resume_goal_unknown():
    eng = _make_engine()
    assert eng.resume_goal("nonexistent") is None
