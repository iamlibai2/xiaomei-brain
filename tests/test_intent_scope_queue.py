import sqlite3
import time

from xiaomei_brain.consciousness.intent import Intent, normalize_intent_record
from xiaomei_brain.consciousness.queue_storage import TaskQueueStorage
from xiaomei_brain.consciousness.context_pipeline import _project_self_image
from xiaomei_brain.consciousness.self_image_proxy import SelfImage


def _work(content: str, person: str, session: str, priority: int = 50) -> dict:
    return normalize_intent_record({
        "type": "work",
        "priority": priority,
        "content": content,
        "scope_type": "session",
        "user_id": person,
        "session_id": session,
        "params": {},
    })


def test_two_work_intents_keep_distinct_owners_and_consumption(tmp_path):
    storage = TaskQueueStorage(str(tmp_path / "brain.db"))
    ppt = _work("完善甲的 PPT", "person-a", "session-a", 60)
    word = _work("完成乙的 Word", "person-b", "session-b", 55)

    storage.add_intent(ppt)
    storage.add_intent(word)
    pending = storage.load_pending_intents()

    assert [item["intent_id"] for item in pending] == [ppt["intent_id"], word["intent_id"]]
    assert {(item["user_id"], item["session_id"]) for item in pending} == {
        ("person-a", "session-a"),
        ("person-b", "session-b"),
    }

    assert storage.mark_intent_consumed(ppt["intent_id"]) == 1
    remaining = storage.load_pending_intents()
    assert [item["intent_id"] for item in remaining] == [word["intent_id"]]


def test_sync_preserves_stable_intent_ids(tmp_path):
    storage = TaskQueueStorage(str(tmp_path / "brain.db"))
    item = _work("稍后处理", "person-a", "session-a")
    storage.add_intent(item)

    storage.sync_intents([item])
    storage.sync_intents([item])

    pending = storage.load_pending_intents()
    assert len(pending) == 1
    assert pending[0]["intent_id"] == item["intent_id"]


def test_person_projection_does_not_mutate_shared_self_image():
    shared = SelfImage()
    shared.current_user_id = "person-a"
    projected = _project_self_image(shared)

    projected.current_user_id = "person-b"
    projected.memory.recalled_memories = [{"content": "B's memory"}]

    assert shared.current_user_id == "person-a"
    assert shared.memory is not projected.memory
    assert shared.memory.recalled_memories == []


def test_existing_intent_table_is_upgraded_without_losing_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE intent_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,
            priority INTEGER, content TEXT, trigger_time REAL, source TEXT,
            params TEXT, status TEXT, created_at REAL
        )"""
    )
    conn.execute(
        "INSERT INTO intent_buffer(type, priority, content, trigger_time, source, params, status, created_at) "
        "VALUES('WORK', 50, '旧任务', ?, 'legacy', '{}', 'pending', ?)",
        (time.time(), time.time()),
    )
    conn.commit()
    conn.close()

    storage = TaskQueueStorage(str(db_path))
    pending = storage.load_pending_intents()

    assert len(pending) == 1
    assert pending[0]["content"] == "旧任务"
    assert pending[0]["intent_id"].startswith("legacy_")
    assert pending[0]["scope_type"] == "agent"


def test_intent_object_round_trip_keeps_identity_and_scope():
    original = _work("继续 PPT", "person-a", "session-a")
    restored = Intent.from_dict(original).to_dict()
    assert restored["intent_id"] == original["intent_id"]
    assert restored["scope_type"] == "session"
    assert restored["user_id"] == "person-a"
    assert restored["session_id"] == "session-a"
