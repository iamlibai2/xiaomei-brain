"""GitHub 技能源 — 从 GitHub 仓库获取 SKILL.md。"""

from __future__ import annotations

import logging
import os
import re

import requests

from xiaomei_brain.skills.sources.base import BaseSourceAdapter, SourceBundle

logger = logging.getLogger(__name__)

# 匹配: owner/repo[/path][:ref]
# 例子:
#   iamlibai2/skills
#   iamlibai2/skills/browser-helper
#   iamlibai2/skills:main
#   iamlibai2/skills/browser-helper:main
_PATTERN = re.compile(r'^([\w.-]+)/([\w.-]+)(?:/([\w./-]+))?(?::([\w-]+))?$')

# GitHub raw 镜像列表（按优先级）。
# 用于 raw.githubusercontent.com 被墙的环境。
_MIRRORS: list[str] = []


def _get_mirrors() -> list[str]:
    """返回 GitHub raw 镜像列表。首次调用从环境变量解析。"""
    if not _MIRRORS:
        env = os.environ.get("GITHUB_RAW_MIRRORS", "")
        if env:
            _MIRRORS.extend(m.strip() for m in env.split(",") if m.strip())
        # 默认备选（按优先级）
        _MIRRORS.extend([
            "https://raw.fastgit.org",
            "https://hub.gitmirror.com",
        ])
    return _MIRRORS


class GitHubSourceAdapter(BaseSourceAdapter):
    """从 GitHub 仓库获取 SKILL.md。

    标识符格式：
        owner/repo              → 仓库根目录 SKILL.md（默认分支）
        owner/repo/path         → {path}/SKILL.md（默认分支）
        owner/repo:ref          → 仓库根目录 SKILL.md（指定分支）
        owner/repo/path:ref     → {path}/SKILL.md（指定分支）

    默认分支为 "main"。

    raw.githubusercontent.com 被墙时，自动尝试镜像（可通过
    GITHUB_RAW_MIRRORS 环境变量添加自定义镜像，逗号分隔）。
    """

    def can_handle(self, identifier: str) -> bool:
        # URL 优先 — https://github.com/... 交给 URLSourceAdapter
        if identifier.startswith("http://") or identifier.startswith("https://"):
            return False
        return bool(_PATTERN.match(identifier))

    def resolve(self, identifier: str) -> str:
        return self._build_url(identifier, "https://raw.githubusercontent.com")

    def _build_url(self, identifier: str, base_url: str) -> str:
        """用给定 base URL 拼接 raw 路径。"""
        m = _PATTERN.match(identifier)
        if not m:
            raise ValueError(
                f"无效的 GitHub 标识符: {identifier}。"
                f"期望格式: owner/repo[/path][:ref]"
            )

        owner, repo, path, ref = m.group(1), m.group(2), m.group(3) or "", m.group(4) or "main"
        skill_path = f"{path}/SKILL.md" if path else "SKILL.md"
        skill_path = skill_path.replace("//", "/")
        if "{mirror_path}" in base_url:
            return base_url.format(
                owner=owner, repo=repo, ref=ref, path=skill_path,
                mirror_path=f"{owner}/{repo}/{ref}/{skill_path}",
            )
        return f"{base_url}/{owner}/{repo}/{ref}/{skill_path}"

    def fetch(self, identifier: str) -> SourceBundle:
        # 尝试直连 + 镜像
        urls = [self._build_url(identifier, "https://raw.githubusercontent.com")]
        urls.extend(self._build_url(identifier, m) for m in _get_mirrors())

        last_error = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=30, allow_redirects=True)
                if resp.status_code == 404:
                    raise FileNotFoundError(
                        f"SKILL.md 未找到: {url}\n"
                        f"请检查仓库是否存在、路径是否正确、文件是否在仓库根目录或指定路径下。"
                    )
                resp.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.debug("GitHub mirror %s failed: %s", url, e)
                last_error = e
                continue
            except FileNotFoundError:
                raise
        else:
            raise RuntimeError(
                f"所有 GitHub 源均不可达，最后错误: {last_error}\n"
                f"尝试的 URL: {urls}\n"
                f"提示: 可设置 GITHUB_RAW_MIRRORS 环境变量添加自定义镜像"
            )

        m = _PATTERN.match(identifier)
        owner, repo, path, ref = m.group(1), m.group(2), m.group(3) or "", m.group(4) or "main"

        return SourceBundle(
            content=resp.text,
            source="github",
            identifier=identifier,
            resolved_url=url,
            metadata={
                "repo_owner": owner,
                "repo_name": repo,
                "repo_path": path or "",
                "ref": ref,
            },
        )
