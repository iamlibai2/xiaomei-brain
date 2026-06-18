"""Tests for LLM client."""

import json
import pytest
from unittest.mock import Mock, patch

from xiaomei_brain.llm.client import LLMClient
from xiaomei_brain.llm.types import NormalizedResponse, ProviderProfile, ModelDefinition
from xiaomei_brain.plugin.registry import PluginRegistry


@pytest.fixture
def registry():
    """Create a PluginRegistry with a test provider."""
    reg = PluginRegistry()
    reg.register_provider("test-provider", ProviderProfile(
        provider_id="test-provider",
        name="Test Provider",
        base_url="https://test.api.example.com/v1",
        env_vars=("TEST_API_KEY",),
        models=[
            ModelDefinition(id="test-model", name="Test Model",
                            context_window=4096, max_tokens=1024),
        ],
    ))
    return reg


@pytest.fixture
def mock_requests():
    """Mock requests library."""
    with patch("xiaomei_brain.llm.client.requests") as mock:
        yield mock


def test_llm_client_init(registry, mock_requests):
    """Test LLM client initialization from registry."""
    import os
    os.environ["TEST_API_KEY"] = "test-key"
    try:
        client = LLMClient(provider="test-provider", model="test-model", registry=registry)
        assert client.provider == "test-provider"
        assert client.model == "test-model"
    finally:
        os.environ.pop("TEST_API_KEY", None)


def test_llm_chat_response(registry, mock_requests):
    """Test LLM chat returns normalized response."""
    import os
    os.environ["TEST_API_KEY"] = "test-key"
    try:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Hello!", "role": "assistant"},
                    "finish_reason": "stop",
                }
            ]
        }
        mock_requests.post.return_value = mock_response

        client = LLMClient(provider="test-provider", model="test-model", registry=registry)
        response = client.chat(messages=[{"role": "user", "content": "Hi"}])

        assert isinstance(response, NormalizedResponse)
        assert response.content == "Hello!"
        assert not response.tool_calls
    finally:
        os.environ.pop("TEST_API_KEY", None)


def test_llm_chat_with_tools(registry, mock_requests):
    """Test LLM chat with tool calls."""
    import os
    os.environ["TEST_API_KEY"] = "test-key"
    try:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-123",
                                "type": "function",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"x": 5, "y": 3}',
                                },
                            }
                        ],
                        "role": "assistant",
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        mock_requests.post.return_value = mock_response

        client = LLMClient(provider="test-provider", model="test-model", registry=registry)
        response = client.chat(
            messages=[{"role": "user", "content": "What is 5 + 3?"}],
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        )

        assert response.tool_calls
        assert response.tool_calls[0].name == "calculator"
        # arguments is str in new API
        assert json.loads(response.tool_calls[0].arguments) == {"x": 5, "y": 3}
    finally:
        os.environ.pop("TEST_API_KEY", None)
