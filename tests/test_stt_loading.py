from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

from xiaomei_brain.body.perception.stt import STT


def test_sensevoice_model_load_is_single_flight(monkeypatch) -> None:
    original_model = STT._model
    original_loaded = STT._loaded
    calls = 0
    calls_lock = threading.Lock()

    def fake_auto_model(**_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return object()

    monkeypatch.setitem(
        sys.modules,
        "funasr",
        SimpleNamespace(AutoModel=fake_auto_model),
    )
    STT._model = None
    STT._loaded = False

    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def load() -> None:
        try:
            barrier.wait()
            STT()._ensure_model()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=load) for _ in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        assert not errors
        assert all(not thread.is_alive() for thread in threads)
        assert calls == 1
        assert STT._loaded is True
        assert STT._model is not None
    finally:
        STT._model = original_model
        STT._loaded = original_loaded
