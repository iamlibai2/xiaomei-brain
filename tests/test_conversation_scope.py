from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.consciousness.attention_layer import AttentionLayer
from xiaomei_brain.consciousness.message_gateway import (
    configure_agent_conversation_scope,
)
from xiaomei_brain.gateway.inbound import Gateway, RawMessage
from xiaomei_brain.people import PeopleService, PeopleStore
from xiaomei_brain.tools.registry import ToolRegistry


def test_agent_short_term_messages_are_scoped_by_context_key():
    agent = Agent(llm=Mock(), tools=ToolRegistry())
    attention = AttentionLayer(agent)

    agent.context_key = "person:person-1"
    agent.messages = [{"role": "user", "content": "私人内容"}]
    attention._current_context = "person:person-1"
    attention.switch_to("conversation:group-1")
    agent.messages.append({"role": "user", "content": "群聊内容"})

    attention.switch_to("person:person-1")
    assert [message["content"] for message in agent.messages] == ["私人内容"]
    attention.switch_to("conversation:group-1")
    assert [message["content"] for message in agent.messages] == ["群聊内容"]


def test_activate_loaded_empty_session_preserves_previous_context():
    agent = Agent(llm=Mock(), tools=ToolRegistry())
    attention = AttentionLayer(agent)

    agent.context_key = "session:old"
    agent.messages = [{"role": "user", "content": "old session"}]
    attention._current_context = "session:old"

    attention.activate_loaded("session:new", [])
    assert agent.context_key == "session:new"
    assert agent.messages == []

    attention.switch_to("session:old")
    assert agent.messages == [{"role": "user", "content": "old session"}]


def test_preload_loaded_does_not_replace_active_turn():
    agent = Agent(llm=Mock(), tools=ToolRegistry())
    attention = AttentionLayer(agent)

    agent.context_key = "session:desktop"
    agent.messages = [{"role": "user", "content": "desktop turn"}]
    agent.user_id = "person-desktop"
    attention._current_context = "session:desktop"

    attention.preload_loaded(
        "person:person-cli",
        [{"role": "user", "content": "cli history"}],
    )

    assert agent.context_key == "session:desktop"
    assert agent.user_id == "person-desktop"
    assert agent.messages == [{"role": "user", "content": "desktop turn"}]

    attention.switch_to("person:person-cli")
    assert agent.messages == [{"role": "user", "content": "cli history"}]


def test_shared_conversation_uses_its_own_memory_scope(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    people.store.ensure_session(
        "group-session",
        "conversation",
        "feishu:app:demo:chat:group-1",
    )
    living = SimpleNamespace(_people_service=people)
    agent = SimpleNamespace()

    configure_agent_conversation_scope(
        agent,
        living,
        "group-session",
        "person-1",
    )

    assert agent.shared_conversation is True
    assert (
        agent.memory_scope_id
        == "conversation:feishu:app:demo:chat:group-1"
    )


def test_person_conversation_keeps_person_memory_scope(tmp_path):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    people.store.ensure_person_session("private-session", "person-1")
    living = SimpleNamespace(_people_service=people)
    agent = SimpleNamespace()

    configure_agent_conversation_scope(
        agent,
        living,
        "private-session",
        "person-1",
    )

    assert agent.shared_conversation is False
    assert agent.memory_scope_id == "person-1"


def test_gateway_context_key_preserves_person_continuity_and_desktop_sessions(
    tmp_path,
):
    people = PeopleService(PeopleStore(tmp_path / "brain.db"))
    people.store.ensure_session(
        "group-session",
        "conversation",
        "feishu:app:demo:chat:group-1",
    )
    living = SimpleNamespace(_people_service=people)
    gateway = Gateway(living, SimpleNamespace())

    cli_key = gateway._context_key(
        RawMessage(content="", channel="cli"),
        "cli-xiaomei",
        "person-1",
    )
    feishu_key = gateway._context_key(
        RawMessage(content="", channel="feishu"),
        "feishu-person-1",
        "person-1",
    )
    desktop_a = gateway._context_key(
        RawMessage(content="", channel="ws"),
        "desktop-session-a",
        "person-1",
    )
    desktop_b = gateway._context_key(
        RawMessage(content="", channel="ws"),
        "desktop-session-b",
        "person-1",
    )
    group_key = gateway._context_key(
        RawMessage(content="", channel="feishu"),
        "group-session",
        "person-1",
    )

    assert cli_key == feishu_key == "person:person-1"
    assert desktop_a == "session:desktop-session-a"
    assert desktop_b == "session:desktop-session-b"
    assert group_key == "conversation:feishu:app:demo:chat:group-1"
