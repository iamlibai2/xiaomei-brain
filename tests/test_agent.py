"""Tests for the Agent class."""

import json

import pytest
from unittest.mock import Mock

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.llm.types import NormalizedResponse, ToolCall
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.registry import TOOL_CONTROL_KEY


def _chat(agent: Agent, user_input: str) -> str:
    """Helper: send a user message through Agent.stream() and collect output."""
    messages = [{"role": "user", "content": user_input}]
    return "".join(agent.stream(messages))


def _setup_mock_llm(mock_llm, content: str = "Hello!"):
    """Configure mock LLM to return a streaming text response."""
    mock_llm.chat_stream.return_value = (_ for _ in [content])
    mock_llm._last_stream_response = NormalizedResponse(
        content=content, finish_reason="stop"
    )
    mock_llm._reasoning_end_yielded = False


@pytest.fixture
def mock_llm():
    return Mock()


@pytest.fixture
def registry():
    return ToolRegistry()


def test_agent_simple_response(mock_llm, registry):
    """Agent.stream() returns LLM response text."""
    agent = Agent(llm=mock_llm, tools=registry, system_prompt="Test")

    _setup_mock_llm(mock_llm, "Hello!")
    response = _chat(agent, "Hi")

    assert response == "Hello!"


def test_agent_reset(mock_llm, registry):
    """Clearing _messages resets conversation state."""
    agent = Agent(llm=mock_llm, tools=registry)

    _setup_mock_llm(mock_llm, "Hi")
    _chat(agent, "Hello")
    assert len(agent.messages) > 0

    agent._messages = {}
    assert len(agent.messages) == 0


def test_agent_max_steps(mock_llm, registry):
    """Agent stops after max_steps when LLM keeps returning tool_calls."""
    agent = Agent(llm=mock_llm, tools=registry, max_steps=3)

    # Mock LLM that always returns a tool call
    tc = ToolCall(id="t1", name="echo", arguments="{}")
    resp = NormalizedResponse(content="", tool_calls=[tc], finish_reason="tool_calls")

    mock_llm.chat_stream.return_value = (_ for _ in ["thinking..."])
    mock_llm._last_stream_response = resp
    mock_llm._reasoning_end_yielded = False

    response = _chat(agent, "Run tool")
    # After max_steps, stream() stops without final answer
    assert isinstance(response, str)


def test_execute_tool_call_accepts_structured_result(mock_llm, registry):
    """Structured tool output must not crash failure classification."""
    from xiaomei_brain.tools import tool

    @tool(name="look_around", description="Inspect the current scene")
    def look_around() -> dict:
        return {"faces": [], "scene": "办公室"}

    registry.register(look_around)
    agent = Agent(llm=mock_llm, tools=registry)

    result = agent._execute_tool_call("call-1", "look_around", {})

    assert result == '{"faces": [], "scene": "办公室"}'


def test_structured_tool_error_marks_action_failed(mock_llm, registry):
    """An error object should complete an approved action as failed."""
    from xiaomei_brain.tools import tool

    @tool(name="look_around", description="Inspect the current scene")
    def look_around() -> dict:
        return {"error": "眼睛不可用"}

    registry.register(look_around)
    agent = Agent(llm=mock_llm, tools=registry)
    agent.on_tool_approval = Mock(
        return_value={"approved": True, "action_id": "action-1"}
    )
    agent.on_action_complete = Mock()

    result = agent._execute_tool_call("call-1", "look_around", {})

    assert result == '{"error": "眼睛不可用"}'
    agent.on_action_complete.assert_called_once_with("action-1", result, True)


def test_document_output_is_auto_presented_when_model_omits_delivery(
    mock_llm,
    registry,
    tmp_path,
):
    """A successful stable document write has a turn-end delivery guarantee."""
    from xiaomei_brain.tools import tool

    output_path = str(tmp_path / "quote.xlsx")
    calls = []

    @tool(name="present_artifacts", description="Present final files")
    def present_artifacts(paths: list[str], message: str = "") -> dict:
        calls.append((paths, message))
        return {
            "type": "present_artifacts_result",
            "path": paths,
            "delivered": True,
        }

    registry.register(present_artifacts)
    agent = Agent(llm=mock_llm, tools=registry)
    agent.turn_id = "turn-1"
    agent.on_artifact = Mock()
    pending = {}
    presented = set()
    agent._track_document_delivery(
        "write_document",
        json.dumps({
            "success": True,
            "format": "spreadsheet",
            "output_path": output_path,
        }),
        pending,
        presented,
    )

    agent._auto_present_document_outputs(pending, presented)

    assert calls == [([output_path], "本轮生成的文档已自动交付。")]
    assert agent._normalized_delivery_path(output_path) in presented
    agent.on_artifact.assert_called_once()
    assert agent.on_artifact.call_args.args[1] == "present_artifacts"


def test_explicit_document_presentation_prevents_auto_duplicate(
    mock_llm,
    registry,
    tmp_path,
):
    output_path = str(tmp_path / "quote.xlsx")
    agent = Agent(llm=mock_llm, tools=registry)
    agent.on_artifact = Mock()
    pending = {}
    presented = set()
    agent._track_document_delivery(
        "write_document",
        json.dumps({"success": True, "output_path": output_path}),
        pending,
        presented,
    )
    agent._track_document_delivery(
        "present_artifacts",
        json.dumps({"path": [output_path], "delivered": True}),
        pending,
        presented,
    )

    agent._auto_present_document_outputs(pending, presented)

    agent.on_artifact.assert_not_called()


def test_tool_handoff_stops_live_react_loop(mock_llm, registry):
    """A background handoff must not let the live model continue working."""
    from xiaomei_brain.tools import tool

    @tool(name="delegate", description="Transfer work to a background runner")
    def delegate() -> dict:
        return {
            "id": "assignment_1",
            "status": "queued",
            TOOL_CONTROL_KEY: {
                "type": "handoff",
                "message": "已转入后台执行。",
            },
        }

    registry.register(delegate)
    agent = Agent(llm=mock_llm, tools=registry, max_steps=5)
    tool_call = ToolCall(id="call-1", name="delegate", arguments="{}")
    mock_llm.chat_stream.return_value = iter(())
    mock_llm._last_stream_response = NormalizedResponse(
        content="",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
    )
    mock_llm._reasoning_end_yielded = False

    response = _chat(agent, "请接下这个持续任务")

    assert response == "已转入后台执行。"
    assert mock_llm.chat_stream.call_count == 1
    tool_messages = [item for item in agent.messages if item["role"] == "tool"]
    assert tool_messages == [{
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"id": "assignment_1", "status": "queued"}',
        "id": None,
    }]
    assert agent.messages[-1]["content"] == "已转入后台执行。"
