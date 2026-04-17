"""Tests for the Agent class."""

import pytest

from xiaomei_brain import Agent, ToolRegistry
from xiaomei_brain.llm import LLMClient
from unittest.mock import Mock, patch


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    with patch("xiaomei_brain.llm.OpenAI") as mock:
        mock.return_value.chat.completions.create.return_value.choices = [
            Mock(message=Mock(content="Hello!", tool_calls=None), finish_reason="stop")
        ]
        yield LLMClient(model="gpt-4o", api_key="test-key")


@pytest.fixture
def registry():
    """Create empty tool registry."""
    return ToolRegistry()


def test_agent_simple_response(mock_llm, registry):
    """Test agent returns LLM response when no tools are called."""
    agent = Agent(llm=mock_llm, tools=registry)
    response = agent.run("Hello")
    assert response == "Hello!"


def test_agent_reset(mock_llm, registry):
    """Test agent clears conversation history after reset."""
    agent = Agent(llm=mock_llm, tools=registry)
    agent.run("Hello")
    assert len(agent.messages) > 0
    agent.reset()
    assert len(agent.messages) == 0


def test_agent_max_steps(mock_llm, registry):
    """Test agent stops after max steps."""
    agent = Agent(llm=mock_llm, tools=registry, max_steps=3)
    response = agent.run("Hello")
    assert response == "Agent reached maximum steps without producing a final answer."
