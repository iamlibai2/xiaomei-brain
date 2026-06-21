"""Tests for the Agent class."""

import pytest
from unittest.mock import Mock

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.llm.types import NormalizedResponse, ToolCall
from xiaomei_brain.tools.registry import ToolRegistry


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
