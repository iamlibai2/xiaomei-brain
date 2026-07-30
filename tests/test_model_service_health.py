import time

from xiaomei_brain.consciousness.layer2 import Layer2DefaultNetwork
from xiaomei_brain.llm.client import FatalLLMError
from xiaomei_brain.llm.service_health import ModelServiceHealth


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_model_service_health_opens_circuit_and_uses_backoff():
    clock = Clock()
    health = ModelServiceHealth(clock=clock)

    error = health.report_failure(402)

    assert health.available is False
    assert error["code"] == "MODEL_BALANCE_INSUFFICIENT"
    assert health.begin_probe() is False

    clock.now += 60
    assert health.begin_probe() is True
    assert health.begin_probe() is False

    health.finish_probe_failure()
    snapshot = health.snapshot()
    assert snapshot["failure_count"] == 2
    assert snapshot["next_probe_at"] == clock.now + 300


def test_model_service_health_recovers_and_clears_public_error():
    clock = Clock()
    health = ModelServiceHealth(clock=clock)
    health.report_failure(401)

    assert health.error()["code"] == "MODEL_AUTHENTICATION_FAILED"
    assert health.mark_available() is True
    assert health.available is True
    assert health.error() is None
    assert health.mark_available() is False


def test_model_configuration_change_can_reset_circuit_immediately():
    health = ModelServiceHealth()
    health.report_failure(402)

    assert health.mark_available() is True
    assert health.snapshot()["failure_count"] == 0


def test_layer2_pauses_without_exiting_when_model_becomes_unavailable():
    class Consciousness:
        _agent_state = "idle"
        _l2_triggered_by_anomaly = None
        _last_intent_time = 0.0

        @staticmethod
        def _should_intent(_state):
            return True

        @staticmethod
        def tick_L2_intent(_context):
            raise FatalLLMError("balance", status_code=402)

    health = ModelServiceHealth()
    layer2 = Layer2DefaultNetwork(
        Consciousness(),
        check_interval=0.01,
        model_available=lambda: health.available,
        model_failure_observer=lambda error: health.report_failure(
            error.status_code,
        ),
    )

    layer2.start()
    deadline = time.time() + 1.0
    while health.available and time.time() < deadline:
        time.sleep(0.01)

    assert health.available is False
    assert layer2._thread is not None
    assert layer2._thread.is_alive()
    layer2.stop()
