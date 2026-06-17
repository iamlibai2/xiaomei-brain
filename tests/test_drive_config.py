"""Tests for drive/config.py -- Drive configuration dataclasses."""

import pytest
from xiaomei_brain.drive.config import (
    DesireThresholds,
    DesireConfig,
    EmotionConfig,
    HormoneConfig,
    MotivationConfig,
    DriveConfig,
)


# ── DesireThresholds ──────────────────────────────────────────────────

def test_desire_thresholds_defaults():
    dt = DesireThresholds()
    assert dt.belonging == 0.7
    assert dt.cognition == 0.8
    assert dt.achievement == 0.6
    assert dt.expression == 0.5
    assert dt.survival_threatened == 0.3
    assert dt.survival_dying == 0.1
    assert dt.survival_dead == 0.0


# ── DesireConfig ──────────────────────────────────────────────────────

def test_desire_config_defaults():
    dc = DesireConfig()
    assert dc.survival == 0.3
    assert dc.achievement == 0.5
    assert dc.belonging == 0.5
    assert dc.cognition == 0.6
    assert dc.expression == 0.4
    assert dc.recovery_rate == 0.5
    assert isinstance(dc.thresholds, DesireThresholds)


# ── EmotionConfig ─────────────────────────────────────────────────────

def test_emotion_config_defaults():
    ec = EmotionConfig()
    assert ec.decay_rate == 0.95
    assert ec.min_intensity == 0.1
    assert ec.default_duration == 60.0
    assert ec.switch_inertia == 0.7


def test_emotion_config_durations():
    ec = EmotionConfig()
    assert ec.durations["joy"] == 600
    assert ec.durations["sadness"] == 1800
    assert ec.durations["fear"] == 300
    assert ec.durations["anger"] == 600


def test_get_duration_known():
    ec = EmotionConfig()
    assert ec.get_duration("joy") == 600
    assert ec.get_duration("sadness") == 1800


def test_get_duration_unknown():
    ec = EmotionConfig()
    assert ec.get_duration("surprise") == 60.0  # default_duration


# ── HormoneConfig ─────────────────────────────────────────────────────

def test_hormone_config_defaults():
    hc = HormoneConfig()
    assert hc.decay_rates["dopamine"] == 0.95
    assert hc.decay_rates["serotonin"] == 0.98
    assert hc.decay_rates["cortisol"] == 0.90
    assert hc.decay_rates["oxytocin"] == 0.95
    assert hc.defaults["dopamine"] == 0.5
    assert hc.defaults["cortisol"] == 0.3


# ── MotivationConfig ──────────────────────────────────────────────────

def test_motivation_config_defaults():
    mc = MotivationConfig()
    assert mc.rpe_coefficient == 0.5
    assert mc.expected_update_weight == 0.2


# ── DriveConfig ───────────────────────────────────────────────────────

def test_drive_config_defaults():
    dc = DriveConfig()
    assert isinstance(dc.desire, DesireConfig)
    assert isinstance(dc.emotion, EmotionConfig)
    assert isinstance(dc.hormone, HormoneConfig)
    assert isinstance(dc.motivation, MotivationConfig)
