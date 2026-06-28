"""URL 技能源 — 从直链下载 SKILL.md。"""

from __future__ import annotations

import requests

from xiaomei_brain.skills.sources.base import BaseSourceAdapter, SourceBundle


class URLSourceAdapter(BaseSourceAdapter):
    """从直接 URL 获取 SKILL.md。

    支持：
        https://example.com/path/to/SKILL.md
        https://raw.githubusercontent.com/.../SKILL.md
    """

    def can_handle(self, identifier: str) -> bool:
        return identifier.startswith("http://") or identifier.startswith("https://")

    def resolve(self, identifier: str) -> str:
        return identifier

    def fetch(self, identifier: str) -> SourceBundle:
        url = self.resolve(identifier)
        resp = requests.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            if "github.com" in url and "/blob/" in url:
                raw_url = url.replace("/blob/", "/raw/")
                raise ValueError(
                    f"URL 是 GitHub 网页，不是原始文件。请使用 raw URL:\n"
                    f"  {raw_url}\n"
                    f"或使用 GitHub shorthand: owner/repo[/path]"
                )
            raise ValueError(
                "URL 返回的是 HTML 页面，不是原始文件。请确保 URL 直接指向 SKILL.md 文件。"
            )

        return SourceBundle(
            content=resp.text,
            source="url",
            identifier=identifier,
            resolved_url=url,
        )
