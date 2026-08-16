from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from xiaomei_brain.consciousness.config import ConsciousnessConfig
from xiaomei_brain.consciousness.core import Consciousness
from xiaomei_brain.consciousness.l3_engine import L3Engine
from xiaomei_brain.consciousness.state_buffer import StateChangeBuffer


def _engine(*, cooldown: float = 60.0) -> tuple[L3Engine, SimpleNamespace]:
    consciousness = SimpleNamespace(
        _cc=SimpleNamespace(l3_enabled=True, l3_cooldown=cooldown),
        _last_l3_time=0.0,
    )
    return L3Engine(consciousness), consciousness


def _append_change(buffer: StateChangeBuffer, **changes) -> None:
    buffer._changes.append({
        "cycle_id": len(buffer._changes) + 1,
        "timestamp": time.time(),
        "changes": changes,
    })


def test_l3_request_uses_one_cooldown_for_every_source(monkeypatch):
    engine, consciousness = _engine()
    report = SimpleNamespace(summary="done")
    monkeypatch.setattr(engine, "tick_l3", lambda: report)

    first = engine.request_reflection(source="scheduler")
    second = engine.request_reflection(source="intent")

    assert first.completed is True
    assert first.report is report
    assert second.status == "cooldown"
    assert consciousness._last_l3_time > 0


def test_l3_failure_is_recorded_as_an_attempt_without_immediate_retry(monkeypatch):
    engine, consciousness = _engine()

    def fail():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(engine, "tick_l3", fail)

    failed = engine.request_reflection(source="scheduler")
    retried = engine.request_reflection(source="intent")

    assert failed.status == "failed"
    assert failed.error == "provider unavailable"
    assert retried.status == "cooldown"
    assert consciousness._last_l3_time > 0


def test_l3_rejects_a_concurrent_second_request(monkeypatch):
    engine, _consciousness = _engine(cooldown=0.0)
    entered = threading.Event()
    release = threading.Event()
    first_result = []

    def run_slowly():
        entered.set()
        assert release.wait(timeout=2)
        return SimpleNamespace(summary="done")

    monkeypatch.setattr(engine, "tick_l3", run_slowly)
    thread = threading.Thread(
        target=lambda: first_result.append(
            engine.request_reflection(source="scheduler")
        )
    )
    thread.start()
    assert entered.wait(timeout=2)

    concurrent = engine.request_reflection(source="intent")
    release.set()
    thread.join(timeout=2)

    assert concurrent.status == "busy"
    assert concurrent.blocks_l4 is True
    assert first_result[0].completed is True


def test_state_buffer_ignores_time_only_changes_for_l3():
    buffer = StateChangeBuffer()
    for index in range(20):
        _append_change(buffer, time_elapsed=index + 1)

    assert buffer.meaningful_count() == 0
    assert buffer.should_trigger_l3(1) is False

    _append_change(buffer, time_elapsed=1, energy_change=-0.1)
    assert buffer.meaningful_count() == 1
    assert buffer.should_trigger_l3(1) is True


def test_l3_scheduler_uses_meaningful_changes_then_periodic_fallback():
    config = ConsciousnessConfig(
        l3_enabled=True,
        l3_cooldown=10.0,
        l3_interval=100.0,
        l3_changes_trigger=2,
    )
    consciousness = Consciousness(consciousness_config=config)
    consciousness._last_l3_time = time.time() - 20.0
    _append_change(consciousness._state_buffer, time_elapsed=1)

    assert consciousness._should_l3("awake") is False

    _append_change(consciousness._state_buffer, energy_change=-0.1)
    _append_change(consciousness._state_buffer, goal_change=0.2)
    assert consciousness._should_l3("awake") is True

    consciousness._state_buffer.clear()
    consciousness._last_l3_time = time.time() - 101.0
    assert consciousness._should_l3("awake") is True
