"""AnthropicMessagesTransport 单元测试 — mock requests 验证协议格式。"""
import pytest
from xiaomei_brain.llm.transport.anthropic_messages import AnthropicMessagesTransport
from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile


@pytest.fixture
def transport():
    return AnthropicMessagesTransport()


@pytest.fixture
def model():
    return ModelDefinition(id="claude-sonnet-4-6", name="Claude Sonnet 4.6",
                           context_window=200000, max_tokens=8192)


@pytest.fixture
def profile():
    return ProviderProfile(
        provider_id="anthropic",
        name="Anthropic",
        api_mode="anthropic-messages",
        base_url="https://api.anthropic.com",
    )


class TestEndpointAndHeaders:
    def test_endpoint(self, transport):
        assert transport.get_endpoint("https://api.anthropic.com") == "https://api.anthropic.com/messages"

    def test_headers(self, transport):
        h = transport.get_headers("sk-ant-test")
        assert h["x-api-key"] == "sk-ant-test"
        assert h["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in h


class TestConvertMessages:
    def test_system_extracted(self, transport, model, profile):
        msgs = [{"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"}]
        result = transport.convert_messages(msgs, model, profile)
        # system 消息保留 role="system"，由 build_kwargs 提取
        assert result[0]["role"] == "system"
        # user 消息 content 转为 block 数组
        assert result[1]["role"] == "user"
        assert result[1]["content"] == [{"type": "text", "text": "Hi"}]

    def test_tool_calls_to_tool_use_blocks(self, transport, model, profile):
        msgs = [{"role": "assistant", "content": None,
                 "tool_calls": [{"id": "tc1", "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'}}]}]
        result = transport.convert_messages(msgs, model, profile)
        blocks = result[0]["content"]
        tool_use = [b for b in blocks if b["type"] == "tool_use"]
        assert len(tool_use) == 1
        assert tool_use[0]["name"] == "get_weather"
        assert tool_use[0]["input"] == {"city": "NYC"}

    def test_tool_result_block(self, transport, model, profile):
        msgs = [{"role": "tool", "content": "Sunny, 22C", "tool_call_id": "tc1"}]
        result = transport.convert_messages(msgs, model, profile)
        assert result[0]["content"] == [{"type": "tool_result", "tool_use_id": "tc1", "content": "Sunny, 22C"}]


class TestConvertTools:
    def test_openai_to_anthropic_format(self, transport, model, profile):
        tools = [{"type": "function",
                  "function": {"name": "get_weather",
                               "description": "Get weather",
                               "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]
        result = transport.convert_tools(tools, model, profile)
        assert result[0]["name"] == "get_weather"
        assert result[0]["input_schema"]["properties"]["city"]["type"] == "string"
        assert "function" not in result[0]


class TestBuildKwargs:
    def test_system_as_top_level(self, transport, model, profile):
        msgs = [{"role": "system", "content": "You are helpful."},
                {"role": "user", "content": [{"type": "text", "text": "Hi"}]}]
        kw = transport.build_kwargs(msgs, None, model, profile, stream=False)
        assert kw["system"] == "You are helpful."
        assert len(kw["messages"]) == 1  # system 不在 messages 中
        assert kw["messages"][0]["role"] == "user"

    def test_stream_param(self, transport, model, profile):
        kw = transport.build_kwargs([], None, model, profile, stream=True)
        assert kw["stream"] is True

    def test_tools_included(self, transport, model, profile):
        tools = [{"name": "foo", "description": "bar", "input_schema": {}}]
        kw = transport.build_kwargs([], tools, model, profile, stream=False)
        assert kw["tools"] == tools


class TestNormalizeResponse:
    def test_text_response(self, transport, model, profile):
        raw = {"content": [{"type": "text", "text": "Hello!"}],
               "stop_reason": "end_turn",
               "usage": {"input_tokens": 10, "output_tokens": 5}}
        resp = transport.normalize_response(raw, model, profile)
        assert resp.content == "Hello!"
        assert resp.finish_reason == "end_turn"
        assert resp.usage == {"input_tokens": 10, "output_tokens": 5}

    def test_tool_use_response(self, transport, model, profile):
        raw = {"content": [{"type": "tool_use", "id": "tc1", "name": "get_weather",
                            "input": {"city": "NYC"}}],
               "stop_reason": "tool_use"}
        resp = transport.normalize_response(raw, model, profile)
        assert resp.content is None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_weather"


class TestStreamIter:
    def test_text_delta(self, transport, model, profile):
        """模拟 Anthropic SSE 流"""
        from unittest.mock import Mock
        response = Mock()
        lines = [
            b"event: message_start",
            b"data: {}",
            b"",
            b"event: content_block_start",
            b'data: {"index":0, "content_block":{"type":"text","text":""}}',
            b"",
            b"event: content_block_delta",
            b'data: {"index":0, "delta":{"type":"text_delta","text":"Hello"}}',
            b"",
            b"event: content_block_delta",
            b'data: {"index":0, "delta":{"type":"text_delta","text":" world"}}',
            b"",
            b"event: message_delta",
            b'data: {"delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":5,"output_tokens":3}}',
            b"",
            b"event: message_stop",
            b"data: {}",
        ]
        response.iter_lines.return_value = lines

        outputs = list(transport.stream_iter(response, model, profile))
        texts = [t for t, extra in outputs if t and not extra]
        assert "".join(texts) == "Hello world"

        # 最后一个元素有 extra_info
        last_extra = outputs[-1][1]
        assert last_extra is not None
        assert last_extra["finish_reason"] == "end_turn"
