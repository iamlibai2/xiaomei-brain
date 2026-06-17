"""Integration tests for Drive + Purpose engine cross-module effects."""

import pytest
from xiaomei_brain.drive.engine import DriveEngine
from xiaomei_brain.drive.config import DriveConfig
from xiaomei_brain.purpose.purpose_engine import PurposeEngine
from xiaomei_brain.purpose.goal import GoalStatus, GoalType


# ── Helpers ───────────────────────────────────────────────────────────

def _make_engines():
    """Create both engines wired together, load=False (no I/O)."""
    config = DriveConfig()
    drive = DriveEngine(agent_id="test", load=False, config=config)
    purpose = PurposeEngine(agent_id="test", load=False, drive=drive)
    return drive, purpose


# ── complete_goal → on_goal_completed ─────────────────────────────────

def test_complete_goal_boosts_dopamine():
    drive, purpose = _make_engines()
    initial = drive.hormone.dopamine
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    assert drive.hormone.dopamine > initial


def test_complete_goal_boosts_serotonin():
    drive, purpose = _make_engines()
    initial = drive.hormone.serotonin
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # serotonin += 0.2
    assert drive.hormone.serotonin == pytest.approx(initial + 0.2)


def test_complete_goal_reduces_cortisol():
    drive, purpose = _make_engines()
    initial = drive.hormone.cortisol
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # cortisol -= 0.1
    assert drive.hormone.cortisol == pytest.approx(initial - 0.1)


def test_complete_goal_adds_joy_emotion():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # Should have JOY emotion added (RPE=0.5 > 0 → JOY)
    assert "joy" in drive.emotion.emotions


def test_complete_goal_decreases_achievement():
    drive, purpose = _make_engines()
    initial = drive.desire.achievement
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # achievement -= 0.3
    assert drive.desire.achievement == pytest.approx(initial - 0.3)


def test_complete_goal_increases_survival():
    drive, purpose = _make_engines()
    initial = drive.desire.survival
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # survival += 0.05
    assert drive.desire.survival == pytest.approx(initial + 0.05)


def test_complete_goal_updates_expected_reward():
    drive, purpose = _make_engines()
    initial = drive.motivation.expected_reward
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    # expected_reward updated via learning weight
    assert drive.motivation.expected_reward != initial


def test_complete_goal_marks_completed():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    assert goal.is_completed()
    assert goal.progress == 1.0


def test_complete_goal_unknown_no_error():
    drive, purpose = _make_engines()
    purpose.complete_goal("nonexistent")  # should not raise


# ── complete_current success ──────────────────────────────────────────

def test_complete_current_success():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    assert purpose.current_goal is not None
    purpose.complete_current(success=True)
    assert goal.is_completed()


def test_complete_current_auto_switches():
    """After completing current, auto-switch to next pending goal."""
    drive, purpose = _make_engines()
    g1 = purpose.add_goal("First")
    g2 = purpose.add_goal("Second")
    # g1 was auto-activated. Switch to g1 explicitly, then complete.
    purpose.set_current(g1.id)
    initial_dopamine = drive.hormone.dopamine
    purpose.complete_current(success=True)
    # After completion, next goal should be activated
    assert purpose.current_goal is not None
    assert purpose.current_goal.id == g2.id


# ── complete_current failure → on_goal_failed ─────────────────────────

def test_complete_current_failure():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    initial_cortisol = drive.hormone.cortisol
    purpose.complete_current(success=False)
    assert goal.is_abandoned()


def test_goal_failed_increases_cortisol():
    drive, purpose = _make_engines()
    initial = drive.hormone.cortisol
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # cortisol += 0.3
    assert drive.hormone.cortisol == pytest.approx(initial + 0.3)


def test_goal_failed_decreases_dopamine():
    drive, purpose = _make_engines()
    initial = drive.hormone.dopamine
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # dopamine -= 0.2
    assert drive.hormone.dopamine == pytest.approx(initial - 0.2)


def test_goal_failed_increases_achievement():
    drive, purpose = _make_engines()
    initial = drive.desire.achievement
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # achievement += 0.2 (frustration)
    assert drive.desire.achievement == pytest.approx(initial + 0.2)


def test_goal_failed_decreases_survival():
    drive, purpose = _make_engines()
    initial = drive.desire.survival
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # survival -= 0.08
    assert drive.desire.survival == pytest.approx(initial - 0.08)


def test_goal_failed_decreases_serotonin():
    drive, purpose = _make_engines()
    initial = drive.hormone.serotonin
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # serotonin -= 0.15
    assert drive.hormone.serotonin == pytest.approx(initial - 0.15)


def test_goal_failed_adds_sadness():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)
    # SADNESS emotion should be added
    assert "sadness" in drive.emotion.emotions


# ── update_progress → on_goal_progress ────────────────────────────────

def test_update_progress_partial():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    goal.progress = 0.0
    purpose.update_progress(goal.id, 0.5)
    assert goal.progress == 0.5


def test_update_progress_clamped():
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.update_progress(goal.id, 2.0)
    assert goal.progress == 1.0  # clamped


# ── PurposeEngine without drive ───────────────────────────────────────

def test_complete_goal_without_drive():
    """PurposeEngine without Drive should not crash."""
    purpose = PurposeEngine(agent_id="test", load=False, drive=None)
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)  # should not raise
    assert goal.is_completed()


def test_complete_current_without_drive():
    purpose = PurposeEngine(agent_id="test", load=False, drive=None)
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=True)  # should not raise


# ── Edge cases ─────────────────────────────────────────────────────────

def test_complete_goal_twice_double_boost():
    """BUG: completing an already-completed goal triggers Drive hooks again.

    complete_goal() has no guard against re-completing a COMPLETED goal.
    This causes double dopamine/serotonin boost and double cortisol reduction.
    """
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.complete_goal(goal.id)
    dopamine_after_first = drive.hormone.dopamine
    serotonin_after_first = drive.hormone.serotonin

    # Complete the same goal again — should be a no-op but isn't
    purpose.complete_goal(goal.id)
    assert drive.hormone.dopamine > dopamine_after_first  # double boosted
    assert drive.hormone.serotonin > serotonin_after_first  # double boosted


def test_complete_nonexistent_goal():
    """Completing a nonexistent goal ID should not crash or affect Drive."""
    drive, purpose = _make_engines()
    initial_dopamine = drive.hormone.dopamine
    purpose.complete_goal("nonexistent_id_12345")
    # Drive should be unchanged
    assert drive.hormone.dopamine == initial_dopamine


def test_abandon_then_complete():
    """Abandoned goal can be completed — status changes to COMPLETED."""
    drive, purpose = _make_engines()
    goal = purpose.add_goal("Test goal")
    purpose.complete_current(success=False)  # ABANDONED
    assert goal.is_abandoned()
    # Re-complete the abandoned goal
    purpose.complete_goal(goal.id)
    assert goal.is_completed()


def test_add_goal_auto_activates_first():
    """First goal added should become current_goal."""
    purpose = PurposeEngine(agent_id="test", load=False, drive=None)
    assert purpose.current_goal is None
    goal = purpose.add_goal("First goal")
    assert purpose.current_goal is not None
    assert purpose.current_goal.id == goal.id
