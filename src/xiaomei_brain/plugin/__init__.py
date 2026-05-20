"""Plugin: xiaomei-brain 插件框架。

参考 Hermes Agent（NousResearch） + OpenClaw 设计模式。

核心设计：
  - Manifest-First: plugin.yaml 元数据先行，启动前即可校验
  - Registry Pattern: 插件写入，Core 读取，唯一交汇点
  - Capability Contract: 核心定义协议（ABC），插件实现
  - Ownership Boundary: 一个插件拥有完整表面

Usage:
    from xiaomei_brain.plugin import boot_plugins

    registry = boot_plugins(agent_id="xiaomei")
    for name in registry.list_channels():
        adapter = registry.get_channel(name)
        router.register_adapter(name, adapter)
"""

from .manifest import PluginManifest
from .context import PluginContext, VALID_HOOKS
from .registry import PluginRegistry, ToolRegistry, ToolEntry, LoadedPlugin
from .loader import PluginLoader
from .bootstrap import boot_plugins
from .toolsets import (
    CHANNEL_TOOLSETS,
    TOOLSET_DEFINITIONS,
    resolve_toolset,
    get_toolset_for_channel,
)

__all__ = [
    "PluginManifest",
    "PluginContext",
    "VALID_HOOKS",
    "PluginRegistry",
    "ToolRegistry",
    "ToolEntry",
    "LoadedPlugin",
    "PluginLoader",
    "boot_plugins",
    "CHANNEL_TOOLSETS",
    "TOOLSET_DEFINITIONS",
    "resolve_toolset",
    "get_toolset_for_channel",
]
