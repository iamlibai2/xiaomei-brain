"""Tests for metacognition/types.py -- enums and dataclasses."""

import pytest
from xiaomei_brain.metacognition.types import (
    SurpriseType,
    StuckClass,
    MetaSuggestion,
    StepObservation,
    StepCheckResult,
    TaskLesson,
    PACECheckpoint,
)


# ── Enums ─────────────────────────────────────────────────────────────

def test_surprise_type_values():
    assert SurpriseType.TOOL_LOOP.value == "tool_loop"
    assert SurpriseType.TOOL_STORM.value == "tool_storm"
    assert SurpriseType.EMPTY_RESPONSE.value == "empty_response"
    assert SurpriseType.REPEATED_OUTPUT.value == "repeated_output"
    assert SurpriseType.SLOW_STEP.value == "slow_step"
    assert SurpriseType.NO_PROGRESS.value == "no_progress"
    assert SurpriseType.GAVE_UP.value == "gave_up"
    assert SurpriseType.VAGUE_GOAL.value == "vague_goal"


def test_stuck_class_values():
    assert StuckClass.TOOL_LOOP.value == "tool_loop"
    assert StuckClass.UNCLEAR.value == "unclear"
    assert StuckClass.BLOCKED.value == "blocked"
    assert StuckClass.OUT_OF_SCOPE.value == "out_of_scope"
    assert StuckClass.GAVE_UP.value == "gave_up"


def test_meta_suggestion_values():
    assert MetaSuggestion.CONTINUE.value == "continue"
    assert MetaSuggestion.CLARIFY.value == "clarify"
    assert MetaSuggestion.SIMPLIFY.value == "simplify"
    assert MetaSuggestion.RETRY_DIFFERENT.value == "retry_different"
    assert MetaSuggestion.REPORT_PARTIAL.value == "report_partial"
    assert MetaSuggestion.ESCALATE.value == "escalate"


# ── StepObservation ───────────────────────────────────────────────────

def test_step_observation_defaults():
    obs = StepObservation(
        step_index=0,
        goal_description="test",
        llm_output="output",
        tool_calls=[],
        tool_call_count=0,
        elapsed_seconds=0.5,
        has_progress_tag=False,
        progress_status=None,
    )
    assert obs.step_index == 0
    assert obs.surprises == []
    assert obs.raw_content == ""


# ── StepCheckResult ───────────────────────────────────────────────────

def test_step_check_result_defaults():
    result = StepCheckResult(
        step_index=0,
        suggestion=MetaSuggestion.CONTINUE,
    )
    assert result.should_continue is True
    assert result.stuck_class is None
    assert result.nudge == ""
    assert result.surprises == []


# ── TaskLesson ────────────────────────────────────────────────────────

def test_task_lesson_to_dict():
    lesson = TaskLesson(
        task_id="task1",
        task_description="test task",
        what_worked=["step 1"],
        what_failed=["step 2"],
    )
    d = lesson.to_dict()
    assert d["task_id"] == "task1"
    assert d["what_worked"] == ["step 1"]
    assert d["total_steps"] == 0


# ── PACECheckpoint ────────────────────────────────────────────────────

def test_pace_checkpoint_to_dict():
    cp = PACECheckpoint(
        goal_id="g1",
        step_index=5,
        observations_json="[]",
        budget_call_count=10,
    )
    d = cp.to_dict()
    assert d["goal_id"] == "g1"
    assert d["step_index"] == 5
    assert d["observations_json"] == "[]"
    assert d["budget_call_count"] == 10
