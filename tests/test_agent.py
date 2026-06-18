"""Tests for the Agent class."""

import pytest

from xiaomei_brain import Agent, ToolRegistry
from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition
from xiaomei_brain.plugin.registry import PluginRegistry
from unittest.mock import Mock, patch


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    import os
    os.environ["TEST_API_KEY"] = "test-key"
    reg = PluginRegistry()
    reg.register_provider("test-provider", ProviderProfile(
        provider_id="test-provider",
        name="Test",
        base_url="https://test.example.com/v1",
        env_vars=("TEST_API_KEY",),
        models=[ModelDefinition(id="test-model", name="Test", context_window=4096, max_tokens=1024)],
    ))
    with patch("xiaomei_brain.llm.client.requests") as mock_req:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": "Hello!", "role": "assistant"},
                "finish_reason": "stop",
            }]
        }
        mock_req.post.return_value = mock_resp
        yield LLMClient(provider="test-provider", model="test-model", registry=reg)
    os.environ.pop("TEST_API_KEY", None)


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
