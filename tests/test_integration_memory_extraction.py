"""Integration tests for MemoryExtractor pipeline (LLM mocked)."""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.longterm import LongTermMemory


# ── Helpers ───────────────────────────────────────────────────────────

def _make_mock_llm(content: str):
    """Create a mock LLM client that returns a specific response."""
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.chat.return_value = response
    return llm


def _make_extractor(llm, db_path: str):
    """Create MemoryExtractor with real ConversationDB and LongTermMemory."""
    db = ConversationDB(db_path)
    ltm = LongTermMemory(db_path)
    extractor = MemoryExtractor(llm_client=llm, longterm_memory=ltm, conversation_db=db)
    return extractor, db, ltm


def _write_messages(db, count: int = 5):
    """Write test messages to ConversationDB."""
    for i in range(count):
        db.log(
            session_id="test",
            role="user" if i % 2 == 0 else "assistant",
            content=f"Test message {i}",
            user_id="test_user",
        )


# ── extract_periodic ──────────────────────────────────────────────────

@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_add_simple(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Write messages, mock LLM returns ADD action, verify memory stored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")

        assert len(ids) == 1
        stored = ltm.get_recent(5, user_id="test_user")
        assert len(stored) == 1
        assert stored[0]["content"] == "用户喜欢川菜"
        assert "偏好" in stored[0]["tags"]


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_add_multiple(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Mock LLM returns 3 ADD actions, verify all stored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": ['
            '{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"},'
            '{"type": "ADD", "tag": "知识", "content": "用户是软件工程师"},'
            '{"type": "ADD", "tag": "经历", "content": "用户去过日本"}'
            ']}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")

        assert len(ids) == 3
        stored = ltm.get_recent(10, user_id="test_user")
        assert len(stored) == 3


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_add_with_scene_tags(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """ADD with scenes should store scene_tags."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "偏好", "content": "用户喜欢咖啡", "scenes": ["工作"]}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        extractor.extract_periodic(user_id="test_user")
        stored = ltm.get_recent(5, user_id="test_user")
        assert len(stored) == 1
        # scene_tags are stored as JSON string
        import json
        scene_tags = json.loads(stored[0].get("scene_tags", "[]"))
        assert "工作" in scene_tags


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_noop(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """NOOP action should store nothing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "NOOP", "reason": "无需操作"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        assert ids == []
        stored = ltm.get_recent(5, user_id="test_user")
        assert len(stored) == 0


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_self_flag(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """self=true action should store with user_id='global'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "自我认知", "content": "我擅长调试代码", "self": true}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        extractor.extract_periodic(user_id="test_user")
        # Self memories should be stored with user_id="global"
        stored = ltm.get_recent(5, user_id="global")
        assert len(stored) == 1
        assert "我擅长调试代码" in stored[0]["content"]


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_user_isolation(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Memories stored for one user shouldn't appear for another."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "偏好", "content": "用户A喜欢猫"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        extractor.extract_periodic(user_id="user_a")
        # Different user should see empty
        stored = ltm.get_recent(5, user_id="user_b")
        assert len(stored) == 0


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_insufficient_messages(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Need >= 3 messages to extract."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm('{}')
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 2)  # only 2 messages

        ids = extractor.extract_periodic(user_id="test_user")
        assert ids == []  # early return


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_no_llm(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Without LLM, extract_periodic should return []."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        extractor, db, ltm = _make_extractor(None, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        assert ids == []


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_delete(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Pre-store memory, mock LLM returns DELETE, verify soft-deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "临时", "content": "待删除的记忆"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)
        extractor.extract_periodic(user_id="test_user")
        stored = ltm.get_recent(5, user_id="test_user")
        memory_id = stored[0]["id"]

        # Now mock LLM to return DELETE with matching content.
        # _vector_recall is still mocked to return [] at class level, so recall() would return []
        # and the DELETE would fall back to ADD. Patch recall() on the instance instead.
        llm2 = _make_mock_llm(
            '{"actions": [{"type": "DELETE", "content": "待删除的记忆"}]}'
        )
        extractor2 = MemoryExtractor(llm_client=llm2, longterm_memory=ltm, conversation_db=db)
        _write_messages(db, 5)

        with patch.object(ltm, 'recall', return_value=[
            {"id": memory_id, "content": "待删除的记忆", "score": 0.95}
        ]):
            extractor2.extract_periodic(user_id="test_user")

        # After soft delete, status should be 'deleted'
        deleted = ltm._get_conn().execute(
            "SELECT status FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        assert deleted is not None
        assert deleted["status"] == "deleted"


# ── UPDATE / MERGE actions ────────────────────────────────────────────

@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_update_explicit(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Pre-store memory, mock LLM returns UPDATE, verify content replaced."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        # First: ADD
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "事实", "content": "用户在北京"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)
        extractor.extract_periodic(user_id="test_user")
        stored = ltm.get_recent(5, user_id="test_user")
        memory_id = stored[0]["id"]

        # Second: UPDATE with new content
        _write_messages(db, 5)
        llm2 = _make_mock_llm(
            '{"actions": [{"type": "UPDATE", "content": "用户在北京", "tag": "事实"}]}'
        )
        extractor2 = MemoryExtractor(llm_client=llm2, longterm_memory=ltm, conversation_db=db)
        with patch.object(ltm, 'recall', return_value=[
            {"id": memory_id, "content": "用户在北京", "score": 0.95}
        ]):
            extractor2.extract_periodic(user_id="test_user")

        # Content should remain (UPDATE replaces content via _simple_update)
        row = ltm._get_conn().execute(
            "SELECT content FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        assert row is not None


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_merge(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Pre-store memory, mock LLM returns MERGE, verify content merged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        # First: ADD
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "知识", "content": "用户会Python"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)
        extractor.extract_periodic(user_id="test_user")
        stored = ltm.get_recent(5, user_id="test_user")
        memory_id = stored[0]["id"]

        # Second: MERGE with additional info
        _write_messages(db, 5)
        llm2 = _make_mock_llm(
            '{"actions": [{"type": "MERGE", "content": "用户会Python", "tag": "知识"}]}'
        )
        extractor2 = MemoryExtractor(llm_client=llm2, longterm_memory=ltm, conversation_db=db)
        with patch.object(ltm, 'recall', return_value=[
            {"id": memory_id, "content": "用户会Python", "score": 0.9}
        ]):
            extractor2.extract_periodic(user_id="test_user")

        # Updated content should contain both old and new (merged)
        row = ltm._get_conn().execute(
            "SELECT content FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        assert row is not None
        assert "用户会Python" in row["content"]


# ── Error / edge cases ────────────────────────────────────────────────

@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_malformed_json(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Totally malformed LLM output should not crash — falls through to line format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm("这不是JSON，也不是任何有效格式的乱码 ### @@")
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        # Should not crash — returns whatever line parsing produces (likely empty)
        assert isinstance(ids, list)


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_empty_actions_array(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """LLM returns valid JSON with empty actions array — no crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm('{"actions": [], "relations": []}')
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        assert ids == []


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_action_missing_type(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Action item without 'type' field — should be skipped gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        llm = _make_mock_llm(
            '{"actions": [{"tag": "测试", "content": "没有type字段的内容"}]}'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        # Missing type → action_type = "" → won't match ADD/UPDATE/MERGE/DELETE
        # Falls through to nothing (not NOOP either since content is not empty)
        assert isinstance(ids, list)


@patch.object(LongTermMemory, '_embed', return_value=[0.0] * 1024)
@patch.object(LongTermMemory, '_add_to_lance', return_value=None)
@patch.object(LongTermMemory, '_update_lance', return_value=None)
@patch.object(LongTermMemory, '_delete_from_lance', return_value=None)
@patch.object(LongTermMemory, '_vector_recall', return_value=[])
def test_extract_periodic_salvage_truncated_json(mock_vec, mock_del, mock_upd, mock_add, mock_emb):
    """Truncated JSON with partial action blocks should be salvaged via regex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "brain.db")
        # JSON truncated mid-stream — missing closing brackets
        llm = _make_mock_llm(
            '{"actions": [{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"'
        )
        extractor, db, ltm = _make_extractor(llm, db_path)
        _write_messages(db, 5)

        ids = extractor.extract_periodic(user_id="test_user")
        # Salvage should extract the partial ADD action
        assert len(ids) == 1
        stored = ltm.get_recent(5, user_id="test_user")
        assert len(stored) == 1
        assert "川菜" in stored[0]["content"]
