from xiaomei_brain.memory.observability import (
    build_memory_references,
    list_person_memory_views,
    list_person_short_term_memory_views,
)


def test_memory_reference_projection_is_bounded_and_safe() -> None:
    references = build_memory_references([
        {
            "id": 7,
            "content": "  李白希望先完善独立 Agent。  ",
            "source": "immediate",
            "type": "common",
            "tags": ["产品方向", "desktop"],
            "created_at": 123.5,
            "score": 0.98,
            "effective_strength": 0.9,
            "embedding": [1.0, 2.0],
            "raw_stream": "private",
        },
    ])

    assert references == [{
        "id": "7",
        "summary": "李白希望先完善独立 Agent。",
        "source": "immediate",
        "memory_type": "common",
        "tags": ["产品方向", "desktop"],
        "created_at": 123.5,
    }]


def test_person_memory_projection_is_bounded_and_omits_internal_fields() -> None:
    class FakeMemory:
        def list_person_memories(self, person_id, *, limit, offset):
            assert person_id == "person-1"
            assert (limit, offset) == (2, 3)
            return [
                {
                    "id": 8,
                    "content": "  一条可以展示的长期记忆。 ",
                    "source": "periodic",
                    "type": "common",
                    "tags": ["关系"] * 10,
                    "created_at": 10,
                    "last_accessed": 12,
                    "embedding": [1.0],
                    "user_id": "person-1",
                },
                {
                    "id": 9,
                    "content": "下一条只用于判断是否还有更多。",
                },
            ]

    memories, has_more = list_person_memory_views(
        FakeMemory(),
        "person-1",
        limit=1,
        offset=3,
    )

    assert memories == [{
        "id": "8",
        "summary": "一条可以展示的长期记忆。",
        "source": "periodic",
        "memory_type": "common",
        "tags": ["关系"] * 8,
        "created_at": 10.0,
        "last_accessed": 12.0,
    }]
    assert has_more is True


def test_short_term_projection_exposes_review_source_and_update_time() -> None:
    class FakeShortTermMemory:
        def list_for_person(self, person_id, *, limit):
            assert person_id == "person-1"
            assert limit == 5
            return [{
                "id": 4,
                "content": "The person prefers concise status updates.",
                "kind": "preference_signal",
                "formation_source": "turn_batch_review",
                "created_at": 10,
                "last_seen_at": 20,
                "expires_at": 30,
                "reinforcement_count": 2,
            }]

    memories = list_person_short_term_memory_views(
        FakeShortTermMemory(),
        "person-1",
        limit=5,
    )

    assert memories == [{
        "id": "m0:4",
        "summary": "The person prefers concise status updates.",
        "source": "turn_batch_review",
        "memory_type": "preference_signal",
        "tags": [],
        "created_at": 10.0,
        "last_accessed": 20.0,
        "expires_at": 30.0,
        "reinforcement_count": 2,
        "memory_layer": "short_term",
    }]


def test_person_memory_projection_hides_incomplete_fragments() -> None:
    class FakeMemory:
        def list_person_memories(self, person_id, *, limit, offset):
            return [{
                "id": 1,
                "content": "博士让我",
                "source": "immediate",
                "created_at": 10,
                "last_accessed": 20,
            }]

    memories, has_more = list_person_memory_views(
        FakeMemory(),
        "person-1",
        limit=10,
    )

    assert memories == []
    assert has_more is False
