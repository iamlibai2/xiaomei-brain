"""Web search tool — 薄壳调度器。

核心工具 web_search 定义固定的 name + schema，实际搜索逻辑
由 WebSearchProvider 协议实现提供。按优先级自动选择可用的 provider。
"""

from __future__ import annotations

import logging

from ..base import tool

logger = logging.getLogger(__name__)

_registry = None  # PluginRegistry 引用，由 init_agent() 设置


def set_registry(registry) -> None:
    """设置 PluginRegistry 引用（由 init_agent() 调用）。"""
    global _registry
    _registry = registry


def _resolve_provider():
    """按优先级解析可用的 WebSearchProvider。

    遍历所有已注册的 provider，过滤 is_available()=True，
    按 priority 降序排列，返回第一个。
    """
    if _registry is None:
        return None

    providers = _registry.get_web_search_providers()
    available = [p for p in providers if p.is_available()]
    if not available:
        return None

    available.sort(key=lambda p: p.priority, reverse=True)
    return available[0]


@tool(
    name="web_search",
    description="使用搜索引擎搜索实时信息、文档或研究主题。支持时间过滤: pd(24h), pw(7d), pm(31d), py(365d)，或指定日期范围 YYYY-MM-DDtoYYYY-MM-DD。",
)
def web_search(
    query: str,
    count: int = 10,
    freshness: str | None = None,
) -> str:
    """Search the web via the best available provider.

    Args:
        query: Search query.
        count: Number of results (1-50).
        freshness: Time filter: pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD.
    """
    provider = _resolve_provider()

    if provider is None:
        return "搜索未启用或未配置。请在 config.json 中配置 baidu_api_key。"

    if not query or not query.strip():
        return "搜索关键词不能为空。"

    try:
        results = provider.search(query=query, count=count, freshness=freshness)

        if not results:
            return "未找到相关结果。"

        output = f"找到 {len(results)} 条结果:\n\n"
        for i, r in enumerate(results, 1):
            time_str = f" ({r.time})" if r.time else ""
            output += f"{i}. {r.title}{time_str}\n   {r.url}\n\n"

        return output.strip()

    except Exception as e:
        logger.error("Web search error: %s", e)
        return f"搜索失败: {e}"


web_search_tool = web_search
