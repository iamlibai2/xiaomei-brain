from xiaomei_brain.memory.observability import (
    build_memory_references,
    list_person_memory_views,
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
