"""Web search tool using Baidu AI Search API."""

from __future__ import annotations

import logging

from ..base import tool

logger = logging.getLogger(__name__)

_search_provider = None


def set_search_provider(provider) -> None:
    global _search_provider
    _search_provider = provider


@tool(
    name="web_search",
    description="使用百度搜索实时信息、文档或研究主题。支持时间过滤: pd(24h), pw(7d), pm(31d), py(365d)，或指定日期范围 YYYY-MM-DDtoYYYY-MM-DD。",
)
def web_search(
    query: str,
    count: int = 10,
    freshness: str | None = None,
) -> str:
    """Search the web via Baidu.

    Args:
        query: Search query.
        count: Number of results (1-50).
        freshness: Time filter: pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD.
    """
    global _search_provider

    if _search_provider is None:
        return "百度搜索未启用或未配置。请在 config.json 中配置 baidu_api_key。"

    if not query or not query.strip():
        return "搜索关键词不能为空。"

    try:
        results = _search_provider.search(query=query, count=count, freshness=freshness)

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
