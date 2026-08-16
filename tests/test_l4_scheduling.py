from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from xiaomei_brain.consciousness.associative_chain import AssociativeChain
from xiaomei_brain.consciousness.config import ConsciousnessConfig
from xiaomei_brain.consciousness.core import Consciousness
from xiaomei_brain.consciousness.l4_engine import L4Engine, L4Report


def _engine(*, cooldown: float = 60.0) -> tuple[L4Engine, SimpleNamespace]:
    consciousness = SimpleNamespace(
        _cc=SimpleNamespace(l4_enabled=True, l4_cooldown=cooldown),
        _last_l4_time=0.0,
    )
    return L4Engine(consciousness), consciousness


def test_l4_request_uses_one_cooldown_for_every_source(monkeypatch):
    engine, consciousness = _engine()
    report = L4Report(pattern_insight="看见了一个模式")
    monkeypatch.setattr(engine, "run", lambda: report)

    first = engine.request_association(source="scheduler")
    second = engine.request_association(source="manual")

    assert first.completed is True
    assert first.report is report
    assert second.status == "cooldown"
    assert consciousness._last_l4_time > 0


def test_l4_failure_and_empty_result_do_not_immediately_retry(monkeypatch):
    engine, _consciousness = _engine()

    def fail():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(engine, "run", fail)
    failed = engine.request_association(source="scheduler")
    retried = engine.request_association(source="manual")

    assert failed.status == "failed"
    assert failed.error == "provider unavailable"
    assert retried.status == "cooldown"

    skipped_engine, _ = _engine()
    monkeypatch.setattr(
        skipped_engine,
        "run",
        lambda: L4Report(skipped=True, reason="empty_examination"),
    )
    skipped = skipped_engine.request_association(source="scheduler")
    assert skipped.status == "skipped"
    assert skipped.report.reason == "empty_examination"
    assert skipped_engine.request_association(source="manual").status == "cooldown"


def test_l4_rejects_a_concurrent_second_request(monkeypatch):
    engine, _consciousness = _engine(cooldown=0.0)
    entered = threading.Event()
    release = threading.Event()
    first_result = []

    def run_slowly():
        entered.set()
        assert release.wait(timeout=2)
        return L4Report(pattern_insight="done")

    monkeypatch.setattr(engine, "run", run_slowly)
    thread = threading.Thread(
        target=lambda: first_result.append(
            engine.request_association(source="scheduler")
        )
    )
    thread.start()
    assert entered.wait(timeout=2)

    concurrent = engine.request_association(source="manual")
    release.set()
    thread.join(timeout=2)

    assert concurrent.status == "busy"
    assert first_result[0].completed is True


def test_l4_scheduler_only_runs_while_idle():
    config = ConsciousnessConfig(
        l4_enabled=True,
        l4_cooldown=10.0,
        l4_timeout=100.0,
    )
    consciousness = Consciousness(consciousness_config=config)
    consciousness._last_l4_time = time.time() - 101.0

    assert consciousness._should_l4("awake") is False
    assert consciousness._should_l4("working") is False
    assert consciousness._should_l4("idle") is True

    consciousness._cc.l4_enabled = False
    assert consciousness._should_l4("idle") is False


def test_l4_uses_global_memory_scope_and_self_image_contribution(monkeypatch):
    narratives_calls = []
    stored_calls = []

    class Memory:
        def get_narratives(self, **kwargs):
            narratives_calls.append(kwargs)
            return [{"content": "一段属于我自己的独白", "trigger": "L2"}]

        def store_narrative(self, **kwargs):
            stored_calls.append(kwargs)

    self_image = SimpleNamespace(
        body=SimpleNamespace(energy=0.8),
        perception=SimpleNamespace(user_idle_duration=100),
        contributed=[],
    )
    self_image.contribute_deep_pattern = self_image.contributed.append
    consciousness = SimpleNamespace(
        drive=None,
        _cc=SimpleNamespace(
            l4_desire_threshold=0.7,
            l4_cortisol_threshold=0.6,
        ),
        agent=SimpleNamespace(longterm_memory=Memory(), exp_stream=None),
        self_image=self_image,
        body=self_image.body,
        perception=self_image.perception,
    )
    engine = L4Engine(consciousness)

    assert engine._generate_seed() == "一段属于我自己的独白"
    engine._integrate("我总会从相同的张力出发。")
    chain = SimpleNamespace(hops=[], total_hops=0)
    engine._store("种子", "审视", chain)

    assert narratives_calls == [{"limit": 3, "user_id": "global"}]
    assert self_image.contributed == ["我总会从相同的张力出发。"]
    assert stored_calls[0]["user_id"] == "global"


def test_associative_chain_deduplicates_stream_id_field():
    class Memory:
        def search_consciousness_stream(self, **_kwargs):
            return [{"id": 7, "content": "same"}, {"id": 8, "content": "new"}]

    chain = AssociativeChain(ltm=Memory(), llm=SimpleNamespace())
    assert chain._search_thoughts("query", "global", {7}) == [
        {"id": 8, "content": "new"}
    ]
