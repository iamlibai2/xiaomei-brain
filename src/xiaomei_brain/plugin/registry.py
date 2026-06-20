"""PluginRegistry: 中央注册表。

插件写入，Core 读取。Registry 是唯一的交汇点。
包含 ToolRegistry（AST 自发现 + Toolset 分组 + check_fn）。
"""

from __future__ import annotations

import asyncio
import ast
import importlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)


# ── ToolEntry ────────────────────────────────────────────────────

@dataclass
class ToolEntry:
    """单个工具的注册信息。"""

    name: str
    schema: dict                     # OpenAI 兼容 JSON function 定义
    handler: Callable                # handler(args: dict) -> str
    toolset: str = "default"         # 工具分组
    check_fn: Callable[[], bool] | None = None  # 运行时可用性检查
    optional: bool = False           # 是否可选
    _check_cache: tuple[float, bool] | None = field(default=None, repr=False, init=False)

    _CHECK_TTL = 30.0  # check_fn 结果缓存秒数

    def is_available(self) -> bool:
        """检查工具当前是否可用（带缓存）。"""
        if self.check_fn is None:
            return True
        now = time.monotonic()
        if self._check_cache is not None:
            cached_at, cached_val = self._check_cache
            if now - cached_at < self._CHECK_TTL:
                return cached_val
        val = self.check_fn()
        self._check_cache = (now, val)
        return val


# ── ToolRegistry ─────────────────────────────────────────────────

class ToolRegistry:
    """工具注册表（Hermes 风格）。

    独立于 PluginRegistry，可独立用于 AST 自发现内置工具。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}

    def register(
        self,
        name: str,
        schema: dict,
        handler: Callable,
        toolset: str = "default",
        check_fn: Callable[[], bool] | None = None,
        optional: bool = False,
    ) -> None:
        """注册一个工具。"""
        if name in self._tools:
            logger.warning("[ToolRegistry] 工具 '%s' 已存在，将被覆盖", name)
        self._tools[name] = ToolEntry(
            name=name,
            schema=schema,
            handler=handler,
            toolset=toolset,
            check_fn=check_fn,
            optional=optional,
        )

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_definitions(self, enabled_toolsets: list[str] | None = None, allow_list: list[str] | None = None) -> list[dict]:
        """生成 LLM tool definitions（只包含可用的工具）。

        Args:
            enabled_toolsets: 启用的 toolset 列表。None = 全部。
            allow_list: 显式允许的工具名列表。用于选择性暴露。
        """
        result = []
        for entry in self._tools.values():
            # 可选工具必须在 allow_list 中
            if entry.optional and (allow_list is None or entry.name not in allow_list):
                continue
            # toolset 过滤
            if enabled_toolsets is not None and entry.toolset not in enabled_toolsets:
                continue
            # 可用性检查
            if not entry.is_available():
                continue
            result.append({"type": "function", "function": entry.schema})
        return result

    def discover_builtin(self, tools_dir: Path, package_prefix: str) -> int:
        """AST 扫描目录下的 .py 文件，自动发现 registry.register() 调用。

        Hermes 风格：只检查模块顶层是否有 registry.register() 调用，
        避免不必要的副作用。

        Args:
            tools_dir: 工具文件所在的目录
            package_prefix: Python 包前缀（如 "xiaomei_brain.tools.builtin"）

        Returns:
            loaded_count: 成功加载的工具模块数
        """
        count = 0
        for path in sorted(tools_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            if not _has_top_level_register(path):
                continue
            try:
                module_name = f"{package_prefix}.{path.stem}"
                importlib.import_module(module_name)
                count += 1
                logger.debug("[ToolRegistry] AST 发现工具: %s", path.stem)
            except Exception as e:
                logger.warning("[ToolRegistry] 导入工具模块失败: %s: %s", path.stem, e)
        return count

    def dispatch(self, name: str, args: dict) -> str:
        """执行工具调用。"""
        entry = self._tools.get(name)
        if entry is None:
            return f'{{"error": "未知工具: {name}"}}'
        try:
            return entry.handler(args)
        except Exception as e:
            logger.warning("[ToolRegistry] 工具 '%s' 执行失败: %s", name, e)
            return f'{{"error": "工具执行失败: {e}"}}'


def _has_top_level_register(path: Path) -> bool:
    """检查模块顶层是否有 registry.register() 或 tool_registry.register() 调用。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "register"
                and isinstance(func.value, ast.Name)
                and func.value.id in ("registry", "tool_registry")
            ):
                return True
    return False


# ── LoadedPlugin ─────────────────────────────────────────────────

@dataclass
class LoadedPlugin:
    """已加载的插件记录。"""

    manifest: Any  # PluginManifest
    status: Literal["loaded", "warn", "error", "disabled"] = "loaded"
    error: str | None = None
    summary: str = ""


# ── PluginRegistry ───────────────────────────────────────────────

class PluginRegistry:
    """中央注册表。

    插件写入，Core 读取。所有能力都通过此单例注册和获取。
    """

    def __init__(self) -> None:
        self._channels: dict[str, Any] = {}
        self._providers: dict[str, Any] = {}
        self._tools = ToolRegistry()
        self._agent_tools: list[Any] = []  # tools.base.Tool 对象
        self._speech: dict[str, Any] = {}
        self._memory: dict[str, Any] = {}
        self._hooks: dict[str, list[Callable]] = {}
        self._plugins: dict[str, LoadedPlugin] = {}
        self._web_search_providers: list[Any] = []
        self._pending_senses: list[tuple[Any, Any]] = []

    # ── Channel ─────────────────────────────────────────────────

    def register_channel(self, name: str, adapter: Any) -> None:
        self._channels[name] = adapter

    def get_channel(self, name: str) -> Any | None:
        return self._channels.get(name)

    def list_channels(self) -> list[str]:
        return list(self._channels.keys())

    # ── Provider ────────────────────────────────────────────────

    def register_provider(self, provider_id: str, provider: Any) -> None:
        self._providers[provider_id] = provider

    def get_provider(self, provider_id: str) -> Any | None:
        return self._providers.get(provider_id)

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    # ── Tool ────────────────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        schema: dict,
        handler: Callable,
        toolset: str = "default",
        check_fn: Callable[[], bool] | None = None,
        optional: bool = False,
    ) -> None:
        self._tools.register(name, schema, handler, toolset=toolset, check_fn=check_fn, optional=optional)

    def get_tool_definitions(self, enabled_toolsets: list[str] | None = None) -> list[dict]:
        return self._tools.get_definitions(enabled_toolsets)

    def dispatch_tool(self, name: str, args: dict) -> str:
        return self._tools.dispatch(name, args)

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    # ── Agent Tool (tools.base.Tool) ───────────────────────────

    def register_agent_tool(self, tool: Any) -> None:
        """注册 Agent 工具（接受 tools.base.Tool 对象）。"""
        self._agent_tools.append(tool)

    def get_agent_tools(self) -> list[Any]:
        """获取所有插件注册的 Agent 工具。"""
        return list(self._agent_tools)

    # ── Web Search Provider ────────────────────────────────────

    def register_web_search_provider(self, provider: Any) -> None:
        """注册 Web 搜索 Provider。

        核心工具 web_search 通过此方法收集可用的搜索后端，
        按优先级自动选择。
        """
        self._web_search_providers.append(provider)

    def get_web_search_providers(self) -> list[Any]:
        """获取所有已注册的 Web 搜索 Provider。"""
        return list(self._web_search_providers)

    # ── Speech ──────────────────────────────────────────────────

    def register_speech_provider(self, name: str, provider: Any) -> None:
        self._speech[name] = provider

    def get_speech_provider(self, name: str) -> Any | None:
        return self._speech.get(name)

    # ── Memory ──────────────────────────────────────────────────

    def register_memory_backend(self, name: str, backend: Any) -> None:
        self._memory[name] = backend

    def get_memory_backend(self, name: str) -> Any | None:
        return self._memory.get(name)

    # ── Hook ────────────────────────────────────────────────────

    def register_hook(self, event: str, callback: Callable) -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    def fire_hook(self, event: str, **kwargs) -> None:
        """同步触发 hook。"""
        for cb in self._hooks.get(event, []):
            try:
                cb(**kwargs)
            except Exception as e:
                logger.warning("[PluginRegistry] Hook '%s' 回调失败: %s", event, e)

    # ── Sense (Body 器官) ──────────────────────────────────────

    def register_sense(self, sense: Any, device: Any) -> None:
        """注册身体器官（Sense + Device）。

        body/ 插件调用此方法，由 conscious_living 消费后装配到 Body。
        """
        self._pending_senses.append((sense, device))

    def get_pending_senses(self) -> list[tuple[Any, Any]]:
        """获取所有待装配的器官。"""
        return list(self._pending_senses)

    # ── Plugin tracking ─────────────────────────────────────────

    def track_plugin(self, plugin: LoadedPlugin) -> None:
        self._plugins[plugin.manifest.name] = plugin

    def get_plugin(self, name: str) -> LoadedPlugin | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[LoadedPlugin]:
        return list(self._plugins.values())
