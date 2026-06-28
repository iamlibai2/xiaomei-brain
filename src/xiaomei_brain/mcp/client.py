"""MCP Client — 连接外部 MCP Server，发现工具，注册到 Agent。

用法::

    from xiaomei_brain.mcp.client import bootstrap_mcp_servers

    tools = ToolRegistry()
    bootstrap_mcp_servers(tools, config)  # 连接所有配置的 MCP Server

配置格式 (config.json)::

    "mcp_servers": {
        "seedance": {
            "command": "npx",
            "args": ["-y", "seedance-mcp"],
            "env": {"ARK_API_KEY": "..."},
            "timeout": 300,
            "enabled": true,
            "supports_parallel_tool_calls": false
        },
        "ppt_gen": {
            "url": "https://mcp-server.example.com/mcp",
            "headers": {"Authorization": "Bearer sk-..."},
            "transport": "http",
            "timeout": 180,
            "enabled": true,
            "include": ["generate_ppt"],
            "exclude": ["debug_tool"]
        }
    }

架构:
    - 后台 asyncio 事件循环运行在 daemon 线程中
    - 每个 MCP Server 一个 MCPConnection 实例
    - stdio 用 mcp SDK 的 stdio_client，HTTP 用 streamable_http_client
    - 工具发现: session.initialize() → session.list_tools()
    - 工具调用: session.call_tool() 在后台事件循环上执行
    - 熔断器: 3 次连续失败 → 60s 冷却 → 半开探测
    - 自动重连: 指数退避，最多 3 次
    - 并行工具调用: supports_parallel_tool_calls=true 时，同一 Server 多工具并发
    - 工具过滤: include/exclude 控制注册范围
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_TIMEOUT = 120.0
_DEFAULT_CONNECT_TIMEOUT = 30.0
_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_COOLDOWN_SEC = 60.0

# ── 全局状态 ───────────────────────────────────────────────────────

_mcp_loop: asyncio.AbstractEventLoop | None = None
_mcp_thread: threading.Thread | None = None
_lock = threading.Lock()
_servers: dict[str, "MCPConnection"] = {}
_error_counts: dict[str, int] = {}
_breaker_opened_at: dict[str, float] = {}
# 半开状态追踪：冷却期满后，下一次调用作为探测请求放行
#   CLOSED → (N failures) → OPEN → (cooldown) → HALF_OPEN → (probe) → CLOSED/OPEN
_breaker_half_open: set[str] = set()


def _ensure_mcp_loop() -> asyncio.AbstractEventLoop:
    """确保后台事件循环在 daemon 线程中运行。"""
    global _mcp_loop, _mcp_thread
    with _lock:
        if _mcp_loop is not None and _mcp_loop.is_running():
            return _mcp_loop
        _mcp_loop = asyncio.new_event_loop()
        _mcp_thread = threading.Thread(
            target=_mcp_loop.run_forever, name="mcp-loop", daemon=True
        )
        _mcp_thread.start()
        return _mcp_loop


def _run_on_mcp_loop(coro, timeout: float = 120.0) -> Any:
    """在后台事件循环上执行协程，同步等待结果。"""
    loop = _ensure_mcp_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _bump_error(name: str) -> None:
    """增加错误计数。

    三态熔断器逻辑：
    - CLOSED → 连续 N 次失败 → OPEN（开始冷却）
    - HALF_OPEN 探测失败 → 重新 OPEN（重置冷却计时）
    """
    with _lock:
        prev = _error_counts.get(name, 0)
        _error_counts[name] = prev + 1
        if prev + 1 >= _CIRCUIT_BREAKER_THRESHOLD:
            if name in _breaker_half_open:
                # 半开探测失败 — 重新断路，重置冷却时间
                _breaker_opened_at[name] = time.monotonic()
                _breaker_half_open.discard(name)
            else:
                # 首次达到阈值 — 开启熔断
                _breaker_opened_at[name] = time.monotonic()


def _reset_error(name: str) -> None:
    """完全关闭熔断器（探测成功或正常恢复）。"""
    with _lock:
        _error_counts.pop(name, None)
        _breaker_opened_at.pop(name, None)
        _breaker_half_open.discard(name)


def _breaker_blocked(name: str) -> bool:
    """检查熔断器是否阻止调用。

    三态逻辑：
    - CLOSED（错误数 < 阈值）: 放行
    - OPEN（冷却期内）: 阻止
    - HALF_OPEN（冷却期满，首次放行探测）: 放行探测请求
    """
    with _lock:
        count = _error_counts.get(name, 0)
        if count < _CIRCUIT_BREAKER_THRESHOLD:
            return False  # CLOSED — 放行
        opened_at = _breaker_opened_at.get(name, 0.0)
        age = time.monotonic() - opened_at
        if age < _CIRCUIT_BREAKER_COOLDOWN_SEC:
            return True  # OPEN — 仍在冷却，阻止
        # 冷却期满
        if name in _breaker_half_open:
            # 探测已在进行中（或已完成），放行后续调用
            return False
        # 首次冷却期满 → 转换为 HALF_OPEN，放行一次探测
        _breaker_half_open.add(name)
        return False


def _sanitize_name(name: str) -> str:
    """将服务器/工具名标准化为 mcp_xxx_yyy 格式。"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").lower()


from .connection import MCPConnection  # noqa: F401 — re-export

# ── 工具注册 ────────────────────────────────────────────────────────


def _normalize_filter(value: Any) -> set[str] | None:
    """标准化 include/exclude 为 set。支持 str（单个工具名）、list、None。"""
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple)):
        return set(value)
    return None


def _apply_tool_filters(tools: list, config: dict, server_name: str) -> list:
    """根据 include/exclude 过滤工具列表。

    - include (str | list): 白名单，指定后只注册这些工具
    - exclude (str | list): 黑名单，排除指定工具（include 优先）

    include 和 exclude 可同时使用：先取 include 交集，再去掉 exclude。
    """
    include = _normalize_filter(config.get("include"))
    exclude = _normalize_filter(config.get("exclude"))

    if include is None and exclude is None:
        return tools

    filtered = []
    skipped = []
    for tool in tools:
        tool_name = getattr(tool, "name", "")
        if include is not None and tool_name not in include:
            skipped.append(tool_name)
            continue
        if exclude is not None and tool_name in exclude:
            skipped.append(tool_name)
            continue
        filtered.append(tool)

    if skipped:
        verb = "include/exclude filter" if include is not None else "exclude filter"
        logger.info(
            "MCP server '%s': %d tool(s) skipped by %s: %s",
            server_name, len(skipped), verb, ", ".join(skipped),
        )
    return filtered


def _convert_mcp_schema(server_name: str, mcp_tool) -> dict:
    """将 MCP 工具格式转换为我们的 Tool schema。"""
    safe_server = _sanitize_name(server_name)
    safe_tool = _sanitize_name(mcp_tool.name)
    prefixed = f"mcp__{safe_server}__{safe_tool}"

    input_schema = getattr(mcp_tool, "inputSchema", None) or {}
    # 标准化 schema: 确保 type/properties/required 存在
    params = {
        "type": input_schema.get("type", "object"),
        "properties": input_schema.get("properties", {}),
    }
    required = input_schema.get("required", [])
    if required:
        params["required"] = required

    return {
        "name": prefixed,
        "description": mcp_tool.description or f"MCP tool {mcp_tool.name} from {server_name}",
        "parameters": params,
    }


def _make_tool_handler(conn: MCPConnection, tool_name: str):
    """创建同步工具处理函数。"""

    def handler(**kwargs: Any) -> str:
        if _breaker_blocked(conn.name):
            count = _error_counts.get(conn.name, 0)
            opened_at = _breaker_opened_at.get(conn.name, 0.0)
            remaining = max(1, int(_CIRCUIT_BREAKER_COOLDOWN_SEC - (time.monotonic() - opened_at)))
            return json.dumps({
                "error": (
                    f"MCP server '{conn.name}' is unreachable after {count} "
                    f"consecutive failures. Auto-retry in ~{remaining}s. "
                    f"Do NOT retry — use alternative approaches."
                )
            }, ensure_ascii=False)

        if not conn.session:
            _bump_error(conn.name)
            return json.dumps({
                "error": f"MCP server '{conn.name}' is not connected"
            }, ensure_ascii=False)

        async def _call():
            return await conn.call_tool(tool_name, arguments=kwargs)

        try:
            result = _run_on_mcp_loop(_call(), timeout=conn.tool_timeout)
            try:
                parsed = json.loads(result)
                if "error" not in parsed:
                    _reset_error(conn.name)
            except (json.JSONDecodeError, TypeError):
                _reset_error(conn.name)
            return result
        except Exception as e:
            _bump_error(conn.name)
            logger.error("MCP tool %s/%s call failed: %s", conn.name, tool_name, e)
            return json.dumps({
                "error": f"MCP call failed: {type(e).__name__}: {e}"
            }, ensure_ascii=False)

    return handler


# ── 公共 API ────────────────────────────────────────────────────────


def _load_mcp_config(config: dict | None = None) -> dict[str, dict]:
    """从 config.json 加载 MCP Server 配置。

    Args:
        config: 完整的 config.json 字典。None 时自动读取。

    Returns:
        {server_name: server_config}

    配置格式::

        "mcp_servers": {
            "seedance": {
                "command": "npx",
                "args": ["-y", "seedance-mcp"],
                "env": {"ARK_API_KEY": "..."},
                "timeout": 300,
                "enabled": true
            },
            "my_server": {
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer sk-..."},
                "transport": "http",
                "timeout": 180
            }
        }
    """
    if config is None:
        from xiaomei_brain.base.config import Config
        try:
            cfg = Config.from_json()
            if cfg:
                config = cfg._raw or {}
        except Exception:
            config = {}

    mcp_servers = config.get("mcp_servers", {}) if config else {}
    if not isinstance(mcp_servers, dict):
        logger.warning("mcp_servers 配置格式错误，应为 dict")
        return {}
    return mcp_servers


def bootstrap_mcp_servers(tool_registry, config: dict | None = None) -> int:
    """启动所有配置的 MCP Server，发现工具并注册。

    在 agent_manager.init_agent() 中调用。

    Args:
        tool_registry: ToolRegistry 实例
        config: 完整 config.json 字典

    Returns:
        注册的工具数量
    """
    try:
        from mcp import ClientSession  # noqa: F401 — 验证 SDK 可用
    except ImportError:
        logger.debug("MCP SDK 未安装，跳过 MCP 工具发现")
        return 0

    from xiaomei_brain.tools.base import Tool

    servers_config = _load_mcp_config(config)
    if not servers_config:
        logger.debug("未配置 MCP Server")
        return 0

    # 安全过滤：拦截外泄形状的 MCP 配置
    from .security import filter_suspicious_mcp_servers
    servers_config = filter_suspicious_mcp_servers(servers_config)
    if not servers_config:
        return 0

    total_tools = 0

    for name, srv_config in servers_config.items():
        if not isinstance(srv_config, dict):
            continue

        enabled = srv_config.get("enabled", True)
        if not enabled:
            logger.info("MCP server '%s': disabled", name)
            continue

        with _lock:
            if name in _servers:
                logger.debug("MCP server '%s': already connected", name)
                continue

        logger.info("MCP server '%s': connecting...", name)
        conn = MCPConnection(name, srv_config)

        if not conn.start():
            logger.error("MCP server '%s': failed to connect", name)
            continue

        with _lock:
            _servers[name] = conn

        # 工具过滤（include / exclude）
        filtered_tools = _apply_tool_filters(conn._tools, srv_config, name)

        # 注册工具
        for mcp_tool in filtered_tools:
            schema = _convert_mcp_schema(name, mcp_tool)
            handler = _make_tool_handler(conn, mcp_tool.name)

            tool = Tool(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
                func=handler,
                source=f"mcp:{name}",
                optional=False,
                category="mcp",
            )
            try:
                tool_registry.register(tool)
                total_tools += 1
            except ValueError:
                logger.warning(
                    "MCP tool '%s' 与已有工具冲突，跳过", schema["name"]
                )

        logger.info(
            "MCP server '%s': registered %d tool(s)", name, len(conn._tools),
        )

    logger.info("MCP: total %d tool(s) from %d server(s)", total_tools, len(_servers))
    return total_tools


def shutdown_mcp_servers():
    """关闭所有 MCP Server 连接。"""
    with _lock:
        names = list(_servers.keys())
    for name in names:
        with _lock:
            conn = _servers.pop(name, None)
        if conn:
            conn.shutdown()
            logger.info("MCP server '%s': shutdown", name)

    global _mcp_loop
    with _lock:
        if _mcp_loop and _mcp_loop.is_running():
            try:
                _mcp_loop.call_soon_threadsafe(_mcp_loop.stop)
            except Exception:
                pass
        _mcp_loop = None


# ── Config 热重载 ───────────────────────────────────────────────────

_config_reloader: Any = None  # ConfigReloader 实例
_mcp_tool_registry: Any = None


def register_config_listener(tool_registry):
    """将 MCP 注册为 ConfigReloader 的订阅者。

    当 config.json 变化时，自动重载 mcp_servers 配置并注册新工具。
    """
    global _mcp_tool_registry
    _mcp_tool_registry = tool_registry


def _on_config_changed(data: dict):
    """ConfigReloader 回调：config.json 变化时重新加载 MCP Server。"""
    if _mcp_tool_registry is None:
        return
    new_count = bootstrap_mcp_servers(_mcp_tool_registry, data)
    if new_count > 0:
        logger.info("Config reload: %d new MCP tool(s) registered", new_count)
    # 通知 DynamicToolLoader 重建索引
    from xiaomei_brain.tools.dynamic import notify_tools_changed
    notify_tools_changed()


def get_mcp_status() -> list[dict]:
    """获取 MCP Server 状态。"""
    result = []
    with _lock:
        servers = dict(_servers)
    for name, conn in servers.items():
        result.append({
            "name": name,
            "transport": "http" if conn._is_http() else "stdio",
            "tools": len(conn._tools),
            "connected": conn.session is not None,
        })
    return result
