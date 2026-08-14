from __future__ import annotations

import threading

from xiaomei_brain.base.persistent_vector_index import PersistentVectorIndex
from xiaomei_brain.base.shared_embedder import SharedEmbedder
from xiaomei_brain.capabilities.registry import CapabilityRegistry
from xiaomei_brain.memory.procedure import ProcedureMatcher, ProcedureStore


class _FakeEmbedder:
    dim = 3

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed_batch(self, texts, *, source="unknown"):
        values = list(texts)
        self.batches.append(values)
        return [self.vector(text) for text in values]

    @staticmethod
    def vector(text: str) -> list[float]:
        length = float(len(text))
        return [length, length / 2, 1.0]


def test_persistent_index_reuses_and_incrementally_updates_vectors(tmp_path, monkeypatch):
    fake = _FakeEmbedder()
    monkeypatch.setattr(
        SharedEmbedder,
        "get_or_create",
        classmethod(lambda cls, model_name="": fake),
    )

    first = PersistentVectorIndex(tmp_path, "test_vectors", "test.index")
    vectors = first.sync([("a", "alpha"), ("b", "beta")])
    assert set(vectors) == {"a", "b"}
    assert fake.batches == [["alpha", "beta"]]

    # A new object simulates an Agent restart. Unchanged content must come
    # entirely from LanceDB without another embedding call.
    restarted = PersistentVectorIndex(tmp_path, "test_vectors", "test.index")
    vectors = restarted.sync([("a", "alpha"), ("b", "beta")])
    assert set(vectors) == {"a", "b"}
    assert fake.batches == [["alpha", "beta"]]

    restarted.sync([("a", "alpha changed"), ("b", "beta")])
    assert fake.batches[-1] == ["alpha changed"]

    restarted.sync([("a", "alpha changed")])
    assert len(fake.batches) == 2


class _FakeVectorIndex:
    def __init__(self) -> None:
        self.sync_calls = 0

    def sync(self, items):
        self.sync_calls += 1
        return {
            item_id: [1.0, 0.0]
            for item_id, _ in items
        }


def test_procedure_match_only_embeds_query_after_index_build(tmp_path):
    store = ProcedureStore(str(tmp_path / "brain.db"))
    store._init_table()
    store.store({
        "id": "PROC-1",
        "name": "Create quotation",
        "description": "Prepare and deliver a quotation",
        "steps": [],
    })
    index = _FakeVectorIndex()
    matcher = ProcedureMatcher(store, index)
    assert matcher.build_index() == 1

    embedded: list[str] = []

    def embed_query(text: str):
        embedded.append(text)
        return [1.0, 0.0]

    matched = matcher.match("create a quotation", embed_fn=embed_query, threshold=0.5)
    assert [item["id"] for item in matched] == ["PROC-1"]
    assert embedded == ["create a quotation"]
    assert index.sync_calls == 1


def test_capability_discovery_does_not_wait_for_initial_background_index(tmp_path):
    registry = CapabilityRegistry(
        plugin_registry=object(),
        definitions=[],
        vector_index_path=tmp_path,
    )
    started = threading.Event()
    release = threading.Event()

    def slow_build():
        started.set()
        release.wait(timeout=2)

    registry._build_discovery_index_background = slow_build
    try:
        assert registry.discover("hi") == []
        assert started.wait(timeout=1)
    finally:
        release.set()
