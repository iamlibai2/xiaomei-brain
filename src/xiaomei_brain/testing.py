"""测试工具 — 供插件开发者编写测试。

Usage:
    from xiaomei_brain.testing import create_mock_ctx, assert_tool_registered

    def test_my_plugin():
        ctx = create_mock_ctx(plugin_name="my-plugin")
        from my_plugin.adapter import register
        register(ctx)
        assert_tool_registered(ctx, "my_tool")
"""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import MagicMock


def create_mock_ctx(
    plugin_name: str = "test-plugin",
    config: dict | None = None,
    agent_id: str = "test",
) -> Any:
    """创建模拟的 PluginContext，用于测试 register(ctx) 函数。

    Args:
        plugin_name: 插件名称
        config: 模拟的插件配置（channels.<name>.accounts.default）
        agent_id: 模拟的 agent ID

    Returns:
        Mock PluginContext，所有 register_* 方法都记录调用但不执行真实注册
    """
    from xiaomei_brain.plugin.context import PluginContext, VALID_HOOKS
    from xiaomei_brain.plugin.registry import PluginRegistry, ToolRegistry

    registry = PluginRegistry()
    ctx = PluginContext(
        config=config or {},
        plugin_name=plugin_name,
        agent_id=agent_id,
        registry=registry,
    )

    # 记录注册调用
    ctx._registrations: list[dict] = []

    _orig_register_channel = ctx.register_channel
    _orig_register_tool = ctx.register_tool
    _orig_register_hook = ctx.register_hook
    _orig_register_provider = ctx.register_provider
    _orig_register_speech_provider = ctx.register_speech_provider

    def _track_channel(name, adapter):
        ctx._registrations.append({"type": "channel", "name": name, "adapter": adapter})
        _orig_register_channel(name, adapter)

    def _track_tool(name, schema, handler, toolset="default", check_fn=None, optional=False):
        ctx._registrations.append({"type": "tool", "name": name, "toolset": toolset})
        _orig_register_tool(name, schema, handler, toolset=toolset, check_fn=check_fn, optional=optional)

    def _track_hook(event, callback):
        ctx._registrations.append({"type": "hook", "event": event})
        _orig_register_hook(event, callback)

    def _track_provider(provider):
        provider_id = getattr(provider, "provider_id", "unknown")
        ctx._registrations.append({"type": "provider", "id": provider_id})
        _orig_register_provider(provider)

    def _track_speech_provider(provider):
        name = getattr(provider, "name", "unknown")
        ctx._registrations.append({"type": "speech", "name": name})
        _orig_register_speech_provider(provider)

    ctx.register_channel = _track_channel
    ctx.register_tool = _track_tool
    ctx.register_hook = _track_hook
    ctx.register_provider = _track_provider
    ctx.register_speech_provider = _track_speech_provider

    ctx.registry = registry
    return ctx


def assert_channel_registered(ctx: Any, name: str) -> None:
    """断言频道已注册。

    Args:
        ctx: create_mock_ctx() 返回的上下文
        name: 频道名称（如 "feishu"）

    Raises:
        AssertionError: 频道未注册
    """
    registered = [r["name"] for r in getattr(ctx, "_registrations", []) if r["type"] == "channel"]
    assert name in registered, (
        f"Expected channel '{name}' to be registered, "
        f"got: {registered or 'none'}"
    )


def assert_tool_registered(ctx: Any, name: str, toolset: str | None = None) -> None:
    """断言工具已注册。

    Args:
        ctx: create_mock_ctx() 返回的上下文
        name: 工具名称
        toolset: 可选，检查工具分组

    Raises:
        AssertionError: 工具未注册或 toolset 不匹配
    """
    tools = [r for r in getattr(ctx, "_registrations", []) if r["type"] == "tool" and r["name"] == name]
    assert tools, (
        f"Expected tool '{name}' to be registered, "
        f"got registered tools: {[r['name'] for r in getattr(ctx, '_registrations', []) if r['type'] == 'tool'] or 'none'}"
    )
    if toolset is not None:
        assert tools[0]["toolset"] == toolset, (
            f"Expected tool '{name}' in toolset '{toolset}', "
            f"got '{tools[0]['toolset']}'"
        )


def assert_hook_registered(ctx: Any, event: str) -> None:
    """断言 Hook 已注册。

    Args:
        ctx: create_mock_ctx() 返回的上下文
        event: 钩子事件名（如 "pre_tool_call"）

    Raises:
        AssertionError: Hook 未注册
    """
    hooks = [r for r in getattr(ctx, "_registrations", []) if r["type"] == "hook" and r["event"] == event]
    assert hooks, (
        f"Expected hook '{event}' to be registered, "
        f"got: {[r['event'] for r in getattr(ctx, '_registrations', []) if r['type'] == 'hook'] or 'none'}"
    )


def assert_no_registrations(ctx: Any) -> None:
    """断言没有任何注册（用于测试配置缺失时跳过注册的逻辑）。

    Args:
        ctx: create_mock_ctx() 返回的上下文
    """
    regs = getattr(ctx, "_registrations", [])
    assert not regs, f"Expected no registrations, got: {regs}"


def create_mock_adapter(channel_type: str = "mock") -> Any:
    """创建模拟的 ChannelAdapter，用于独立测试通道逻辑。

    Args:
        channel_type: 通道类型标识

    Returns:
        可用的 mock ChannelAdapter
    """
    adapter = MagicMock()
    adapter.channel_type = channel_type
    adapter.send = MagicMock()
    adapter.setup = MagicMock()
    adapter.shutdown = MagicMock()
    adapter.receive = MagicMock(return_value=None)
    return adapter
