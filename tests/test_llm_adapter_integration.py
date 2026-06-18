"""集成测试：PluginLoader 发现 → ProviderProfile 注册 → LLMClient 构造。"""

import os

import pytest


def test_provider_plugin_discovery_and_registration():
    """验证 boot_plugins 能发现 llm/providers/ 下的 provider 插件。"""
    from xiaomei_brain.plugin.bootstrap import boot_plugins

    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["ZHIPU_API_KEY"] = "test-key"
    os.environ["OPENAI_API_KEY"] = "test-key"

    try:
        registry = boot_plugins(agent_id="test")

        # 检查 provider 是否注册
        deepseek = registry.get_provider("deepseek")
        assert deepseek is not None, "deepseek provider not found"
        assert deepseek.provider_id == "deepseek"
        assert deepseek.base_url == "https://api.deepseek.com/v1"

        zhipu = registry.get_provider("zhipu")
        assert zhipu is not None, "zhipu provider not found"
        assert zhipu.base_url == "https://open.bigmodel.cn/api/paas/v4"

        openai_p = registry.get_provider("openai")
        assert openai_p is not None, "openai provider not found"
        assert openai_p.base_url == "https://api.openai.com/v1"

    finally:
        for k in ["DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "OPENAI_API_KEY"]:
            os.environ.pop(k, None)


def test_llm_client_from_registry():
    """验证 LLMClient 能从 registry 正常构造。"""
    from xiaomei_brain.llm.client import LLMClient
    from xiaomei_brain.plugin.registry import PluginRegistry
    from xiaomei_brain.plugin.context import PluginContext
    from xiaomei_brain.llm.providers.deepseek.adapter import register

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
    from xiaomei_brain.llm.providers.deepseek.adapter import register

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
