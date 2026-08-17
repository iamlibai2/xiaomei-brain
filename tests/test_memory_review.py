from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.formation import MemoryFormationService
from xiaomei_brain.memory.review import (
    MemoryReviewProtocolError,
    TurnBatchMemoryReviewer,
)
from xiaomei_brain.memory.short_term import (
    ShortTermMemoryCandidate,
    ShortTermMemoryStore,
)
from xiaomei_brain.consciousness.internal_display import InternalDisplay
from xiaomei_brain.consciousness.internal_processing import InternalProcessingReport


class StubLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.content)


def _log_turn(
    db: ConversationDB,
    *,
    person_id: str,
    session_id: str,
    turn_id: str,
    user: str,
    assistant: str,
) -> tuple[int, int]:
    user_id = db.log(
        session_id,
        "user",
        user,
        user_id=person_id,
        metadata={"turn_id": turn_id},
    )
    assistant_id = db.log(
        session_id,
        "assistant",
        assistant,
        user_id=person_id,
        metadata={"turn_id": turn_id},
    )
    return int(user_id), int(assistant_id)


def _reviewer(tmp_path, response: str):
    db_path = tmp_path / "brain.db"
    db = ConversationDB(db_path)
    short_term = ShortTermMemoryStore(str(db_path))
    long_term = MagicMock()
    long_term.recall.return_value = []
    long_term._embed_batch.side_effect = lambda texts: [
        [1.0, float(index + 1) / 100.0] for index, _ in enumerate(texts)
    ]
    formation = MemoryFormationService(
        short_term=short_term,
        long_term=long_term,
        conversation_db=db,
    )
    llm = StubLLM(response)
    reviewer = TurnBatchMemoryReviewer(
        llm_client=llm,
        conversation_db=db,
        formation_service=formation,
        longterm_memory=long_term,
    )
    return reviewer, db, short_term, llm


def test_three_turn_review_is_scoped_and_links_exact_evidence(tmp_path):
    response = """{
      "actions": [{
        "operation": "ADD",
        "kind": "preference_signal",
        "content": "博士喜欢大连，并在2013年左右去过星海广场",
        "scope_type": "person",
        "confidence": 0.85,
        "importance": 0.6,
        "evidence_turn_ids": ["a-1", "a-3"]
      }]
    }"""
    reviewer, db, short_term, _llm = _reviewer(tmp_path, response)
    a1 = _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="a-1",
        user="我喜欢大连", assistant="大连很漂亮",
    )
    _log_turn(
        db, person_id="person-b", session_id="session-b", turn_id="b-1",
        user="我喜欢成都", assistant="成都也很好",
    )
    _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="a-2",
        user="大概2013年去的", assistant="记下这个时间",
    )
    a3 = _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="a-3",
        user="去过星海广场", assistant="这段经历接上了",
    )

    result = reviewer.review_next(
        person_id="person-a",
        session_id="session-a",
        user_name="博士",
    )

    assert result.processed is True
    assert result.turn_count == 3
    assert result.added == 1
    memory = short_term.list_active()[0]
    assert memory["scope_type"] == "person"
    assert memory["scope_id"] == "person-a"
    assert memory["person_id"] == "person-a"
    assert memory["session_id"] == "session-a"
    assert memory["formation_source"] == "turn_batch_review"
    links = short_term._get_conn().execute(
        "SELECT evidence_id FROM memory_evidence_links WHERE memory_id = ? ORDER BY evidence_id",
        (memory["id"],),
    ).fetchall()
    assert {row[0] for row in links} == {str(value) for value in (*a1, *a3)}
    checkpoint_a = db.get_memory_review_checkpoint("person-a", "session-a")
    checkpoint_b = db.get_memory_review_checkpoint("person-b", "session-b")
    assert checkpoint_a["last_message_id"] == a3[1]
    assert checkpoint_a["reviewed_turn_count"] == 3
    assert checkpoint_b["last_message_id"] == 0


def test_review_uses_source_message_time_as_memory_event_range(tmp_path):
    response = """{
      "actions": [{
        "operation": "ADD",
        "kind": "event",
        "content": "博士明确要求空闲时自主完成工作并交付",
        "scope_type": "person",
        "confidence": 0.9,
        "importance": 0.8,
        "evidence_turn_ids": ["turn-1", "turn-3"]
      }]
    }"""
    reviewer, db, short_term, llm = _reviewer(tmp_path, response)
    first = _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="turn-1",
        user="闲了就自己做", assistant="明白",
    )
    _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="turn-2",
        user="不是等我催", assistant="知道了",
    )
    last = _log_turn(
        db, person_id="person-a", session_id="session-a", turn_id="turn-3",
        user="做完自己交付", assistant="记住了",
    )
    source_times = {
        first[0]: datetime(2026, 8, 17, 16, 12, 40).timestamp(),
        first[1]: datetime(2026, 8, 17, 16, 12, 45).timestamp(),
        last[0]: datetime(2026, 8, 17, 16, 14, 20).timestamp(),
        last[1]: datetime(2026, 8, 17, 16, 14, 25).timestamp(),
    }
    for message_id, created_at in source_times.items():
        db._get_conn().execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            (created_at, message_id),
        )
    db._get_conn().commit()

    reviewer.review_next(person_id="person-a", session_id="session-a", user_name="博士")

    memory = short_term.list_active()[0]
    assert memory["event_time"] == datetime(2026, 8, 17, 16, 12, 40).timestamp()
    assert memory["event_time_end"] == datetime(2026, 8, 17, 16, 14, 25).timestamp()
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "2026-08-17 16:12:40" in prompt
    assert "2026-08-17 16:14:25" in prompt


def test_review_waits_for_three_complete_turns(tmp_path):
    reviewer, db, _short_term, llm = _reviewer(
        tmp_path,
        '{"actions":[{"operation":"NOOP"}]}',
    )
    for index in range(2):
        _log_turn(
            db,
            person_id="person-a",
            session_id="session-a",
            turn_id=f"turn-{index}",
            user=f"user {index}",
            assistant=f"assistant {index}",
        )

    result = reviewer.review_next(person_id="person-a", session_id="session-a")

    assert result.processed is False
    assert llm.calls == []
    assert db.get_memory_review_checkpoint("person-a", "session-a")["last_message_id"] == 0


def test_review_encodes_query_once_and_reuses_it_across_scopes(tmp_path):
    reviewer, db, short_term, _llm = _reviewer(
        tmp_path,
        '{"actions":[{"operation":"NOOP"}]}',
    )
    for scope_type, scope_id, content in (
        ("person", "person-a", "博士喜欢成都"),
        ("agent", "global", "小美喜欢下雨天"),
    ):
        short_term.remember(
            ShortTermMemoryCandidate(
                content=content,
                scope_type=scope_type,
                scope_id=scope_id,
                person_id="person-a" if scope_type == "person" else "",
            ),
            embedder=reviewer._embedding_batch,
        )
    reviewer.longterm._embed_batch.reset_mock()
    for index in range(3):
        _log_turn(
            db,
            person_id="person-a",
            session_id="session-a",
            turn_id=f"turn-{index}",
            user=f"成都补充 {index}",
            assistant=f"收到 {index}",
        )

    reviewer.review_next(person_id="person-a", session_id="session-a")

    review_calls = [
        call for call in reviewer.longterm._embed_batch.call_args_list
        if call.kwargs.get("source") == "memory.short_term.review"
    ]
    assert len(review_calls) == 1
    assert len(review_calls[0].args[0]) == 1


def test_merge_updates_existing_memory_instead_of_inserting_duplicate(tmp_path):
    db_path = tmp_path / "brain.db"
    db = ConversationDB(db_path)
    short_term = ShortTermMemoryStore(str(db_path))
    original = short_term.remember(
        ShortTermMemoryCandidate(
            content="博士最近想去成都",
            kind="preference_signal",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
            session_id="session-a",
        )
    )
    formation = MemoryFormationService(
        short_term=short_term,
        long_term=MagicMock(),
        conversation_db=db,
    )

    results = formation.form_actions(
        [{
            "operation": "MERGE",
            "target_memory_id": original,
            "kind": "preference_signal",
            "content": "博士最近想去成都，因为喜欢这个城市的节奏和多雨天气",
            "scope_type": "person",
            "evidence_turn_ids": ["turn-3"],
        }],
        source="turn_batch_review",
        user_id="person-a",
        session_id="session-a",
        evidence_by_turn={"turn-3": (("message", "33"),)},
        allowed_target_ids={original},
        embedder=lambda _texts: [[1.0, 0.0], [1.0, 0.0]],
    )

    assert [result.memory_id for result in results] == [original]
    active = short_term.list_active()
    assert len(active) == 1
    assert active[0]["content"].endswith("喜欢这个城市的节奏和多雨天气")
    assert active[0]["reinforcement_count"] == 2
    evidence = short_term._get_conn().execute(
        "SELECT evidence_id FROM memory_evidence_links WHERE memory_id = ?",
        (original,),
    ).fetchall()
    assert [row[0] for row in evidence] == ["33"]


def test_high_similarity_add_is_converted_to_merge(tmp_path):
    response = """{
      "actions": [{
        "operation": "ADD",
        "kind": "preference_signal",
        "content": "博士最近想去成都，因为喜欢这个城市的节奏",
        "scope_type": "person",
        "evidence_turn_ids": ["turn-1", "turn-2", "turn-3"]
      }]
    }"""
    reviewer, db, short_term, _llm = _reviewer(tmp_path, response)
    original = short_term.remember(
        ShortTermMemoryCandidate(
            content="博士最近想去成都",
            kind="preference_signal",
            scope_type="person",
            scope_id="person-a",
            person_id="person-a",
            session_id="session-a",
        )
    )
    # Keep this test focused on the review policy rather than vector values.
    reviewer._short_term_candidates = lambda *_args, **_kwargs: [{
        **short_term.get_active(original),
        "similarity": 0.95,
    }]
    for index in range(1, 4):
        _log_turn(
            db,
            person_id="person-a",
            session_id="session-a",
            turn_id=f"turn-{index}",
            user=f"成都补充 {index}",
            assistant=f"收到 {index}",
        )

    result = reviewer.review_next(person_id="person-a", session_id="session-a")

    assert result.added == 0
    assert result.merged == 1
    assert len(short_term.list_active()) == 1
    assert short_term.list_active()[0]["id"] == original


def test_invalid_json_does_not_advance_checkpoint(tmp_path):
    reviewer, db, _short_term, _llm = _reviewer(tmp_path, "not json")
    for index in range(3):
        _log_turn(
            db,
            person_id="person-a",
            session_id="session-a",
            turn_id=f"turn-{index}",
            user=f"user {index}",
            assistant=f"assistant {index}",
        )

    with pytest.raises(MemoryReviewProtocolError):
        reviewer.review_next(person_id="person-a", session_id="session-a")

    assert db.get_memory_review_checkpoint("person-a", "session-a")["last_message_id"] == 0


def test_memory_review_counts_are_visible_to_cli_and_activity():
    display = InternalDisplay()
    display.record_memory_review({
        "turn_count": 3,
        "added": 1,
        "updated": 1,
        "merged": 2,
        "reinforced": 1,
        "deleted": 0,
        "noop": 0,
        "rejected": 0,
        "count": 5,
    })

    payload = display.to_dict()
    lines = display.render_lines()
    report = InternalProcessingReport.from_display(payload)

    assert "三轮记忆复盘" in lines[0]
    assert payload["data"]["memory_review"]["merged"] == 2
    assert {item.key for item in report.items} == {
        "memory_review_added",
        "memory_review_updated",
        "memory_review_merged",
        "memory_review_reinforced",
    }
