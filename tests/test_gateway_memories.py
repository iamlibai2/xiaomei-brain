from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.base.sqlite_store import SQLiteStore
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.people import IdentityContext


def _identity(person_id: str, conn_id: str) -> IdentityContext:
    return IdentityContext(
        person_id=person_id,
        issuer="test",
        subject=person_id,
        authentication_method="test",
        assurance="verified",
        authenticated_at=1.0,
        connection_id=conn_id,
    )


def _memory(tmp_path) -> LongTermMemory:
    # The list RPC only needs SQLite metadata. Avoid constructing the
    # embedding backend in this focused observation test.
    memory = object.__new__(LongTermMemory)
    SQLiteStore.__init__(memory, tmp_path / "brain.db")
    memory._init_tables()
    return memory


def _insert(
    memory: LongTermMemory,
    *,
    person_id: str,
    content: str,
    source: str = "immediate",
    memory_type: str = "common",
    status: str = "active",
    created_at: float = 1.0,
    last_accessed: float = 0.0,
    tags: tuple[str, ...] = (),
) -> int:
    cursor = memory._get_conn().execute(
        """INSERT INTO memories
           (user_id, content, source, created_at, last_accessed, status, type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            person_id,
            content,
            source,
            created_at,
            last_accessed,
            status,
            memory_type,
        ),
    )
    memory_id = int(cursor.lastrowid)
    memory._get_conn().executemany(
        "INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)",
        [(memory_id, tag) for tag in tags],
    )
    memory._get_conn().commit()
    return memory_id


def _router(memory: LongTermMemory) -> MethodRouter:
    living = SimpleNamespace(agent=SimpleNamespace(longterm_memory=memory))
    router = MethodRouter(living=living)
    router._auth_sessions.update({"conn-1", "conn-2"})
    router._identity_contexts.update({
        "conn-1": _identity("person-1", "conn-1"),
        "conn-2": _identity("person-2", "conn-2"),
    })
    return router


def test_memory_list_only_exposes_current_person_ordinary_memories(tmp_path):
    memory = _memory(tmp_path)
    own_old = _insert(
        memory,
        person_id="person-1",
        content="喜欢简洁的交互。",
        created_at=10,
        last_accessed=1000,
        tags=("偏好",),
    )
    own_recent = _insert(
        memory,
        person_id="person-1",
        content="当前优先完善 Desktop。",
        source="every_turn",
        created_at=20,
        last_accessed=40,
    )
    _insert(memory, person_id="person-2", content="另一个人的记忆。", created_at=50)
    _insert(memory, person_id="global", content="全局知识。", created_at=60)
    _insert(memory, person_id="person-1", content="梦境。", source="dream", created_at=70)
    _insert(memory, person_id="person-1", content="内在叙事。", source="internal", created_at=80)
    _insert(
        memory,
        person_id="person-1",
        content="经验记忆。",
        memory_type="experience",
        created_at=90,
    )
    _insert(
        memory,
        person_id="person-1",
        content="已淡忘。",
        status="extinct",
        created_at=100,
    )
    router = _router(memory)

    # A client-supplied identity must never change the server-derived Person.
    response = router.dispatch(
        "conn-1",
        "list",
        "memory.list",
        {"person_id": "person-2", "limit": 20},
    )

    assert response["result"]["has_more"] is False
    assert [item["id"] for item in response["result"]["memories"]] == [
        str(own_recent),
        str(own_old),
    ]
    assert response["result"]["memories"][1]["tags"] == ["偏好"]
    assert response["result"]["memories"][1]["last_accessed"] == 1000
    assert all("user_id" not in item for item in response["result"]["memories"])
    assert "memory.read" in router._capabilities()
    memory.close()


def test_memory_list_paginates_and_requires_verified_identity(tmp_path):
    memory = _memory(tmp_path)
    for index in range(3):
        _insert(
            memory,
            person_id="person-1",
            content=f"这是一条记忆 {index}",
            created_at=float(index + 1),
        )
    router = _router(memory)

    first = router.dispatch(
        "conn-1",
        "first",
        "memory.list",
        {"limit": 2, "offset": 0},
    )
    second = router.dispatch(
        "conn-1",
        "second",
        "memory.list",
        {"limit": 2, "offset": first["result"]["next_offset"]},
    )
    assert [item["summary"] for item in first["result"]["memories"]] == [
        "这是一条记忆 2",
        "这是一条记忆 1",
    ]
    assert first["result"]["has_more"] is True
    assert first["result"]["next_offset"] == 2
    assert [item["summary"] for item in second["result"]["memories"]] == ["这是一条记忆 0"]
    assert second["result"]["has_more"] is False
    assert second["result"]["next_offset"] is None

    router._auth_sessions.add("conn-without-person")
    unauthorized = router.dispatch(
        "conn-without-person",
        "missing",
        "memory.list",
        {},
    )
    assert unauthorized["error"]["code"] == -32001
    memory.close()
