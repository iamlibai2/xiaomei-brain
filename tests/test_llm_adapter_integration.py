"""集成测试：PluginLoader 发现 → ProviderProfile 注册 → LLMClient 构造。"""

import os

import pytest


def deepseek_profile_and_model(*, reasoning=True):
    from xiaomei_brain.llm.types import (
        ModelDefinition,
        ProviderProfile,
        resolve_provider_thinking_mapping,
        resolve_thinking_capabilities,
    )

    thinking_format, effort_map = resolve_provider_thinking_mapping("deepseek")
    capabilities = resolve_thinking_capabilities(
        "deepseek",
        "deepseek-v4-pro",
        reasoning=reasoning,
    )
    return (
        ProviderProfile(
            provider_id="deepseek",
            name="DeepSeek",
            base_url="https://api.deepseek.com",
            thinking_format=thinking_format,
            thinking_effort_map=effort_map,
        ),
        ModelDefinition(
            id="deepseek-v4-pro",
            name="DeepSeek V4 Pro",
            context_window=128000,
            max_tokens=8192,
            reasoning=reasoning,
            **capabilities,
        ),
    )


def test_provider_plugin_discovery_and_registration():
    """验证 boot_plugins 能发现专用 LLM provider 插件。"""
    from xiaomei_brain.plugin.bootstrap import boot_plugins

    os.environ["DEEPSEEK_API_KEY"] = "test-key"

    try:
        registry = boot_plugins(agent_id="test")

        # 检查 provider 是否注册
        deepseek = registry.get_provider("deepseek")
        assert deepseek is not None, "deepseek provider not found"
        assert deepseek.provider_id == "deepseek"
        assert deepseek.base_url == "https://api.deepseek.com/v1"

        anthropic = registry.get_provider("anthropic")
        assert anthropic is not None, "anthropic provider not found"
        assert anthropic.api_mode == "anthropic-messages"

    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_llm_client_from_registry():
    """验证 LLMClient 能从 registry 正常构造。"""
    from xiaomei_brain.llm.client import LLMClient
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugin.context import PluginContext
    from xiaomei_brain.plugins.providers.deepseek.adapter import register

    reg = PluginRegistry()
    ctx = PluginContext(config={}, plugin_name="deepseek", agent_id="test", registry=reg)
    register(ctx)

    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    try:
        client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=reg)
        assert client.provider == "deepseek"
        assert client.model == "deepseek-v4-flash"
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


def test_provider_from_config_merge():
    """验证 config.json provider 合并逻辑。"""
    from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, load_config_providers
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugin.context import PluginContext
    from xiaomei_brain.plugins.providers.deepseek.adapter import register

    reg = PluginRegistry()
    ctx = PluginContext(config={}, plugin_name="deepseek", agent_id="test", registry=reg)
    register(ctx)

    # 模拟 config.json 覆盖 base_url
    config = {
        "models": {
            "providers": {
                "deepseek": {
                    "baseUrl": "https://my-proxy.example.com/v1",
                }
            }
        }
    }
    load_config_providers(reg, config)

    p = reg.get_provider("deepseek")
    assert p.base_url == "https://my-proxy.example.com/v1"  # config 覆盖
    # models 应保留（config 未设置 models）
    assert p.resolve_model("deepseek-v4-flash") is not None


def test_deepseek_thinking_payload_and_reasoning_round_trip():
    """只有工具调用轮次回传完整 reasoning_content。"""
    from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport

    profile, model = deepseek_profile_and_model()
    transport = ChatCompletionsTransport()
    messages = transport.convert_messages([
        {
            "role": "assistant",
            "content": "普通回答",
            "reasoning_content": "普通回答的历史思考",
        },
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "需要完整回传的工具思考",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
    ], model, profile, thinking={"enabled": True, "effort": "medium"})

    assert "reasoning_content" not in messages[0]
    assert messages[1]["reasoning_content"] == "需要完整回传的工具思考"

    payload = transport.build_kwargs(
        messages,
        None,
        model,
        profile,
        stream=False,
        thinking={"enabled": True, "effort": "medium"},
    )
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_deepseek_drops_incomplete_historical_tool_turn():
    """缺少完整思考的旧工具调用组不能用空格伪造。"""
    from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport

    profile, model = deepseek_profile_and_model()
    messages = ChatCompletionsTransport().convert_messages([
        {"role": "user", "content": "旧问题"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "old-call",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "old-call", "content": "旧结果"},
        {"role": "user", "content": "新问题"},
    ], model, profile, thinking={"enabled": True, "effort": "default"})

    assert messages == [
        {"role": "user", "content": "旧问题"},
        {"role": "user", "content": "新问题"},
    ]


def test_deepseek_non_reasoning_explicitly_disables_thinking():
    from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport

    profile, model = deepseek_profile_and_model(reasoning=False)
    payload = ChatCompletionsTransport().build_kwargs(
        [],
        None,
        model,
        profile,
        stream=False,
        thinking={"enabled": False, "effort": "default"},
    )

    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_anthropic_register_creates_fresh_profile():
    from xiaomei_brain.plugin.context import PluginContext
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugins.providers.anthropic.adapter import register

    first_registry = PluginRegistry()
    second_registry = PluginRegistry()
    register(PluginContext({}, "anthropic", "first", first_registry))
    register(PluginContext({}, "anthropic", "second", second_registry))

    first = first_registry.get_provider("anthropic")
    second = second_registry.get_provider("anthropic")
    assert first is not second
    first.base_url = "https://proxy.example.com"
    assert second.base_url == "https://api.anthropic.com"


def test_normalized_response_and_tool_call():
    """验证 NormalizedResponse 和 ToolCall 数据结构。"""
    from xiaomei_brain.llm.types import NormalizedResponse, ToolCall

    tc = ToolCall(id="1", name="test_tool", arguments='{"key": "value"}')
    resp = NormalizedResponse(
        content="Hello",
        tool_calls=[tc],
        finish_reason="stop",
    )
    assert resp.content == "Hello"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "test_tool"


def test_model_definition_per_model_capabilities():
    """验证 per-model 能力字段覆盖逻辑。"""
    from xiaomei_brain.llm.types import ModelDefinition

    m = ModelDefinition(id="test", name="Test", context_window=4096, max_tokens=1024,
                        supports_vision=True, supports_tools=False)
    assert m.supports_vision is True
    assert m.supports_tools is False
    assert m.supports_developer_role is None  # 未设置 → 沿用 transport 默认
