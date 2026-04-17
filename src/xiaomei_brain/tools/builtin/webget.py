"""Web get tool — fetch and extract readable content from URLs."""

from __future__ import annotations

import logging

from ..base import tool

logger = logging.getLogger(__name__)

_get_provider = None


def set_get_provider(provider) -> None:
    global _get_provider
    _get_provider = provider


@tool(
    name="web_get",
    description="抓取网页内容并提取可读文本。支持提取为 markdown 或纯文本格式，自动处理 HTML、Markdown、JSON 等内容类型。",
)
def web_get(
    url: str,
    extract_mode: str = "markdown",
    max_chars: int = 40000,
) -> str:
    """Fetch a URL and extract readable content.

    Args:
        url: HTTP or HTTPS URL to fetch.
        extract_mode: "markdown" (default) or "text".
        max_chars: Maximum characters to return (default: 40000).

    Returns:
        Extracted text content with metadata.
    """
    global _get_provider

    if _get_provider is None:
        return "Web get 未启用。请在 config.json 中启用 web_get 或配置相关设置。"

    if not url or not url.strip():
        return "URL 不能为空。"

    try:
        result = _get_provider.fetch(
            url=url.strip(),
            extract_mode=extract_mode,
            max_chars=max_chars,
        )

        # Build output
        lines = [
            f"# {result.title}" if result.title else "网页内容",
            f"URL: {result.final_url}",
            f"状态: {result.status}",
            f"类型: {result.content_type}",
            f"提取方式: {result.extractor}",
            "",
            "---",
            "",
            result.text,
        ]

        output = "\n".join(lines)

        if result.truncated:
            output += "\n\n> 内容已截断（超过 max_chars 限制）"

        return output

    except ValueError as e:
        return f"URL 错误: {e}"
    except Exception as e:
        logger.error("Web get error: %s", e)
        return f"抓取失败: {e}"


web_get_tool = web_get
