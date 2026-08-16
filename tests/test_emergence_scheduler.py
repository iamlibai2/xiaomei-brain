from __future__ import annotations

import time
from types import SimpleNamespace

from xiaomei_brain.consciousness.config import ConsciousnessConfig
from xiaomei_brain.consciousness.core import Consciousness
from xiaomei_brain.consciousness.state_buffer import StateChangeBuffer


def _consciousness(**overrides) -> Consciousness:
    config = ConsciousnessConfig(
        l2_emergence_cooldown=600.0,
        l2_emergence_interval=1800.0,
        l2_emergence_changes_trigger=2,
        **overrides,
    )
    drive = SimpleNamespace(
        energy=SimpleNamespace(level=0.8),
        desire=SimpleNamespace(
            belonging=0.0,
            cognition=0.0,
            achievement=0.0,
            expression=0.0,
        ),
    )
    return Consciousness(consciousness_config=config, drive=drive)


def _snapshot(age: float, *, energy: float = 0.8, memory: int = 0) -> dict:
    return {
        "consciousness_age": age,
        "agent_state": "awake",
        "user_idle_duration": age,
        "energy": energy,
        "window_size": memory,
        "goal_progress": 0.0,
    }


def test_time_passing_alone_does_not_trigger_emergence() -> None:
    buffer = StateChangeBuffer()
    for age in range(1, 10):
        buffer.tick(_snapshot(age - 1), _snapshot(age))

    assert len(buffer) == 9
    assert buffer.meaningful_count() == 0
    assert buffer.should_trigger_l2(2) is False


def test_meaningful_changes_trigger_emergence_after_cooldown() -> None:
    consciousness = _consciousness()
    consciousness._last_emerge_time = time.time() - 700.0
    consciousness._state_buffer.tick(
        _snapshot(0), _snapshot(1, energy=0.7)
    )
    consciousness._state_buffer.tick(
        _snapshot(1, energy=0.7), _snapshot(2, energy=0.6, memory=1)
    )

    assert consciousness._emergence_trigger_context("awake") == "state_changes"


def test_periodic_emergence_is_a_fallback() -> None:
    consciousness = _consciousness()
    consciousness._last_emerge_time = time.time() - 1900.0

    assert consciousness._emergence_trigger_context("idle") == "periodic"


def test_emergence_respects_enabled_energy_and_cooldown() -> None:
    disabled = _consciousness(l2_emergence_enabled=False)
    disabled._last_emerge_time = time.time() - 1900.0
    assert disabled._emergence_trigger_context("awake") is None

    low_energy = _consciousness(l2_emergence_energy_threshold=0.3)
    low_energy.drive.energy.level = 0.2
    low_energy._last_emerge_time = time.time() - 1900.0
    assert low_energy._emergence_trigger_context("awake") is None

    cooling_down = _consciousness()
    cooling_down._last_emerge_time = time.time() - 300.0
    assert cooling_down._emergence_trigger_context("awake") is None
