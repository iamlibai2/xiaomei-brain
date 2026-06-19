"""PluginContext: 插件注册上下文。

插件通过 ctx 注册能力，无需了解核心内部结构。
参考 Hermes Agent 的 register(ctx) 模式。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import PluginRegistry

logger = logging.getLogger(__name__)


# ── Hook 事件类型 ──────────────────────────────────────────────────

VALID_HOOKS = frozenset({
    "pre_tool_call",
    "post_tool_call",
    "pre_llm_call",
    "post_llm_call",
    "on_session_start",
    "on_session_end",
    "on_startup",
    "on_shutdown",
    "pre_gateway_dispatch",
    "transform_tool_result",
})


# ── PluginContext ────────────────────────────────────────────────────

class PluginContext:
    """插件注册上下文。

    每个插件加载时创建一个 PluginContext 实例，传入 register(ctx) 函数。
    插件通过 ctx 上的方法注册自己的各种能力。
    """

    def __init__(
        self,
        config: dict,
        plugin_name: str,
        agent_id: str,
        registry: PluginRegistry,
    ) -> None:
        self.config = config                    # 此插件的配置段
        self.plugin_name = plugin_name          # 插件名称（用于日志）
        self.agent_id = agent_id
        self.logger = logging.getLogger(f"xiaomei_brain.plugin.{plugin_name}")
        self._registry = registry

    # ── Channel ──────────────────────────────────────────────────

    def register_channel(self, name: str, adapter: Any) -> None:
        """注册频道适配器。

        Args:
            name: 频道名称（"cli", "ws", "feishu", "http_p2p", ...）
            adapter: ChannelAdapter 子类实例
        """
        self._registry.register_channel(name, adapter)
        self.logger.info("频道已注册: %s", name)

    # ── Provider ─────────────────────────────────────────────────

    def register_provider(self, provider: Any) -> None:
        """注册 LLM 供应商。

        Args:
            provider: LLMProvider 子类实例
        """
        provider_id = getattr(provider, "provider_id", "unknown")
        self._registry.register_provider(provider_id, provider)
        self.logger.info("Provider 已注册: %s", provider_id)

    # ── Tool ─────────────────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        schema: dict,
        handler: Callable,
        toolset: str = "default",
        check_fn: Callable[[], bool] | None = None,
        optional: bool = False,
    ) -> None:
        """注册 Agent 工具（Hermes 风格：name + schema + handler）。

        Args:
            name: 工具名称（LLM 可见）
            schema: OpenAI 兼容的 JSON function 定义
            handler: 工具执行函数 handler(args: dict) -> str
            toolset: 工具分组（"cli", "ws", "feishu", ...）
            check_fn: 运行时可用性检查（返回 False → 不传给 LLM）
            optional: 是否可选（需要用户在 config 中显式 allow）
        """
        self._registry.register_tool(name, schema, handler, toolset=toolset, check_fn=check_fn, optional=optional)
        self.logger.info("工具已注册: %s (toolset=%s)", name, toolset)

    # ── Agent Tool (接受 tools.base.Tool 对象) ─────────────────

    def register_agent_tool(self, tool: Any) -> None:
        """注册 Agent 工具（接受 tools.base.Tool 对象）。

        和 register_tool() 的区别：
          - register_tool(): Hermes 风格，name + schema + handler
          - register_agent_tool(): 直接传入 Tool dataclass 实例

        插件目录下的 adapter.py 在 register(ctx) 中用此方法注册工具。
        """
        self._registry.register_agent_tool(tool)
        self.logger.info("Agent 工具已注册: %s (source=%s)", tool.name, getattr(tool, 'source', 'unknown'))

    # ── Web Search Provider ────────────────────────────────────

    def register_web_search_provider(self, provider: Any) -> None:
        """注册 Web 搜索 Provider。

        核心工具 web_search 会按优先级自动选择可用的 provider。
        """
        self._registry.register_web_search_provider(provider)
        self.logger.info("WebSearch provider 已注册: %s (priority=%s)",
                         getattr(provider, 'provider_id', 'unknown'),
                         getattr(provider, 'priority', 0))

    # ── Speech ───────────────────────────────────────────────────

    def register_speech_provider(self, provider: Any) -> None:
        """注册 TTS/STT 供应商。"""
        name = getattr(provider, "name", "unknown")
        self._registry.register_speech_provider(name, provider)
        self.logger.info("Speech provider 已注册: %s", name)

    # ── Memory ───────────────────────────────────────────────────

    def register_memory_backend(self, backend: Any) -> None:
        """注册记忆后端。"""
        name = getattr(backend, "backend_name", "unknown")
        self._registry.register_memory_backend(name, backend)
        self.logger.info("Memory backend 已注册: %s", name)

    # ── Hook ─────────────────────────────────────────────────────

    def register_hook(self, event: str, callback: Callable) -> None:
        """注册生命周期钩子。

        Args:
            event: 事件名，必须是 VALID_HOOKS 之一
            callback: 回调函数
        """
        if event not in VALID_HOOKS:
            self.logger.warning("未知 hook 事件: %s，有效值: %s", event, sorted(VALID_HOOKS))
            return
        self._registry.register_hook(event, callback)
        self.logger.info("Hook 已注册: %s", event)

    # ── 装饰器快捷方式 ──────────────────────────────────────────

    def tool(self, name: str, description: str, toolset: str = "default"):
        """装饰器：@ctx.tool(name="xxx", description="...")"""
        def decorator(fn: Callable) -> Callable:
            import inspect
            # 从函数签名生成简单 schema
            sig = inspect.signature(fn)
            properties = {}
            required = []
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                param_type = "string"
                if param.annotation is not inspect.Parameter.empty:
                    anno = param.annotation
                    if anno is int:
                        param_type = "integer"
                    elif anno is float:
                        param_type = "number"
                    elif anno is bool:
                        param_type = "boolean"
                properties[param_name] = {"type": param_type, "description": ""}
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

            schema = {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }

            def handler(args: dict) -> str:
                return str(fn(**args))

            self.register_tool(name, schema, handler, toolset=toolset)
            return fn
        return decorator

    def hook(self, event: str):
        """装饰器：@ctx.hook("post_tool_call")"""
        def decorator(fn: Callable) -> Callable:
            self.register_hook(event, fn)
            return fn
        return decorator
