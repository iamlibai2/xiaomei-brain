from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.llm.usage import (
    LLMUsageRecord,
    current_usage_context,
    estimate_input_breakdown,
    scale_input_breakdown,
    usage_context,
)
from xiaomei_brain.llm.usage_store import UsageStore


def _record(**overrides) -> LLMUsageRecord:
    values = {
        "provider": "test-provider",
        "model": "test-model",
        "input_tokens": 100,
        "output_tokens": 40,
        "cached_input_tokens": 10,
        "reasoning_tokens": 5,
        "total_tokens": 140,
        "exact": True,
        "latency_ms": 250.0,
        "person_id": "person-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "category": "conversation",
        "input_breakdown": {
            "messages": 40,
            "system": 30,
            "tools": 20,
            "skills": 5,
            "workspace": 5,
        },
    }
    values.update(overrides)
    return LLMUsageRecord(**values)


def test_usage_context_is_scoped_and_restored():
    assert current_usage_context().session_id == ""
    with usage_context(
        person_id="person-1",
        session_id="session-1",
        turn_id="turn-1",
        category="conversation",
    ):
        current = current_usage_context()
        assert current.person_id == "person-1"
        assert current.session_id == "session-1"
        assert current.turn_id == "turn-1"
        assert current.category == "conversation"
    assert current_usage_context().session_id == ""


def test_input_breakdown_attributes_tools_skills_and_workspace():
    messages = [
        {
            "role": "system",
            "content": (
                "base system\n<available_skills>documents</available_skills>\n"
                "<focused_workspace>客户经营</focused_workspace>"
            ),
        },
        {"role": "user", "content": "生成一份文档"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "function": {"name": "skill_view", "arguments": '{"name":"documents"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "完整 Skill 内容"},
    ]
    tools = [{"type": "function", "function": {"name": "skill_view"}}]
    breakdown = estimate_input_breakdown(messages, tools)
    assert breakdown["messages"] > 0
    assert breakdown["system"] > 0
    assert breakdown["tools"] > 0
    assert breakdown["skills"] > 0
    assert breakdown["workspace"] > 0
    scaled = scale_input_breakdown(breakdown, 1000)
    assert sum(scaled.values()) == 1000


def test_usage_store_aggregates_period_session_and_turn(tmp_path):
    store = UsageStore(tmp_path / "brain.db")
    store.record(_record())
    store.record(_record(
        turn_id="turn-2",
        category="memory",
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
        exact=False,
    ))
    store.record(_record(
        session_id="session-2",
        turn_id="turn-3",
        total_tokens=50,
    ))
    summary = store.summary(session_id="session-1")
    assert summary["periods"]["today"]["total_tokens"] == 220
    assert summary["current_session"]["total_tokens"] == 170
    assert summary["current_session"]["calls"] == 2
    assert {item["turn_id"] for item in summary["turns"]} == {"turn-1", "turn-2"}
    turn_2 = next(item for item in summary["turns"] if item["turn_id"] == "turn-2")
    assert turn_2["estimated_calls"] == 1
    turn_1 = next(item for item in summary["turns"] if item["turn_id"] == "turn-1")
    assert turn_1["tool_input_tokens"] == 20
    assert turn_1["skill_input_tokens"] == 5
    assert {item["category"] for item in summary["categories"]} == {"conversation", "memory"}
    assert summary["periods"]["today"]["tool_input_tokens"] == 60

    page = store.list_records(session_id="session-1", limit=1)
    assert len(page["items"]) == 1
    assert page["has_more"] is True


def test_usage_gateway_methods_require_auth_and_return_summary(tmp_path):
    store = UsageStore(tmp_path / "brain.db")
    store.record(_record())
    router = MethodRouter(living=SimpleNamespace(usage_store=store))

    unauthenticated = router.dispatch("conn-1", "req-1", "usage.summary", {})
    assert "error" in unauthenticated

    router._auth_sessions.add("conn-1")
    response = router.dispatch(
        "conn-1",
        "req-2",
        "usage.summary",
        {"session_id": "session-1"},
    )
    assert response["result"]["usage"]["current_session"]["total_tokens"] == 140


def test_usage_summary_includes_current_context_pressure(tmp_path):
    store = UsageStore(tmp_path / "brain.db")
    store.record(_record())
    pressure = {
        "available": True,
        "session_id": "session-1",
        "message_tokens": 12000,
        "message_count": 24,
        "turn_count": 8,
        "max_tokens": 50000,
        "trigger_tokens": 25000,
        "target_tokens": 17500,
        "pressure_ratio": 0.48,
        "reached": False,
    }
    core = SimpleNamespace(
        get_context_compaction_status=lambda session_id: {
            **pressure,
            "session_id": session_id,
        }
    )
    living = SimpleNamespace(
        usage_store=store,
        agent=SimpleNamespace(_agent=core),
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("conn-1")

    response = router.dispatch(
        "conn-1",
        "req-1",
        "usage.summary",
        {"session_id": "session-1"},
    )

    assert response["result"]["usage"]["context_pressure"] == pressure
