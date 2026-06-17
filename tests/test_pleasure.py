"""Tests for drive/embody/pleasure.py -- PleasureCenter model."""

import pytest
from xiaomei_brain.drive.embody.pleasure import PleasureCenter


# ── Defaults ──────────────────────────────────────────────────────────

def test_pleasure_center_defaults():
    pc = PleasureCenter()
    assert pc.pleasure_value == 0.5
    assert pc.craving == 0.0
    assert pc.expected_pleasure == 0.5
    assert pc._hit_count == 0
    assert pc._resist_count == 0


# ── hit ───────────────────────────────────────────────────────────────

def test_hit_increases_pleasure():
    pc = PleasureCenter()
    pc.hit()
    assert pc.pleasure_value == pytest.approx(0.65)  # 0.5 + 0.15
    assert pc.expected_pleasure == pytest.approx(0.52)  # 0.5 + 0.02
    assert pc.craving == 0.0
    assert pc._hit_count == 1


def test_hit_pleasure_ceiling():
    pc = PleasureCenter()
    pc.pleasure_value = 0.9
    pc.hit()
    assert pc.pleasure_value == 1.0  # clamped
    assert pc.expected_pleasure == 0.52


def test_hit_increments_count():
    pc = PleasureCenter()
    pc.hit()
    pc.hit()
    assert pc._hit_count == 2


def test_hit_returns_sensation_string():
    pc = PleasureCenter()
    result = pc.hit()
    assert isinstance(result, str)
    assert len(result) > 0


# ── resist ────────────────────────────────────────────────────────────

def test_resist_decreases_expected():
    pc = PleasureCenter()
    pc.resist()
    assert pc.expected_pleasure == 0.45  # 0.5 - 0.05
    assert pc._resist_count == 1


def test_resist_expected_floor():
    pc = PleasureCenter()
    pc.expected_pleasure = 0.32
    pc.resist()
    assert pc.expected_pleasure == 0.3  # floor at 0.3


def test_resist_recalculates_craving():
    pc = PleasureCenter()
    pc.pleasure_value = 0.3
    pc.expected_pleasure = 0.6
    pc.resist()
    # expected drops to 0.55, craving = max(0, 0.55 - 0.3) = 0.25
    assert pc.craving == pytest.approx(0.25)


# ── tick_minute ───────────────────────────────────────────────────────

def test_tick_minute_decay():
    pc = PleasureCenter()
    pc.pleasure_value = 0.8
    pc.expected_pleasure = 0.7
    pc.tick_minute()
    assert pc.pleasure_value == 0.79  # 0.8 - 0.01
    # craving = max(0, 0.69 - 0.79) = 0.0
    assert pc.craving == 0.0
    assert pc.expected_pleasure == 0.69  # 0.7 - 0.01


def test_tick_minute_pleasure_floor():
    pc = PleasureCenter()
    pc.pleasure_value = 0.0
    pc.tick_minute()
    assert pc.pleasure_value == 0.0  # floor at 0


def test_tick_minute_expected_floor():
    pc = PleasureCenter()
    pc.expected_pleasure = 0.5
    pc.tick_minute()
    assert pc.expected_pleasure == 0.5  # floor at 0.5


def test_tick_minute_craving_grows():
    pc = PleasureCenter()
    pc.pleasure_value = 0.3
    pc.expected_pleasure = 0.5
    pc.tick_minute()
    assert pc.pleasure_value == 0.29
    # expected_pleasure floor at 0.5 → stays 0.5
    # craving = max(0, 0.5 - 0.29) = 0.21
    assert pc.craving == pytest.approx(0.21)


# ── to_dict / from_dict ───────────────────────────────────────────────

def test_pleasure_center_to_dict():
    pc = PleasureCenter()
    pc.hit()
    d = pc.to_dict()
    assert "pleasure_value" in d
    assert "craving" in d
    assert "expected_pleasure" in d
    assert d["hit_count"] == 1


def test_pleasure_center_from_dict():
    pc = PleasureCenter()
    pc.from_dict({
        "pleasure_value": 0.8,
        "craving": 0.3,
        "expected_pleasure": 0.6,
        "hit_count": 3,
        "resist_count": 1,
    })
    assert pc.pleasure_value == 0.8
    assert pc.craving == 0.3
    assert pc._hit_count == 3
    assert pc._resist_count == 1


# ── reset ─────────────────────────────────────────────────────────────

def test_pleasure_center_reset():
    pc = PleasureCenter()
    pc.hit()
    pc.hit()
    pc.resist()
    pc.reset()
    assert pc.pleasure_value == 0.5
    assert pc.craving == 0.0
    assert pc.expected_pleasure == 0.5
    assert pc._hit_count == 0
    assert pc._resist_count == 0
