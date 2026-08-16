from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.config import ConsciousnessConfig
from xiaomei_brain.consciousness.core import Consciousness
from xiaomei_brain.consciousness.relationship import RelationshipEngine
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.metacognition.social_cognition import (
    SocialCognition,
    SocialCognitionResult,
)


def _log_turn(
    db: ConversationDB,
    *,
    person_id: str,
    session_id: str,
    turn_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    metadata = {"turn_id": turn_id}
    db.log(session_id, "user", user_text, user_id=person_id, metadata=metadata)
    db.log(
        session_id,
        "assistant",
        assistant_text,
        user_id=person_id,
        metadata=metadata,
    )


def test_social_review_cursor_skips_history_and_keeps_scopes_separate(tmp_path):
    db = ConversationDB(tmp_path / "brain.db")
    _log_turn(
        db,
        person_id="person-a",
        session_id="desktop-a",
        turn_id="old",
        user_text="旧消息",
        assistant_text="旧回复",
    )
    db.initialize_memory_review_checkpoints("social_cognition")

    assert db.list_pending_memory_review_scopes(
        review_type="social_cognition"
    ) == []

    _log_turn(
        db,
        person_id="person-a",
        session_id="desktop-a",
        turn_id="new-a",
        user_text="今天有点紧张",
        assistant_text="我听见了",
    )
    _log_turn(
        db,
        person_id="person-b",
        session_id="feishu-b",
        turn_id="new-b",
        user_text="谢谢你",
        assistant_text="不客气",
    )
    # A restart must not move unprocessed cursors to the end.
    db.initialize_memory_review_checkpoints("social_cognition")

    scopes = db.list_pending_memory_review_scopes(review_type="social_cognition")
    assert {(item["person_id"], item["session_id"]) for item in scopes} == {
        ("person-a", "desktop-a"),
        ("person-b", "feishu-b"),
    }
    batch = db.get_next_memory_review_batch(
        "person-a",
        "desktop-a",
        batch_turns=5,
        minimum_turns=1,
        review_type="social_cognition",
    )
    assert batch is not None
    assert batch["turn_ids"] == ["new-a"]
    assert {item["user_id"] for item in batch["messages"]} == {"person-a"}
    assert {item["session_id"] for item in batch["messages"]} == {"desktop-a"}


def test_social_cognition_routes_person_scoped_results(monkeypatch):
    class Llm:
        def chat(self, messages):
            return SimpleNamespace(
                content=(
                    "---EVENTS---\n{}\n"
                    "---PERCEPTION---\n- 对方正在试着建立信任\n"
                    "---SIGNAL---\n"
                    '{"social_signal":"user_trusting","intensity":0.8}'
                )
            )

    class Drive:
        def __init__(self):
            self.signals = []

        def apply_social_signal(self, signal_type, intensity):
            self.signals.append((signal_type, intensity))

    class Memory:
        def __init__(self):
            self.items = []

        def store_narrative(self, **kwargs):
            self.items.append(kwargs)

    class Relationship:
        def __init__(self):
            self.calls = []

        def on_social_signal_for(self, person_id, signal_type, intensity):
            self.calls.append((person_id, signal_type, intensity))

    drive = Drive()
    memory = Memory()
    relationship = Relationship()
    monkeypatch.setattr(
        "xiaomei_brain.metacognition.social_cognition.build_simple_context",
        lambda *args, **kwargs: "agent context",
    )
    engine = SocialCognition(
        llm=Llm(),
        self_image=SimpleNamespace(),
        consciousness=SimpleNamespace(),
        drive=drive,
        longterm_memory=memory,
    )

    result = engine.reflect(
        context="scheduler",
        user_name="甲",
        recent_conversation="甲：谢谢你\n小美：不客气",
        person_id="person-a",
        session_id="desktop-a",
        relationship_engine=relationship,
    )

    assert result.completed is True
    assert result.perceptions == ["对方正在试着建立信任"]
    assert drive.signals == [("user_trusting", 0.8)]
    assert relationship.calls == [("person-a", "user_trusting", 0.8)]
    assert all(item["user_id"] == "person-a" for item in memory.items)
    assert all(
        item["conversation_summary"] == "source_session=desktop-a"
        for item in memory.items
    )


def test_scheduler_advances_cursor_only_after_completed_review(tmp_path):
    db = ConversationDB(tmp_path / "brain.db")
    db.initialize_memory_review_checkpoints("social_cognition")
    _log_turn(
        db,
        person_id="person-a",
        session_id="desktop-a",
        turn_id="turn-a",
        user_text="你好",
        assistant_text="你好",
    )
    agent_core = SimpleNamespace(identity_mgr=None)
    agent = SimpleNamespace(
        id="test",
        conversation_db=db,
        _get_agent=lambda: agent_core,
    )
    consciousness = Consciousness(
        agent_instance=agent,
        consciousness_config=ConsciousnessConfig(sc_cooldown=0.0),
    )
    consciousness.self_image.body = SimpleNamespace(energy=1.0)

    class Reviewer:
        def __init__(self, status):
            self.status = status

        def reflect(self, **kwargs):
            return SocialCognitionResult(
                self.status,
                kwargs["person_id"],
                kwargs["session_id"],
            )

    consciousness._social_cognition = Reviewer("failed")
    batch = consciousness._next_social_cognition_batch("idle")
    assert batch is not None
    failed = consciousness.request_social_cognition(batch)
    assert failed.completed is False
    assert db.get_memory_review_checkpoint(
        "person-a", "desktop-a", review_type="social_cognition"
    )["last_message_id"] == 0

    consciousness._last_sc_time = 0.0
    consciousness._social_cognition = Reviewer("completed")
    completed = consciousness.request_social_cognition(batch)
    assert completed.completed is True
    checkpoint = db.get_memory_review_checkpoint(
        "person-a", "desktop-a", review_type="social_cognition"
    )
    assert checkpoint["last_message_id"] == batch["max_message_id"]
    assert checkpoint["reviewed_turn_count"] == 1


def test_social_scheduler_requires_idle_energy_and_enabled(tmp_path):
    db = ConversationDB(tmp_path / "brain.db")
    db.initialize_memory_review_checkpoints("social_cognition")
    _log_turn(
        db,
        person_id="person-a",
        session_id="desktop-a",
        turn_id="turn-a",
        user_text="你好",
        assistant_text="你好",
    )
    agent = SimpleNamespace(id="test", conversation_db=db)
    config = ConsciousnessConfig(sc_cooldown=0.0, sc_energy_threshold=0.5)
    consciousness = Consciousness(agent_instance=agent, consciousness_config=config)
    consciousness._social_cognition = object()
    consciousness.self_image.body = SimpleNamespace(energy=0.4)
    assert consciousness._next_social_cognition_batch("idle") is None
    consciousness.self_image.body.energy = 0.8
    assert consciousness._next_social_cognition_batch("awake") is None
    assert consciousness._next_social_cognition_batch("idle") is not None
    consciousness._cc.sc_enabled = False
    assert consciousness._next_social_cognition_batch("idle") is None


def test_scoped_relationship_signal_does_not_switch_active_person(tmp_path):
    relationship = RelationshipEngine(str(tmp_path / "brain.db"), user_id="person-a")
    relationship.load("person-a")
    active_snapshot = (relationship.depth, relationship.trust, relationship.closeness)

    result = relationship.on_social_signal_for(
        "person-b",
        "user_trusting",
        0.5,
    )

    assert relationship._user_id == "person-a"
    assert (relationship.depth, relationship.trust, relationship.closeness) == active_snapshot
    assert result["user_id"] == "person-b"
    assert result["trust"] == 0.14
