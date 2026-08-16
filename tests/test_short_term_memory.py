from __future__ import annotations

import sqlite3
import time
from unittest.mock import MagicMock

from xiaomei_brain.memory.formation import MemoryFormationService
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.short_term import (
    ShortTermMemoryCandidate,
    ShortTermMemoryStore,
)


def test_short_term_vectors_are_cached_on_write_and_reused_for_search(tmp_path):
    store = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    calls: list[tuple[list[str], str]] = []

    def embed(texts, *, source=""):
        calls.append((list(texts), source))
        return [[1.0, float(len(text))] for text in texts]

    memory_id = store.remember(
        ShortTermMemoryCandidate(
            content="博士喜欢成都的雨天",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
        ),
        embedder=embed,
    )

    assert calls == [(["博士喜欢成都的雨天"], "memory.short_term.write")]
    calls.clear()
    store.find_similar(
        "成都",
        scope_type="person",
        scope_id="person-a",
        embedder=embed,
    )
    assert calls == [(["成都"], "memory.short_term.review")]
    cached = store._get_conn().execute(
        "SELECT memory_id FROM memory0_embeddings WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    assert cached is not None


def test_legacy_short_term_vectors_are_backfilled_only_once(tmp_path):
    store = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    store.remember(ShortTermMemoryCandidate(
        content="旧短期记忆",
        scope_type="person",
        scope_id="person-a",
        person_id="person-a",
    ))
    calls: list[tuple[list[str], str]] = []

    def embed(texts, *, source=""):
        calls.append((list(texts), source))
        return [[1.0, 0.5] for _ in texts]

    for _ in range(2):
        store.find_similar(
            "查询内容",
            scope_type="person",
            scope_id="person-a",
            embedder=embed,
        )

    assert calls == [
        (["旧短期记忆"], "memory.short_term.index"),
        (["查询内容"], "memory.short_term.review"),
        (["查询内容"], "memory.short_term.review"),
    ]


def test_short_term_update_refreshes_cached_vector(tmp_path):
    store = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    calls: list[tuple[list[str], str]] = []

    def embed(texts, *, source=""):
        calls.append((list(texts), source))
        return [[float(len(text)), 1.0] for text in texts]

    memory_id = store.remember(
        ShortTermMemoryCandidate(
            content="博士想去成都",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
        ),
        embedder=embed,
    )
    store.apply_action(
        ShortTermMemoryCandidate(
            content="博士计划秋天去成都",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
        ),
        operation="UPDATE",
        target_memory_id=memory_id,
        embedder=embed,
    )

    assert calls[-1] == (["博士计划秋天去成都"], "memory.short_term.update")
    row = store._get_conn().execute(
        "SELECT content_hash FROM memory0_embeddings WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    assert row["content_hash"] == store._content_hash("博士计划秋天去成都")


def test_memories0_is_created_and_exact_candidate_is_reinforced(tmp_path):
    db_path = tmp_path / "brain.db"
    store = ShortTermMemoryStore(str(db_path))
    candidate = ShortTermMemoryCandidate(
        content="博士明天下午可能去成都",
        kind="temporary_plan",
        scope_type="person",
        scope_id="person-a",
        person_id="person-a",
        session_id="session-a",
        evidence_refs=(("message", "10"),),
    )

    first = store.remember(candidate)
    second = store.remember(candidate)

    assert first == second
    row = store.list_active()[0]
    assert row["reinforcement_count"] == 2
    assert row["scope_id"] == "person-a"
    with sqlite3.connect(db_path) as conn:
        tables = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "memories0" in tables
        assert "short_term_memories" not in tables
        evidence_count = conn.execute(
            "SELECT COUNT(*) FROM memory_evidence_links WHERE memory_layer='short_term'"
        ).fetchone()[0]
        assert evidence_count == 1


def test_recall_filters_person_and_agent_scopes_across_sessions(tmp_path):
    store = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    for content, scope_type, scope_id in (
        ("person A likes tea", "person", "person-a"),
        ("person B likes coffee", "person", "person-b"),
        ("agent learned patience", "agent", "global"),
    ):
        store.remember(
            ShortTermMemoryCandidate(
                content=content,
                scope_type=scope_type,
                scope_id=scope_id,
                person_id=scope_id if scope_type == "person" else "",
                session_id="session-a",
            )
        )

    recalled = store.recall(
        "plan tea patience",
        person_id="person-a",
        session_id="session-a",
        limit=10,
    )
    contents = {item["content"] for item in recalled}
    assert "person A likes tea" in contents
    assert "agent learned patience" in contents
    assert "person B likes coffee" not in contents

    recalled_from_another_session = store.recall(
        "tea patience",
        person_id="person-a",
        session_id="session-b",
        limit=10,
    )
    assert {item["content"] for item in recalled_from_another_session} == {
        "person A likes tea",
        "agent learned patience",
    }


def test_expired_memory_is_not_recalled(tmp_path):
    store = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    memory_id = store.remember(
        ShortTermMemoryCandidate(
            content="a temporary detail",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
            retention_seconds=60,
        )
    )
    conn = store._get_conn()
    conn.execute("UPDATE memories0 SET expires_at = ? WHERE id = ?", (time.time() - 1, memory_id))
    conn.commit()

    assert store.recall("temporary", person_id="person-a") == []
    status = conn.execute("SELECT status FROM memories0 WHERE id = ?", (memory_id,)).fetchone()[0]
    assert status == "expired"


def test_formation_defaults_conversation_memory_to_memories0(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    long_term = MagicMock()
    service = MemoryFormationService(short_term=short_term, long_term=long_term)

    results = service.form_actions(
        [{
            "type": "ADD",
            "tag": "preference_signal",
            "content": "博士这次表示喜欢苹果",
            "self": False,
        }],
        source="immediate",
        user_id="person-a",
        session_id="session-a",
    )

    assert [item.layer for item in results] == ["short_term"]
    assert short_term.list_active()[0]["content"] == "博士这次表示喜欢苹果"
    assert short_term.list_active()[0]["formation_source"] == "immediate"
    long_term.store.assert_not_called()


def test_session_context_is_not_persisted_as_memory(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    service = MemoryFormationService(short_term=short_term, long_term=MagicMock())

    service.form_actions(
        [{
            "type": "ADD",
            "content": "This detail only belongs to the current conversation.",
            "scope_type": "session",
        }],
        source="turn_batch_review",
        user_id="person-a",
        session_id="session-a",
    )

    assert short_term.list_active() == []
    assert short_term.list_for_person("person-a") == []


def test_legacy_session_memory_is_not_recalled_or_displayed(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    short_term.remember(ShortTermMemoryCandidate(
        content="The second draft is only meaningful in the original conversation.",
        scope_type="session",
        scope_id="session-a",
        person_id="person-a",
        session_id="session-a",
    ))

    assert short_term.recall(
        "second draft",
        person_id="person-a",
        session_id="session-a",
    ) == []
    assert short_term.list_for_person("person-a") == []


def test_agent_scoped_memory_is_visible_but_other_person_memory_is_not(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    short_term.remember(ShortTermMemoryCandidate(
        content="I learned not to invent personal history for rapport.",
        scope_type="agent",
        scope_id="global",
        formation_source="turn_batch_review",
    ))
    short_term.remember(ShortTermMemoryCandidate(
        content="Person B prefers private status summaries.",
        scope_type="person",
        scope_id="person-b",
        person_id="person-b",
    ))

    visible = short_term.list_for_person("person-a")
    assert len(visible) == 1
    assert visible[0]["scope_type"] == "agent"


def test_incomplete_memory_fragment_is_rejected(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    service = MemoryFormationService(short_term=short_term, long_term=MagicMock())

    result = service.form_actions(
        [{"type": "ADD", "content": "博士认同"}],
        source="immediate",
        user_id="person-a",
        session_id="session-a",
    )

    assert result == []
    assert short_term.list_active() == []


def test_formation_links_only_messages_from_current_turn(tmp_path):
    db_path = tmp_path / "brain.db"
    conversation = ConversationDB(str(db_path))
    conversation.log(
        "session-a", "user", "old turn", user_id="person-a",
        metadata={"turn_id": "turn-old"},
    )
    current_id = conversation.log(
        "session-a", "user", "remember this", user_id="person-a",
        metadata={"turn_id": "turn-current"},
    )
    short_term = ShortTermMemoryStore(str(db_path))
    service = MemoryFormationService(
        short_term=short_term,
        long_term=MagicMock(),
        conversation_db=conversation,
    )

    results = service.form_actions(
        [{"type": "ADD", "content": "current evidence"}],
        source="immediate",
        user_id="person-a",
        session_id="session-a",
        turn_id="turn-current",
    )

    links = short_term._get_conn().execute(
        "SELECT evidence_id FROM memory_evidence_links WHERE memory_id = ?",
        (results[0].memory_id,),
    ).fetchall()
    assert [row[0] for row in links] == [str(current_id)]
    conversation.close()
    short_term.close()


def test_explicit_long_term_candidate_bypasses_memories0(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    long_term = MagicMock()
    long_term.store.return_value = 42
    service = MemoryFormationService(short_term=short_term, long_term=long_term)

    results = service.form_actions(
        [{
            "type": "ADD",
            "tag": "safety",
            "content": "博士对花生严重过敏",
            "retention": "long_term",
            "importance": 0.95,
        }],
        source="immediate",
        user_id="person-a",
        session_id="session-a",
    )

    assert results[0].layer == "long_term"
    assert results[0].memory_id == 42
    assert short_term.list_active() == []


def test_dream_consolidates_repeated_memory_and_retains_weak_one(tmp_path):
    short_term = ShortTermMemoryStore(str(tmp_path / "brain.db"))
    long_term = MagicMock()
    long_term.store.return_value = 88
    service = MemoryFormationService(short_term=short_term, long_term=long_term)
    repeated = ShortTermMemoryCandidate(
        content="博士不喜欢苹果",
        kind="preference_signal",
        scope_type="person",
        scope_id="person-a",
        person_id="person-a",
    )
    for _ in range(3):
        short_term.remember(repeated)
    short_term.remember(
        ShortTermMemoryCandidate(
            content="博士今天穿了蓝色衣服",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
            importance=0.2,
        )
    )

    result = service.consolidate_for_dream()

    assert result == {"consolidated": 1, "retained": 1, "expired": 0}
    active = short_term.list_active()
    assert [item["content"] for item in active] == ["博士今天穿了蓝色衣服"]
    long_term.store.assert_called_once()
