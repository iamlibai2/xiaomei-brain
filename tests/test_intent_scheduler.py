from __future__ import annotations

import time
from types import SimpleNamespace

from xiaomei_brain.consciousness.config import ConsciousnessConfig
from xiaomei_brain.consciousness.core import Consciousness


def _consciousness(**overrides) -> Consciousness:
    values = {
        "l2_cooldown": 300.0,
        "l2_periodic_interval": 1800.0,
        "l2_idle_trigger": 600.0,
        **overrides,
    }
    config = ConsciousnessConfig(**values)
    drive = SimpleNamespace(
        energy=SimpleNamespace(level=0.8),
        desire=SimpleNamespace(
            belonging=0.0,
            cognition=0.0,
            achievement=0.0,
            expression=0.0,
        ),
    )
    consciousness = Consciousness(consciousness_config=config, drive=drive)
    consciousness._last_intent_time = time.time() - 2000.0
    return consciousness


def test_intent_decision_can_be_disabled() -> None:
    consciousness = _consciousness(l2_intent_enabled=False)

    assert consciousness._intent_trigger_context("awake") is None


def test_awake_only_uses_periodic_intent_review() -> None:
    consciousness = _consciousness()
    consciousness.drive.desire.cognition = 1.0

    assert consciousness._intent_trigger_context("awake") == "periodic"


def test_idle_preserves_desire_reason_before_periodic_fallback() -> None:
    consciousness = _consciousness()
    consciousness.perception.user_idle_duration = 120.0
    consciousness.drive.desire.cognition = 0.8

    assert (
        consciousness._intent_trigger_context("idle")
        == "desire_starvation_cognition"
    )


def test_idle_goal_reason_is_preserved_before_periodic_fallback() -> None:
    consciousness = _consciousness()
    consciousness.perception.user_idle_duration = 120.0
    consciousness.purpose = SimpleNamespace(get_current=lambda: object())

    assert consciousness._intent_trigger_context("idle") == "goal_progress"


def test_low_energy_doubles_minimum_intent_interval() -> None:
    consciousness = _consciousness(l2_periodic_interval=60.0)
    consciousness._last_intent_time = time.time() - 400.0
    consciousness.drive.energy.level = 0.2

    assert consciousness._intent_trigger_context("awake") is None
    consciousness._last_intent_time = time.time() - 700.0
    assert consciousness._intent_trigger_context("awake") == "periodic"
