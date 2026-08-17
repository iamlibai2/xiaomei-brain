"""Regression tests for token- and Turn-aware DAG compaction."""

import threading
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from xiaomei_brain.agent.context_compactor import ContextCompactor
from xiaomei_brain.agent.core import Agent
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.tools.registry import ToolRegistry


class _FakeDag:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages
        self.compacted: list[dict] = []

    def get_unsummarized_messages(self, _session_id: str, limit: int = 2000) -> list[dict]:
        return self.messages[:limit]

    def compact(self, _session_id, _message_ids, messages, user_id=None):
        self.compacted = list(messages)
        return SimpleNamespace(id=1, depth=0, content="summary")


def _agent_with_messages(messages: list[dict]) -> tuple[Agent, _FakeDag]:
    agent = Agent(llm=Mock(), tools=ToolRegistry())
    dag = _FakeDag(messages)
    agent.dag = dag
    agent._living_cfg = SimpleNamespace(
        living=SimpleNamespace(max_context_tokens=4000),
        context=SimpleNamespace(
            compact_token_ratio=0.5,
            compact_target_ratio=0.35,
        )
    )
    return agent, dag


def _message(
    message_id: int,
    role: str,
    content: str,
    turn_id: str,
    **extra,
) -> dict:
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "metadata": {"turn_id": turn_id},
        **extra,
    }


def test_tool_heavy_turn_is_compacted_as_one_unit():
    messages = [_message(1, "user", "build report", "turn-1")]
    for index in range(10):
        call_id = f"call-{index}"
        messages.extend([
            _message(
                index * 2 + 2,
                "assistant",
                "",
                "turn-1",
                tool_calls=[{"id": call_id, "function": {"name": "read", "arguments": "{}"}}],
            ),
            _message(
                index * 2 + 3,
                "tool",
                "x" * 1000,
                "turn-1",
                tool_call_id=call_id,
                tool_name="read",
            ),
        ])
    messages.append(_message(22, "assistant", "report delivered", "turn-1"))
    messages.append(_message(23, "user", "new request", "turn-2"))

    plan = ContextCompactor().plan_compaction(
        messages,
        max_tokens=4000,
        trigger_ratio=0.5,
        target_ratio=0.35,
        active_turn_id="turn-2",
    )

    assert plan is not None
    assert plan.turn_count == 1
    assert [item["id"] for item in plan.messages] == list(range(1, 23))


def test_active_turn_is_never_compacted_even_when_large():
    messages = [
        _message(1, "user", "x" * 12000, "active"),
        _message(2, "assistant", "working", "active"),
    ]

    plan = ContextCompactor().plan_compaction(
        messages,
        max_tokens=4000,
        trigger_ratio=0.5,
        target_ratio=0.35,
        active_turn_id="active",
    )

    assert plan is None


def test_small_turns_do_not_compact_merely_because_there_are_many_messages():
    messages: list[dict] = []
    message_id = 1
    for index in range(20):
        turn_id = f"turn-{index}"
        messages.append(_message(message_id, "user", "hi", turn_id))
        message_id += 1
        messages.append(_message(message_id, "assistant", "hello", turn_id))
        message_id += 1

    plan = ContextCompactor().plan_compaction(
        messages,
        max_tokens=50000,
        trigger_ratio=0.5,
        target_ratio=0.35,
    )

    assert plan is None


def test_trim_to_budget_keeps_complete_newest_turns():
    messages = [
        _message(1, "user", "a" * 2000, "turn-1"),
        _message(2, "assistant", "b" * 2000, "turn-1"),
        _message(3, "user", "c" * 1200, "turn-2"),
        _message(4, "assistant", "d" * 1200, "turn-2"),
        _message(5, "user", "current", "turn-3"),
    ]

    trimmed = ContextCompactor().trim_to_budget(
        messages,
        token_budget=800,
        active_turn_id="turn-3",
    )

    assert [item["id"] for item in trimmed] == [3, 4, 5]


def test_legacy_messages_use_user_boundaries_without_splitting_tools():
    messages = [
        {"id": 1, "role": "user", "content": "first"},
        {"id": 2, "role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"id": 3, "role": "tool", "content": "result", "tool_call_id": "c1"},
        {"id": 4, "role": "assistant", "content": "done"},
        {"id": 5, "role": "user", "content": "second"},
    ]

    turns = ContextCompactor().split_turns(messages)

    assert [[item["id"] for item in turn.messages] for turn in turns] == [
        [1, 2, 3, 4],
        [5],
    ]
    assert turns[0].complete is True
    assert turns[1].complete is False


def test_persisted_steer_is_grouped_with_the_active_turn():
    messages = [
        _message(1, "user", "start", "turn-1"),
        _message(2, "assistant", "", "turn-1", tool_calls=[{"id": "c1"}]),
        {
            "id": 3,
            "role": "user",
            "content": "also make it blue",
            "metadata": {
                "turn_id": "turn-2",
                "steered_into_turn_id": "turn-1",
            },
        },
        _message(4, "tool", "done", "turn-1", tool_call_id="c1"),
        _message(5, "assistant", "finished", "turn-1"),
    ]

    turns = ContextCompactor().split_turns(messages)

    assert len(turns) == 1
    assert [item["id"] for item in turns[0].messages] == [1, 2, 3, 4, 5]


def test_agent_delegates_compaction_plan_to_dag():
    messages = [
        _message(1, "user", "x" * 10000, "turn-1"),
        _message(2, "assistant", "done", "turn-1"),
        _message(3, "user", "next", "turn-2"),
    ]
    agent, dag = _agent_with_messages(messages)
    agent.turn_id = "turn-2"

    result = agent._auto_compact("session", max_tokens=4000)

    assert result is not None
    assert result["compact_turn_count"] == 1
    assert [item["id"] for item in dag.compacted] == [1, 2]


def test_foreground_compaction_waits_for_existing_session_job():
    messages = [
        _message(1, "user", "x" * 10000, "turn-1"),
        _message(2, "assistant", "done", "turn-1"),
        _message(3, "user", "不错", "turn-2"),
    ]
    agent, dag = _agent_with_messages(messages)
    agent.turn_id = "turn-2"

    session_lock = threading.Lock()
    session_lock.acquire()
    agent._compact_locks["session"] = session_lock
    completed = threading.Event()

    def run_compaction():
        agent._auto_compact(
            "session",
            max_tokens=4000,
            wait_for_existing=True,
        )
        completed.set()

    worker = threading.Thread(target=run_compaction)
    worker.start()
    time.sleep(0.05)
    assert completed.is_set() is False

    session_lock.release()
    worker.join(timeout=1)

    assert completed.is_set() is True
    assert [item["id"] for item in dag.compacted] == [1, 2]


def test_context_status_uses_same_tokens_and_threshold_as_compaction():
    messages = [
        _message(1, "user", "x" * 10000, "turn-1"),
        _message(2, "assistant", "done", "turn-1"),
        _message(3, "user", "next", "turn-2"),
    ]
    agent, _dag = _agent_with_messages(messages)
    agent.session_id = "session"
    agent.turn_id = "turn-2"

    status = agent.get_context_compaction_status("session")
    plan = agent.context_compactor.plan_compaction(
        messages,
        max_tokens=4000,
        trigger_ratio=0.5,
        target_ratio=0.35,
        active_turn_id="turn-2",
    )

    assert plan is not None
    assert status["available"] is True
    assert status["message_tokens"] == plan.before_tokens
    assert status["message_count"] == 3
    assert status["turn_count"] == 2
    assert status["trigger_tokens"] == 2000
    assert status["target_tokens"] == 1400
    assert status["reached"] is True


def test_dag_summary_input_contains_tool_arguments_and_result_facts():
    dag = object.__new__(DAGSummaryGraph)
    formatted = dag._format_messages_for_summary([
        _message(
            1,
            "assistant",
            "",
            "turn-1",
            tool_calls=[{
                "id": "call-1",
                "function": {
                    "name": "write_document",
                    "arguments": '{"path":"report.docx"}',
                },
            }],
        ),
        _message(
            2,
            "tool",
            "created report.docx",
            "turn-1",
            tool_call_id="call-1",
            tool_name="write_document",
        ),
    ])

    assert "write_document" in formatted
    assert "report.docx" in formatted
    assert "created report.docx" in formatted


def test_dag_summary_input_preserves_source_message_time():
    dag = object.__new__(DAGSummaryGraph)
    formatted = dag._format_messages_for_summary([
        _message(
            1,
            "user",
            "记住这件事",
            "turn-1",
            created_at=datetime(2026, 8, 17, 16, 12, 40).timestamp(),
        ),
    ])

    assert "2026-08-17 16:12:40" in formatted
    assert "记住这件事" in formatted
