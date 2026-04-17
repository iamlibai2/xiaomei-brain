"""Tests for LLM client (Volcengine)."""

import pytest
from unittest.mock import Mock, patch

from xiaomei_brain.llm import LLMClient, ChatResponse


@pytest.fixture
def mock_requests():
    """Mock requests library."""
    with patch("xiaomei_brain.llm.requests") as mock:
        yield mock


def test_llm_client_init_volcengine(mock_requests):
    """Test LLM client initialization for Volcengine."""
    client = LLMClient(provider="volcengine", model="doubao-pro-4k", api_key="test-key")
    assert client.provider == "volcengine"
    assert client.model == "doubao-pro-4k"


def test_llm_chat_response(mock_requests):
    """Test LLM chat returns parsed response."""
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

    client = LLMClient(provider="volcengine", model="doubao-pro-4k", api_key="test-key")
    response = client.chat(messages=[{"role": "user", "content": "Hi"}])

    assert isinstance(response, ChatResponse)
    assert response.content == "Hello!"
    assert not response.has_tool_calls


def test_llm_chat_with_tools(mock_requests):
    """Test LLM chat with tool calls."""
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

    client = LLMClient(provider="volcengine", model="doubao-pro-4k", api_key="test-key")
    response = client.chat(
        messages=[{"role": "user", "content": "What is 5 + 3?"}],
        tools=[{"type": "function", "function": {"name": "calculator"}}],
    )

    assert response.has_tool_calls
    assert response.tool_calls[0].name == "calculator"
    assert response.tool_calls[0].arguments == {"x": 5, "y": 3}
