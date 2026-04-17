"""Web search provider using Baidu AI Search API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://qianfan.baidubce.com/v2/ai_search"
DEFAULT_COUNT = 10


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    time: str | None = None


class BaiduSearchProvider:
    """Baidu AI Search (Qianfan) web search.

    API docs: https://console.bce.baidu.com/ai-search/qianfan/ais/console/apiKey
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def search(
        self,
        query: str,
        count: int = DEFAULT_COUNT,
        freshness: str | None = None,
    ) -> list[SearchResult]:
        """Search the web.

        Args:
            query: Search query string.
            count: Number of results (1-50, default 10).
            freshness: Time filter:
                - "pd" = past 24 hours
                - "pw" = past 7 days
                - "pm" = past 31 days
                - "py" = past 365 days
                - "YYYY-MM-DDtoYYYY-MM-DD" = custom date range

        Returns:
            List of SearchResult objects.
        """
        from datetime import datetime, timedelta
        import re

        count = max(1, min(50, count))

        # Build search filter
        search_filter: dict[str, Any] = {}
        if freshness:
            current_time = datetime.now()
            end_date = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")
            date_pattern = r"\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}"

            if freshness in ("pd", "pw", "pm", "py"):
                delta = {"pd": 1, "pw": 6, "pm": 30, "py": 364}[freshness]
                start_date = (current_time - timedelta(days=delta)).strftime("%Y-%m-%d")
                search_filter = {"range": {"page_time": {"gte": start_date, "lt": end_date}}}
            elif re.match(date_pattern, freshness):
                start_date, end_date = freshness.split("to")
                search_filter = {"range": {"page_time": {"gte": start_date, "lt": end_date}}}

        request_body = {
            "messages": [{"content": query, "role": "user"}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": count}],
        }
        if search_filter:
            request_body["search_filter"] = search_filter

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Appbuilder-From": "xiaomei-brain",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{self.base_url}/web_search",
            headers=headers,
            json=request_body,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "code" in data:
            raise RuntimeError(f"Baidu search error: {data.get('message', data['code'])}")

        results = []
        for item in data.get("references", []):
            # Remove snippet to reduce output noise
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                time=item.get("time"),
            ))

        return results
