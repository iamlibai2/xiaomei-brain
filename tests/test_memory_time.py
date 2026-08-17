from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from xiaomei_brain.base.sqlite_store import SQLiteStore
from xiaomei_brain.consciousness.workspace.render_consciousness_v3 import (
    _render_internal_narratives,
    _render_longterm_memories,
)
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.short_term import ShortTermMemoryCandidate, ShortTermMemoryStore


def test_longterm_store_preserves_event_range_separately_from_created_at(tmp_path):
    memory = object.__new__(LongTermMemory)
    SQLiteStore.__init__(memory, str(tmp_path / "brain.db"))
    memory._init_tables()
    memory._add_to_lance = lambda *_args, **_kwargs: None
    start = datetime(2026, 8, 17, 16, 12).timestamp()
    end = datetime(2026, 8, 17, 16, 14).timestamp()

    memory_id = memory.store(
        "一段有原始证据时间的记忆",
        source="manual",
        user_id="person-a",
        event_time=start,
        event_time_end=end,
    )

    row = memory._get_conn().execute(
        "SELECT event_time, event_time_end, created_at FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    assert row["event_time"] == start
    assert row["event_time_end"] == end
    assert row["created_at"] > end


def test_longterm_renderer_does_not_present_formation_time_as_event_time():
    source_time = datetime(2026, 8, 17, 16, 12).timestamp()
    formed_time = datetime(2026, 8, 18, 8, 0).timestamp()
    si = SimpleNamespace(memory=SimpleNamespace(
        important_memories=[{
            "id": 1,
            "content": "有证据的记忆",
            "event_time": source_time,
            "event_time_end": source_time,
            "created_at": formed_time,
            "effective_strength": 1.0,
        }, {
            "id": 2,
            "content": "旧记忆",
            "created_at": formed_time,
            "effective_strength": 1.0,
        }],
        recalled_memories=[],
    ))

    rendered = "\n".join(_render_longterm_memories(si))

    assert "发生于 2026-08-17 16:12:00" in rendered
    assert "形成于 2026-08-18 08:00:00（发生时间未知）" in rendered


def test_internal_narratives_render_newest_first_with_real_time():
    newest = datetime(2026, 8, 17, 16, 12).timestamp()
    older = datetime(2026, 8, 17, 15, 0).timestamp()
    si = SimpleNamespace(memory=SimpleNamespace(internal_narratives=[
        {"content": "最新想法", "created_at": newest},
        {"content": "较早想法", "created_at": older},
    ]))

    rendered = "\n".join(_render_internal_narratives(si))

    assert rendered.index("最新想法") < rendered.index("较早想法")
    assert "你上一次想了（思考于 2026-08-17 16:12:00）" in rendered


def test_existing_memories_backfill_event_time_from_message_evidence(tmp_path):
    db_path = tmp_path / "brain.db"
    conversation = ConversationDB(db_path)
    short_term = ShortTermMemoryStore(str(db_path))
    message_id = conversation.log(
        "session-a",
        "user",
        "这是原始证据",
        user_id="person-a",
        metadata={"turn_id": "turn-1"},
    )
    occurred_at = datetime(2026, 8, 17, 16, 12).timestamp()
    conversation._get_conn().execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        (occurred_at, message_id),
    )
    conversation._get_conn().commit()
    memory_id = short_term.remember(ShortTermMemoryCandidate(
        content="旧短期记忆",
        scope_type="person",
        scope_id="person-a",
        evidence_refs=(("message", str(message_id)),),
    ))
    conn = short_term._get_conn()
    assert conn.execute(
        "SELECT event_time FROM memories0 WHERE id = ?", (memory_id,)
    ).fetchone()[0] is None

    short_term._backfill_event_times(conn, table="memories0", layer="short_term")
    conn.commit()

    row = conn.execute(
        "SELECT event_time, event_time_end FROM memories0 WHERE id = ?", (memory_id,)
    ).fetchone()
    assert row["event_time"] == occurred_at
    assert row["event_time_end"] == occurred_at
