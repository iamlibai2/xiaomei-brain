"""Regression tests for Agent DAG compaction boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.tools.registry import ToolRegistry


class _FakeDag:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages
        self.compacted: list[dict] = []

    def get_unsummarized_messages(self, _session_id: str, limit: int = 100) -> list[dict]:
        return self.messages[:limit]

    def compact(self, _session_id, _message_ids, messages, user_id=None):
        self.compacted = list(messages)
        return SimpleNamespace(id=1, depth=0, content="summary")


def _agent_with_messages(messages: list[dict]) -> tuple[Agent, _FakeDag]:
    agent = Agent(llm=Mock(), tools=ToolRegistry())
    dag = _FakeDag(messages)
    agent.dag = dag
    agent._living_cfg = SimpleNamespace(
        context=SimpleNamespace(
            messages_per_compact=8,
            reserved_fresh_count=10,
            compact_token_ratio=0.5,
        )
    )
    return agent, dag


def _messages(count: int, content_size: int = 10) -> list[dict]:
    return [
        {"id": str(index), "role": "user", "content": "x" * content_size}
        for index in range(count)
    ]


def test_token_trigger_never_compacts_within_reserved_fresh_tail():
    agent, dag = _agent_with_messages(_messages(4, content_size=3000))

    result = agent._auto_compact("session", max_tokens=4000)

    assert result is None
    assert dag.compacted == []


def test_token_trigger_only_compacts_messages_before_reserved_fresh_tail():
    agent, dag = _agent_with_messages(_messages(14, content_size=1000))

    result = agent._auto_compact("session", max_tokens=4000)

    assert result is not None
    assert len(dag.compacted) == 4
    assert result["remaining_count"] == 10


def test_count_trigger_compacts_batch_and_keeps_reserved_fresh_tail():
    agent, dag = _agent_with_messages(_messages(18))

    result = agent._auto_compact("session", max_tokens=50000)

    assert result is not None
    assert len(dag.compacted) == 8
    assert result["remaining_count"] == 10
