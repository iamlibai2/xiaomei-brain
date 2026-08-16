"""Web search tool — 薄壳调度器。

核心工具 web_search 定义固定的 name + schema，实际搜索逻辑
由 WebSearchProvider 协议实现提供。按优先级自动选择可用的 provider。
"""

from __future__ import annotations

import logging
from typing import Any

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
    description=(
        "使用搜索引擎搜索实时信息、文档或研究主题，返回服务商的结构化真实结果。"
        "支持时间过滤: pd(24h), pw(7d), pm(31d), py(365d)，或指定日期范围 "
        "YYYY-MM-DDtoYYYY-MM-DD。若 success=false，说明搜索服务本身失败；"
        "当前执行中不要通过更换关键词反复调用，应使用 error 信息结束或说明受阻。"
    ),
)
def web_search(
    query: str,
    count: int = 10,
    freshness: str | None = None,
) -> dict[str, Any]:
    """Search the web via the best available provider.

    Args:
        query: Search query.
        count: Number of results (1-50).
        freshness: Time filter: pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD.
    """
    provider = _resolve_provider()

    if provider is None:
        return {
            "success": False,
            "error": {
                "type": "not_configured",
                "message": "搜索未启用或未配置。请在 Desktop 的 Agent 设置 → 联网搜索中配置搜索服务。",
                "retryable": False,
            },
        }

    if not query or not query.strip():
        return {
            "success": False,
            "provider": provider.provider_id,
            "error": {
                "type": "invalid_query",
                "message": "搜索关键词不能为空。",
                "retryable": False,
            },
        }

    try:
        results = provider.search(query=query, count=count, freshness=freshness)

        return {
            "success": True,
            "provider": provider.provider_id,
            "query": query,
            "count": len(results),
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "time": result.time,
                }
                for result in results
            ],
        }

    except Exception as e:
        logger.error("Web search error: %s", e)
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None)
        response_text = str(getattr(response, "text", "") or "").strip()
        retry_after = None
        headers = getattr(response, "headers", None)
        if headers is not None:
            retry_after = headers.get("Retry-After")
        error_type = "rate_limited" if status_code == 429 else (
            "http_error" if status_code is not None else "provider_error"
        )
        error: dict[str, Any] = {
            "type": error_type,
            "message": str(e),
            "retryable": bool(status_code == 429 or (isinstance(status_code, int) and status_code >= 500)),
        }
        if status_code is not None:
            error["http_status"] = status_code
        if response_text:
            error["response"] = response_text[:2000]
        if retry_after:
            error["retry_after"] = retry_after
        return {
            "success": False,
            "provider": provider.provider_id,
            "query": query,
            "error": error,
        }


web_search_tool = web_search
