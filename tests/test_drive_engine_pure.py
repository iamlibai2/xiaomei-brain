"""Tests for drive/engine.py -- DriveEngine static and pure methods (load=False)."""

import math
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from xiaomei_brain.drive.engine import DriveEngine
from xiaomei_brain.drive.config import DriveConfig


# ── Helpers ───────────────────────────────────────────────────────────

def _make_engine(**kwargs) -> DriveEngine:
    """Create a DriveEngine with load=False (no I/O)."""
    return DriveEngine(agent_id="test", load=False, config=DriveConfig(), **kwargs)


# ── _calc_token_pressure (static) ─────────────────────────────────────

def test_calc_token_pressure_zero_budget():
    """Zero budget means no limit → always 1.0."""
    assert DriveEngine._calc_token_pressure(1000, 0) == 1.0
    assert DriveEngine._calc_token_pressure(0, 0) == 1.0


def test_calc_token_pressure_no_usage():
    """0 usage → 1.0 (below 50%)."""
    assert DriveEngine._calc_token_pressure(0, 1000) == 1.0


def test_calc_token_pressure_at_half():
    """At 50% → 1.0 (threshold, no extra pressure)."""
    assert DriveEngine._calc_token_pressure(500, 1000) == 1.0


def test_calc_token_pressure_at_75_percent():
    """At 75% → 1.0 + (0.75-0.5)*2 = 1.5."""
    assert DriveEngine._calc_token_pressure(750, 1000) == 1.5


def test_calc_token_pressure_at_full():
    """At 100% → 1.0 + (1.0-0.5)*2 = 2.0."""
    assert DriveEngine._calc_token_pressure(1000, 1000) == 2.0


def test_calc_token_pressure_over_budget():
    """Over 100% → pressure > 2.0."""
    pressure = DriveEngine._calc_token_pressure(1500, 1000)
    assert pressure > 2.0


def test_calc_token_pressure_below_half():
    """Below 50% → 1.0 (no pressure)."""
    assert DriveEngine._calc_token_pressure(300, 1000) == 1.0


# ── token_pressure property ───────────────────────────────────────────

def test_token_pressure_uses_max_of_daily_monthly():
    eng = _make_engine()
    eng.token_budget_daily = 1000
    eng.token_budget_monthly = 10000
    eng.token_usage_today = 900  # 90% → 1.8
    eng.token_usage_month = 1000  # 10% → 1.0
    # max(1.8, 1.0) = 1.8
    assert eng.token_pressure == 1.8


# ── get_survival_state ────────────────────────────────────────────────

def test_get_survival_state_normal():
    eng = _make_engine()
    eng.desire.survival = 0.5
    assert eng.get_survival_state() == "normal"


def test_get_survival_state_threatened():
    eng = _make_engine()
    # threshold survival_threatened default is typically ~0.3
    # Set survival just below threatened threshold
    t = eng.config.desire.thresholds
    eng.desire.survival = t.survival_threatened
    # At exactly the threshold: <= means threatened
    assert eng.get_survival_state() == "threatened"


def test_get_survival_state_dying():
    eng = _make_engine()
    t = eng.config.desire.thresholds
    eng.desire.survival = t.survival_dying
    assert eng.get_survival_state() == "dying"


def test_get_survival_state_dead():
    eng = _make_engine()
    t = eng.config.desire.thresholds
    eng.desire.survival = t.survival_dead
    assert eng.get_survival_state() == "dead"


def test_get_survival_state_below_dead():
    eng = _make_engine()
    eng.desire.survival = 0.0
    assert eng.get_survival_state() == "dead"


# ── is_dead / revive ──────────────────────────────────────────────────

def test_is_dead_true():
    eng = _make_engine()
    eng.desire.survival = 0.0
    assert eng.is_dead() is True


def test_is_dead_false():
    eng = _make_engine()
    eng.desire.survival = 0.5
    assert eng.is_dead() is False


def test_revive():
    eng = _make_engine()
    eng.desire.survival = 0.0
    eng.energy.level = 0.0
    eng.hormone.dopamine = 0.0
    eng.hormone.serotonin = 0.0
    eng.revive()
    assert eng.desire.survival == 0.4
    assert eng.energy.level == 0.5
    assert eng.hormone.dopamine == 0.3  # max(0.0, 0.3) = 0.3
    assert eng.hormone.serotonin == 0.4  # max(0.0, 0.4) = 0.4


def test_revive_does_not_lower_existing():
    """revive uses max() so it doesn't lower already-high values."""
    eng = _make_engine()
    eng.desire.survival = 0.0
    eng.energy.level = 0.0
    eng.hormone.dopamine = 0.8
    eng.hormone.serotonin = 0.9
    eng.revive()
    assert eng.hormone.dopamine == 0.8  # max(0.8, 0.3) = 0.8
    assert eng.hormone.serotonin == 0.9  # max(0.9, 0.4) = 0.9


# ── _update_melatonin ─────────────────────────────────────────────────

def test_update_melatonin_midnight():
    """At 2 AM (peak): cos(0) = 1 → 0.5 + 0.4*1 = 0.9."""
    eng = _make_engine()
    mock_dt = MagicMock()
    mock_dt.hour = 2
    mock_dt.minute = 0
    with patch("xiaomei_brain.drive.engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        eng._update_melatonin()
    assert eng.hormone.melatonin == pytest.approx(0.9, abs=0.01)


def test_update_melatonin_noon():
    """At 2 PM (trough): cos(pi) = -1 → 0.5 + 0.4*(-1) = 0.1."""
    eng = _make_engine()
    mock_dt = MagicMock()
    mock_dt.hour = 14
    mock_dt.minute = 0
    with patch("xiaomei_brain.drive.engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        eng._update_melatonin()
    assert eng.hormone.melatonin == pytest.approx(0.1, abs=0.01)


def test_update_melatonin_8am():
    """At 8 AM: cos((8-2)*pi/12) = cos(pi/2) = 0 → 0.5."""
    eng = _make_engine()
    mock_dt = MagicMock()
    mock_dt.hour = 8
    mock_dt.minute = 0
    with patch("xiaomei_brain.drive.engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        eng._update_melatonin()
    assert eng.hormone.melatonin == pytest.approx(0.5, abs=0.01)


def test_update_melatonin_8pm():
    """At 8 PM: cos((20-2)*pi/12) = cos(3*pi/2) = 0 → 0.5."""
    eng = _make_engine()
    mock_dt = MagicMock()
    mock_dt.hour = 20
    mock_dt.minute = 0
    with patch("xiaomei_brain.drive.engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        eng._update_melatonin()
    assert eng.hormone.melatonin == pytest.approx(0.5, abs=0.01)


def test_update_melatonin_with_minutes():
    """2:30 AM: cos((2.5-2)*pi/12) = cos(pi/24)."""
    eng = _make_engine()
    mock_dt = MagicMock()
    mock_dt.hour = 2
    mock_dt.minute = 30
    with patch("xiaomei_brain.drive.engine.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_dt
        eng._update_melatonin()
    hour = 2.5
    expected = 0.5 + 0.4 * math.cos((hour - 2) * math.pi / 12)
    assert eng.hormone.melatonin == pytest.approx(expected, abs=0.01)


# ── token_pressure with both budgets ──────────────────────────────────

def test_token_pressure_zero_budgets():
    """Both budgets 0 → no pressure."""
    eng = _make_engine()
    eng.token_budget_daily = 0
    eng.token_budget_monthly = 0
    assert eng.token_pressure == 1.0


def test_token_pressure_only_daily():
    eng = _make_engine()
    eng.token_budget_daily = 1000
    eng.token_budget_monthly = 0
    eng.token_usage_today = 800  # 80% → 1.6
    assert eng.token_pressure == 1.6


# ── is_energy_critical ────────────────────────────────────────────────

def test_is_energy_critical_true():
    eng = _make_engine()
    eng.energy.level = 0.1
    assert eng.is_energy_critical is True


def test_is_energy_critical_false():
    eng = _make_engine()
    eng.energy.level = 0.5
    assert eng.is_energy_critical is False
