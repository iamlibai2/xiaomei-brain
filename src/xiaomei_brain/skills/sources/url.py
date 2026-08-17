"""URL 技能源 — 从直链、ZIP 或公开 Skill 页面获取 Skill。"""

from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urljoin

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
        github_repo = re.match(
            r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
            url,
            re.IGNORECASE,
        )
        if github_repo:
            from .github import GitHubSourceAdapter
            return GitHubSourceAdapter().fetch(
                f"{github_repo.group(1)}/{github_repo.group(2)}"
            )
        github_tree = re.match(
            r"^https?://github\.com/([\w.-]+)/([\w.-]+)/tree/([^/]+)/(.*)$",
            url,
            re.IGNORECASE,
        )
        if github_tree:
            from .github import GitHubSourceAdapter
            owner, repo, ref, path = github_tree.groups()
            return GitHubSourceAdapter().fetch(f"{owner}/{repo}/{path}:{ref}")
        resp = requests.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        if "zip" in content_type or url.lower().split("?", 1)[0].endswith(".zip"):
            return self._fetch_zip(identifier, url, resp.content)
        if "text/html" in content_type:
            if "github.com" in url and "/blob/" in url:
                raw_url = url.replace("/blob/", "/raw/")
                raise ValueError(
                    f"URL 是 GitHub 网页，不是原始文件。请使用 raw URL:\n"
                    f"  {raw_url}\n"
                    f"或使用 GitHub shorthand: owner/repo[/path]"
                )
            response_text = resp.text if isinstance(resp.text, str) else ""
            body = html.unescape(response_text)
            command = re.search(
                r"(?:npx\s+skills\s+add|skillhub\s+install)\s+[^<\r\n]+",
                body,
                re.IGNORECASE,
            )
            if command:
                from .marketplace import MarketplaceSourceAdapter
                return MarketplaceSourceAdapter().fetch(command.group(0).strip())
            for href in re.findall(r'href=["\']([^"\']+)["\']', body, re.IGNORECASE):
                target = urljoin(url, href)
                lowered = target.lower().split("?", 1)[0]
                if lowered.endswith("skill.md") or lowered.endswith(".zip"):
                    return self.fetch(target)
            raise ValueError(
                "HTML 网页没有公开可识别的 Skill 安装命令、SKILL.md 或 ZIP 下载地址"
            )

        return SourceBundle(
            content=resp.text,
            source="url",
            identifier=identifier,
            resolved_url=url,
        )

    @staticmethod
    def _fetch_zip(identifier: str, url: str, payload: bytes) -> SourceBundle:
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise ValueError("URL 返回的内容不是有效 ZIP Skill 包") from exc
        safe_names: list[str] = []
        for raw_name in archive.namelist():
            normalized = raw_name.replace("\\", "/").lstrip("/")
            path = PurePosixPath(normalized)
            if not normalized or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"ZIP Skill 包包含不安全路径: {raw_name}")
            if not raw_name.endswith("/"):
                safe_names.append(normalized)
        manifests = [name for name in safe_names if PurePosixPath(name).name == "SKILL.md"]
        if len(manifests) != 1:
            raise ValueError(f"ZIP Skill 包应包含一个 SKILL.md，实际发现 {len(manifests)} 个")
        manifest = manifests[0]
        root = PurePosixPath(manifest).parent
        files: dict[str, str | bytes] = {}
        for name in safe_names:
            path = PurePosixPath(name)
            if path == PurePosixPath(manifest) or root not in path.parents:
                continue
            relative = path.relative_to(root).as_posix()
            raw = archive.read(name)
            try:
                files[relative] = raw.decode("utf-8")
            except UnicodeDecodeError:
                files[relative] = raw
        return SourceBundle(
            content=archive.read(manifest).decode("utf-8"),
            source="url_zip",
            identifier=identifier,
            resolved_url=url,
            files=files,
        )
