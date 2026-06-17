"""Tests for drive/state.py -- EmotionalState, hormone, motivation, desire, energy, DriveSignals."""

import pytest
from xiaomei_brain.drive.state import (
    EmotionType,
    EmotionalState,
    HormoneState,
    MotivationState,
    DesireState,
    EnergyState,
    DriveSignals,
)


# ── EmotionType enum ──────────────────────────────────────────────────

def test_emotion_type_values():
    assert EmotionType.JOY.value == "joy"
    assert EmotionType.SADNESS.value == "sadness"
    assert EmotionType.ANGER.value == "anger"
    assert EmotionType.FEAR.value == "fear"
    assert EmotionType.SURPRISE.value == "surprise"
    assert EmotionType.DISGUST.value == "disgust"
    assert EmotionType.NEUTRAL.value == "neutral"


# ── EmotionalState — constructor ──────────────────────────────────────

def test_emotional_state_empty():
    es = EmotionalState()
    assert es.is_empty() is True
    assert es.emotions == {}


def test_emotional_state_legacy_constructor():
    es = EmotionalState(type=EmotionType.JOY, intensity=0.5)
    assert es.emotions == {"joy": 0.5}


def test_emotional_state_legacy_neutral():
    es = EmotionalState(type=EmotionType.NEUTRAL, intensity=0.5)
    assert es.emotions == {}


def test_emotional_state_composite_constructor():
    es = EmotionalState(emotions={"joy": 0.5, "fear": 0.3})
    assert es.emotions == {"joy": 0.5, "fear": 0.3}


# ── EmotionalState — backward compat properties ───────────────────────

def test_emotional_state_type_property():
    es = EmotionalState(emotions={"joy": 0.5, "fear": 0.3})
    assert es.type == EmotionType.JOY


def test_emotional_state_type_property_empty():
    es = EmotionalState()
    assert es.type == EmotionType.NEUTRAL


def test_emotional_state_type_setter():
    es = EmotionalState()
    es.type = EmotionType.SADNESS
    assert es.emotions == {"sadness": 0.1}


def test_emotional_state_type_setter_neutral():
    es = EmotionalState(emotions={"joy": 0.5})
    es.type = EmotionType.NEUTRAL
    assert es.emotions == {}


def test_emotional_state_intensity_property():
    es = EmotionalState(emotions={"joy": 0.5, "fear": 0.8})
    assert es.intensity == 0.8


def test_emotional_state_intensity_empty():
    es = EmotionalState()
    assert es.intensity == 0.0


# ── EmotionalState — add_emotion ──────────────────────────────────────

def test_add_emotion_new():
    es = EmotionalState()
    es.add_emotion("joy", 0.5)
    assert es.emotions["joy"] == 0.5


def test_add_emotion_takes_max():
    es = EmotionalState(emotions={"joy": 0.5})
    es.add_emotion("joy", 0.3)
    assert es.emotions["joy"] == 0.5  # max
    es.add_emotion("joy", 0.7)
    assert es.emotions["joy"] == 0.7


def test_add_emotion_below_threshold():
    es = EmotionalState()
    es.add_emotion("joy", 0.04)
    assert "joy" not in es.emotions


def test_add_emotion_clamped():
    es = EmotionalState()
    es.add_emotion("joy", 1.5)
    assert es.emotions["joy"] == 1.0


# ── EmotionalState — decay ────────────────────────────────────────────

def test_decay_all():
    es = EmotionalState(emotions={"joy": 1.0, "fear": 0.5})
    es.decay_all(0.5)
    assert es.emotions["joy"] == 0.5
    assert es.emotions["fear"] == 0.25


def test_decay_all_removes_below_threshold():
    es = EmotionalState(emotions={"joy": 0.1})
    es.decay_all(0.5)
    assert es.is_empty()  # 0.1 * 0.5 = 0.05 < 0.08


def test_decay_all_empty():
    es = EmotionalState()
    es.decay_all(0.5)  # should not raise


# ── EmotionalState — dominant / top ───────────────────────────────────

def test_dominant():
    es = EmotionalState(emotions={"joy": 0.5, "fear": 0.8})
    assert es.dominant() == ("fear", 0.8)


def test_dominant_empty():
    es = EmotionalState()
    assert es.dominant() == ("neutral", 0.0)


def test_top_emotions():
    es = EmotionalState(emotions={"joy": 0.5, "fear": 0.8, "anger": 0.3})
    top = es.top_emotions(2)
    assert top == [("fear", 0.8), ("joy", 0.5)]


# ── EmotionalState — serialization ────────────────────────────────────

def test_emotional_state_to_dict():
    es = EmotionalState(emotions={"joy": 0.5})
    d = es.to_dict()
    assert d["emotions"] == {"joy": 0.5}


def test_emotional_state_from_dict_composite():
    es = EmotionalState()
    es.from_dict({"emotions": {"joy": 0.7, "fear": 0.3}})
    assert es.emotions == {"joy": 0.7, "fear": 0.3}


def test_emotional_state_from_dict_legacy():
    es = EmotionalState()
    es.from_dict({"type": "joy", "intensity": 0.6})
    assert es.emotions == {"joy": 0.6}


def test_emotional_state_from_dict_legacy_neutral():
    es = EmotionalState()
    es.from_dict({"type": "neutral", "intensity": 0.0})
    assert es.emotions == {}


# ── HormoneState ──────────────────────────────────────────────────────

def test_hormone_state_defaults():
    h = HormoneState()
    assert h.dopamine == 0.5
    assert h.serotonin == 0.5
    assert h.cortisol == 0.3
    assert h.oxytocin == 0.5
    assert h.norepinephrine == 0.5
    assert h.melatonin == 0.5


def test_hormone_state_to_from_dict():
    h = HormoneState(dopamine=0.8, cortisol=0.2)
    d = h.to_dict()
    h2 = HormoneState()
    h2.from_dict(d)
    assert h2.dopamine == 0.8
    assert h2.cortisol == 0.2


# ── MotivationState ───────────────────────────────────────────────────

def test_motivation_state_defaults():
    m = MotivationState()
    assert m.expected_reward == 0.5
    assert m.motivation_level == 0.5


def test_motivation_state_to_from_dict():
    m = MotivationState(expected_reward=0.7)
    d = m.to_dict()
    m2 = MotivationState()
    m2.from_dict(d)
    assert m2.expected_reward == 0.7


# ── DesireState ───────────────────────────────────────────────────────

def test_desire_state_defaults():
    d = DesireState()
    assert d.survival == 0.3
    assert d.achievement == 0.5
    assert d.belonging == 0.5
    assert d.cognition == 0.6
    assert d.expression == 0.4


def test_desire_state_to_from_dict():
    d = DesireState(survival=0.1, cognition=0.9)
    data = d.to_dict()
    d2 = DesireState()
    d2.from_dict(data)
    assert d2.survival == 0.1
    assert d2.cognition == 0.9


# ── EnergyState ───────────────────────────────────────────────────────

def test_energy_state_defaults():
    e = EnergyState()
    assert e.level == 0.8


def test_energy_state_update_from_hormones():
    e = EnergyState()
    # dopamine=0.5, serotonin=0.5, cortisol=0.3, norepinephrine=0.5
    # raw = 0.5*0.3 + 0.5*0.25 - 0.3*0.35 + 0.5*0.1
    #     = 0.15 + 0.125 - 0.105 + 0.05 = 0.22
    e.update_from_hormones(0.5, 0.5, 0.3, 0.5)
    assert e.level == pytest.approx(0.22, abs=0.01)


def test_energy_state_update_clamped_low():
    e = EnergyState()
    e.update_from_hormones(0, 0, 1.0, 0)  # very negative
    assert e.level == 0.1  # floor


def test_energy_state_update_clamped_high():
    e = EnergyState()
    # Formula: dopamine*0.3 + serotonin*0.25 - cortisol*0.35 + norepinephrine*0.1
    # 1.0*0.3 + 1.0*0.25 - 0*0.35 + 1.0*0.1 = 0.3 + 0.25 + 0.1 = 0.65
    e.update_from_hormones(1.0, 1.0, 0, 1.0)
    assert e.level == 0.65  # 0.65 < 0.95, not hitting ceiling


# ── DriveSignals ──────────────────────────────────────────────────────

def test_drive_signals_defaults():
    ds = DriveSignals()
    assert ds.stress_level == 0.0
    assert ds.satisfaction_level == 0.0
    assert ds.emotion.is_empty()


def test_drive_signals_compute_derived():
    h = HormoneState(cortisol=0.7, serotonin=0.3)
    ds = DriveSignals(hormone=h)
    ds.compute_derived()
    assert ds.stress_level == 0.7
    assert ds.satisfaction_level == 0.3
