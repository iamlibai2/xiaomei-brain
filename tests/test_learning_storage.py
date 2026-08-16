from __future__ import annotations

from xiaomei_brain.learn.storage import KnowledgeStorage


class _ExactTagMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def recall(self, *_args, **_kwargs):
        raise AssertionError("learning cooldown must not use semantic recall")

    def search_by_tags(self, tags: list[str], *, user_id: str):
        self.calls.append((tags, user_id))
        return [
            {"created_at": 10.0, "tags": ["topic:alpha", "knowledge"]},
            {"created_at": 30.0, "tags": ["topic:alpha", "knowledge"]},
            {"created_at": 20.0, "tags": ["topic:beta", "knowledge"]},
        ]


def test_learning_times_are_loaded_by_exact_tags_in_one_query() -> None:
    memory = _ExactTagMemory()
    storage = KnowledgeStorage.__new__(KnowledgeStorage)
    storage._ltm = memory

    result = storage.get_last_learned_times(["alpha", "beta", "missing", "alpha"])

    assert result == {"alpha": 30.0, "beta": 20.0, "missing": 0.0}
    assert memory.calls == [
        (["topic:alpha", "topic:beta", "topic:missing"], "global"),
    ]


def test_single_learning_time_uses_the_exact_tag_path() -> None:
    memory = _ExactTagMemory()
    storage = KnowledgeStorage.__new__(KnowledgeStorage)
    storage._ltm = memory

    assert storage.get_last_learned_time("alpha") == 30.0
    assert memory.calls == [(["topic:alpha"], "global")]
