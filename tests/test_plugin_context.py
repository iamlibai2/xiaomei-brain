from pathlib import Path

from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.plugin.registry import PluginRegistry


def test_agent_dir_uses_platform_native_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    context = PluginContext(
        config={},
        plugin_name="test-plugin",
        agent_id="xiaomei",
        registry=object(),
    )

    assert context.agent_dir == str(tmp_path / ".xiaomei-brain" / "xiaomei")


def test_channel_plugin_registers_runtime_factory():
    registry = PluginRegistry()
    context = PluginContext({}, "channel-plugin", "xiaomei", registry)
    factory = lambda config: {"config": config}

    context.register_channel_factory("example", factory)

    assert registry.get_channel_factory("example") is factory


def test_plugin_registers_managed_runtime_factory():
    registry = PluginRegistry()
    context = PluginContext({}, "runtime-plugin", "xiaomei", registry)
    factory = lambda **dependencies: dependencies

    context.register_runtime("example", factory)

    assert registry.get_runtime_factories() == {"example": factory}
