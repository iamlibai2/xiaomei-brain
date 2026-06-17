"""Tests for drive/embody/wear.py -- BodyWear formulas."""

import pytest
from unittest.mock import patch
from xiaomei_brain.drive.embody.wear import BodyWear


# ── Defaults ──────────────────────────────────────────────────────────

def test_body_wear_defaults():
    bw = BodyWear()
    assert bw.pleasure_overload_count == 0
    assert bw.pleasure_ceiling == 1.0
    assert bw.high_cortisol_accumulated == 0.0
    assert bw.memory_erosion_count == 0
    assert bw.low_serotonin_accumulated == 0.0
    assert bw.emotional_blunting == 0
    assert bw.belonging_satisfaction_count == 0
    assert bw.oxytocin_gain_coefficient == 1.0
    assert bw.energy_baseline == 0.0
    assert bw.energy_recovery_rate == 0.1


# ── to_dict / from_dict ───────────────────────────────────────────────

def test_body_wear_to_dict():
    bw = BodyWear()
    d = bw.to_dict()
    assert d["pleasure_ceiling"] == 1.0
    assert d["oxytocin_gain_coefficient"] == 1.0


def test_body_wear_from_dict():
    bw = BodyWear.from_dict({
        "pleasure_overload_count": 5,
        "pleasure_ceiling": 0.8,
        "emotional_blunting": 2,
    })
    assert bw.pleasure_overload_count == 5
    assert bw.pleasure_ceiling == 0.8
    assert bw.emotional_blunting == 2


def test_body_wear_to_from_roundtrip():
    bw = BodyWear()
    bw.on_pleasure_hit()
    bw.on_belonging_satisfied()
    d = bw.to_dict()
    bw2 = BodyWear.from_dict(d)
    assert bw2.pleasure_overload_count == 1
    assert bw2.belonging_satisfaction_count == 1


# ── on_pleasure_hit ───────────────────────────────────────────────────

def test_on_pleasure_hit_increments():
    bw = BodyWear()
    bw.on_pleasure_hit()
    assert bw.pleasure_overload_count == 1
    # ceiling = max(0.3, 1.0 - 1 * 0.005) = 0.995
    assert bw.pleasure_ceiling == pytest.approx(0.995)


def test_on_pleasure_hit_ceiling_floor():
    bw = BodyWear()
    bw.pleasure_overload_count = 200  # 200 * 0.005 = 1.0, ceiling = max(0.3, 0) = 0.3
    bw.on_pleasure_hit()
    assert bw.pleasure_ceiling == 0.3


# ── tick_cortisol ─────────────────────────────────────────────────────

def test_tick_cortisol_high():
    bw = BodyWear()
    bw.tick_cortisol(0.8, minutes=10)
    assert bw.high_cortisol_accumulated == 10


def test_tick_cortisol_accumulate_to_30():
    """Accumulate 30+ minutes to trigger the random check block."""
    bw = BodyWear()
    bw.tick_cortisol(0.8, minutes=30)
    assert bw.high_cortisol_accumulated == 30


def test_tick_cortisol_low_reduces():
    bw = BodyWear()
    bw.high_cortisol_accumulated = 10
    bw.tick_cortisol(0.2, minutes=5)
    # 10 - 5*2 = 0, floor at 0
    assert bw.high_cortisol_accumulated == 0


def test_tick_cortisol_erosion_trigger():
    """Memory erosion triggered when random < 0.05 (patched)."""
    bw = BodyWear()
    bw.high_cortisol_accumulated = 30
    with patch("random.random", return_value=0.01):  # 0.01 < 0.05 → triggers
        bw.tick_cortisol(0.8, minutes=1)
    assert bw.memory_erosion_count == 1


def test_tick_cortisol_no_erosion():
    """Memory erosion NOT triggered when random >= 0.05."""
    bw = BodyWear()
    bw.high_cortisol_accumulated = 30
    with patch("random.random", return_value=0.5):  # 0.5 >= 0.05 → no trigger
        bw.tick_cortisol(0.8, minutes=1)
    assert bw.memory_erosion_count == 0


# ── tick_serotonin ────────────────────────────────────────────────────

def test_tick_serotonin_low_accumulates():
    bw = BodyWear()
    bw.tick_serotonin(0.2, hours=3)
    assert bw.low_serotonin_accumulated == 3
    assert bw.emotional_blunting == 1  # >= 2h → L1


def test_tick_serotonin_l2():
    bw = BodyWear()
    # tick_serotonin uses elif — only one level per call.
    # Build up incrementally: 2h → L1, then +4h → L2
    bw.tick_serotonin(0.2, hours=2)
    assert bw.emotional_blunting == 1
    bw.tick_serotonin(0.2, hours=4)
    assert bw.emotional_blunting == 2


def test_tick_serotonin_l3():
    bw = BodyWear()
    # Build up incrementally: 2h → L1, +4h → L2, +6h → L3
    bw.tick_serotonin(0.2, hours=2)
    bw.tick_serotonin(0.2, hours=4)
    bw.tick_serotonin(0.2, hours=6)
    assert bw.emotional_blunting == 3


def test_tick_serotonin_high_recovers():
    bw = BodyWear()
    bw.low_serotonin_accumulated = 5
    bw.emotional_blunting = 1
    bw.tick_serotonin(0.6, hours=3)
    # 5 - 3*2 = -1 → 0, emotional_blunting recovers: < 2h → -1 = 0
    assert bw.low_serotonin_accumulated == 0
    assert bw.emotional_blunting == 0


# ── on_belonging_satisfied ────────────────────────────────────────────

def test_on_belonging_satisfied():
    bw = BodyWear()
    bw.on_belonging_satisfied()
    assert bw.belonging_satisfaction_count == 1
    assert bw.oxytocin_gain_coefficient == 0.99  # 1.0 - 0.01


def test_on_belonging_satisfied_floor():
    bw = BodyWear()
    bw.belonging_satisfaction_count = 100
    bw.on_belonging_satisfied()
    # 1.0 - 101 * 0.01 = -0.01, floor at 0.2
    assert bw.oxytocin_gain_coefficient == 0.2


# ── tick_energy ───────────────────────────────────────────────────────

def test_tick_energy_low():
    bw = BodyWear()
    bw.tick_energy(0.2, hours=1)
    assert bw.energy_baseline == 0.02
    assert bw.energy_recovery_rate == 0.095  # 0.1 - 0.005


def test_tick_energy_high():
    bw = BodyWear()
    bw.energy_baseline = 0.2
    bw.energy_recovery_rate = 0.05
    bw.tick_energy(0.6, hours=24)
    assert bw.energy_baseline == pytest.approx(0.15)  # 0.2 - 0.05
    assert bw.energy_recovery_rate == pytest.approx(0.055)  # 0.05 + 0.005
