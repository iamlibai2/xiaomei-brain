"""Web get provider — fetches URLs and extracts readable content."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import unicodedata
from dataclasses import dataclass
from typing import Generator
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MAX_CHARS = 50_000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class GetResult:
    url: str
    final_url: str
    status: int
    content_type: str
    title: str | None
    text: str
    extractor: str
    truncated: bool
    took_ms: int


def _is_private_url(url: str) -> bool:
    """Check if URL resolves to a private/internal IP (covers IPv4 and IPv6)."""
    try:
        host = re.sub(r":\d+$", "", url.split("://", 1)[-1].split("/", 1)[0])
        # IPv6 hostnames arrive as `[::1]` in the URL — strip brackets
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        # 任意一个解析结果命中内网/loopback/link-local/AWS metadata
        # 就视为私有地址。getaddrinfo 同时返回 IPv4 + IPv6，所以
        # IPv6 主机名（如 `fc00::/7` ULA、`fe80::/10` link-local）也被覆盖。
        try:
            ipaddress.ip_address(host)
            # 用 5 元组占位让下方 for 解包保持一致：synthetic sockaddr 是 (host, 0)
            addresses = [(socket.AF_UNSPEC, socket.SOCK_STREAM, 0, "", (host, 0))]
        except ValueError:
            try:
                addresses = socket.getaddrinfo(host, None)
            except (socket.gaierror, ValueError):
                return False
        for _family, _, _, _, sockaddr in addresses:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_reserved
                or ip.is_link_local  # 169.254/16, 含 AWS/GCP metadata 169.254.169.254
            ):
                return True
        return False
    except Exception:
        return False


def _looks_like_html(text: str) -> bool:
    trimmed = text.lstrip()[:256].lower()
    return trimmed.startswith("<!doctype html") or trimmed.startswith("<html")


def _decode_entities(text: str) -> str:
    """Decode common HTML entities."""
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
        "&lt;": "<",
        "&gt;": ">",
        "&#x([0-9a-f]+);": lambda m: chr(int(m.group(1), 16)),
        "&#(\\d+);": lambda m: chr(int(m.group(1), 10)),
    }
    for pattern, replacement in replacements.items():
        if callable(replacement):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        else:
            text = text.replace(pattern, replacement)
    return text


def _strip_tags(text: str) -> str:
    return _decode_entities(re.sub(r"<[^>]+>", "", text))


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _html_to_markdown(html: str) -> tuple[str, str | None]:
    """Convert HTML to markdown and extract title."""
    # Extract title
    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.IGNORECASE)
    title = None
    if title_match:
        title = _normalize_whitespace(_strip_tags(title_match.group(1)))

    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", "", text, flags=re.IGNORECASE)

    # Links: [label](url)
    text = re.sub(
        r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
        lambda m: f"[{_normalize_whitespace(_strip_tags(m.group(2)))}]({m.group(1)})",
        text,
        flags=re.IGNORECASE,
    )

    # Headers
    text = re.sub(
        r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
        lambda m: f"\n{'#' * max(1, min(6, int(m.group(1))))} {_normalize_whitespace(_strip_tags(m.group(2)))}\n",
        text,
        flags=re.IGNORECASE,
    )

    # Lists
    text = re.sub(
        r"<li[^>]*>([\s\S]*?)</li>",
        lambda m: f"\n- {_normalize_whitespace(_strip_tags(m.group(1)))}",
        text,
        flags=re.IGNORECASE,
    )

    # Block elements
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|section|article|header|footer|table|tr|ul|ol)[^>]*>", "\n", text, flags=re.IGNORECASE)

    text = _strip_tags(text)
    text = _normalize_whitespace(text)
    return text, title


def _markdown_to_text(markdown: str) -> str:
    """Strip markdown formatting to plain text."""
    text = markdown
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)  # images
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links
    text = re.sub(r"```[\s\S]*?```", "", text)  # code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)  # inline code
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headers
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # lists
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
    return _normalize_whitespace(text)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text to max_chars."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


class WebGetProvider:
    """Fetch URLs and extract readable content (markdown or text).

    Supports:
    - HTML: extracts main content via basic HTML→markdown conversion
    - Markdown: returns as-is
    - JSON: pretty-prints
    - Plain text: returns as-is
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_chars: int = DEFAULT_MAX_CHARS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self.max_chars = max_chars
        self.user_agent = user_agent

    def fetch(
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
    ) -> GetResult:
        """Fetch a URL and extract content.

        Args:
            url: HTTP or HTTPS URL to fetch.
            extract_mode: "markdown" (default) or "text".
            max_chars: Maximum characters to return (default: provider max_chars).

        Returns:
            FetchResult with url, final_url, status, content_type, title, text, extractor, truncated, took_ms.
        """
        import time

        start = time.monotonic()
        max_chars = max_chars or self.max_chars

        # Validate URL
        try:
            parsed = requests.packages.urllib3.util.url.parse_url(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("URL must use http or https scheme")
            if not parsed.host:
                raise ValueError("Invalid URL: missing host")
        except Exception as e:
            raise ValueError(f"Invalid URL: {e}") from e

        # SSRF 防护：拒绝指向私有/loopback/保留地址的 URL。
        # 公共 URL 跳转到内部 IP 是常见的 SSRF 攻击向量，所以下面关掉
        # allow_redirects 改手动跟进，每跳都重新校验。
        if _is_private_url(url):
            raise ValueError(
                f"URL blocked (SSRF protection): {url} resolves to a private, "
                f"loopback, or reserved address. Requests to localhost, LAN IPs, "
                f"or cloud metadata (169.254.169.254) are not allowed."
            )

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/markdown, text/html;q=0.9, */*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        }

        current_url = url
        redirect_count = 0
        response = None
        while True:
            response = requests.get(
                current_url,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
                stream=True,
            )

            if response.is_redirect:
                if redirect_count >= self.max_redirects:
                    response.close()
                    raise RuntimeError(
                        f"Too many redirects (>{self.max_redirects})"
                    )
                location = response.headers.get("Location", "")
                if not location:
                    response.close()
                    raise RuntimeError("Redirect with no Location header")
                next_url = urljoin(current_url, location)
                if _is_private_url(next_url):
                    response.close()
                    raise ValueError(
                        f"Redirect blocked (SSRF protection): "
                        f"{current_url} -> {next_url} (private/reserved address)"
                    )
                response.close()
                current_url = next_url
                redirect_count += 1
                continue

            break

        final_url = response.url
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        # Normalize: take first part before semicolon
        content_type = content_type.split(";")[0].strip()

        # Read body with byte limit. bytearray 用 extend 避免每次 += 复制整个 buffer。
        body_bytes = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            body_bytes.extend(chunk)
            if len(body_bytes) > self.max_response_bytes:
                del body_bytes[self.max_response_bytes :]
                break

        try:
            body = body_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError(f"Failed to decode response body: {e}") from e

        # Content-type detection fallback
        if not content_type or content_type == "application/octet-stream":
            if _looks_like_html(body):
                content_type = "text/html"
            elif body.lstrip()[:1] in ("{", "["):
                content_type = "application/json"
            else:
                content_type = "text/plain"

        took_ms = int((time.monotonic() - start) * 1000)

        extractor = "raw"
        title: str | None = None

        if "text/markdown" in content_type.lower():
            text = body
            extractor = "cf-markdown"
            if extract_mode == "text":
                text = _markdown_to_text(text)

        elif "text/html" in content_type.lower():
            text, title = _html_to_markdown(body)
            extractor = "html-to-markdown"
            if extract_mode == "text":
                text = _markdown_to_text(text)

        elif "application/json" in content_type.lower():
            try:
                parsed_json = json.loads(body)
                text = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                extractor = "json"
            except Exception:
                text = body
                extractor = "raw"

        else:
            text = body
            extractor = "raw"
            if extract_mode == "text":
                text = _normalize_whitespace(_strip_tags(text))

        text, truncated = _truncate(text, max_chars)

        return GetResult(
            url=url,
            final_url=final_url,
            status=status,
            content_type=content_type,
            title=title,
            text=text,
            extractor=extractor,
            truncated=truncated,
            took_ms=took_ms,
        )
