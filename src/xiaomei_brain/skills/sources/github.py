"""GitHub 技能源 — 从 GitHub 仓库获取 SKILL.md。

支持带代码文件的技能：
1. Git Trees API（1 次调用整个 repo 文件树）优先
2. Contents API 递归下载兜底
3. 子目录结构保留（scripts/、templates/ 等）
"""

from __future__ import annotations

import base64
import logging
import os
import re

import requests

from xiaomei_brain.skills.sources.base import BaseSourceAdapter, SourceBundle

logger = logging.getLogger(__name__)

# 匹配: owner/repo[/path][:ref]
_PATTERN = re.compile(r'^([\w.-]+)/([\w.-]+)(?:/([\w./-]+))?(?::([\w-]+))?$')

# GitHub raw 镜像列表（按优先级）
_MIRRORS: list[str] = []

# session 级 repo tree 缓存: repo → (default_branch, tree_entries)
_TREE_CACHE: dict[str, tuple[str, list[dict]]] = {}


def _get_mirrors() -> list[str]:
    """返回 GitHub raw 镜像列表。首次调用从环境变量解析。"""
    if not _MIRRORS:
        env = os.environ.get("GITHUB_RAW_MIRRORS", "")
        if env:
            _MIRRORS.extend(m.strip() for m in env.split(",") if m.strip())
        _MIRRORS.extend([
            "https://raw.fastgit.org",
            "https://hub.gitmirror.com",
        ])
    return _MIRRORS


def _parse_identifier(identifier: str) -> tuple[str, str, str, str]:
    """解析 identifier，返回 (owner, repo, path, ref)。"""
    m = _PATTERN.match(identifier)
    if not m:
        raise ValueError(
            f"无效的 GitHub 标识符: {identifier}。"
            f"期望格式: owner/repo[/path][:ref]"
        )
    return m.group(1), m.group(2), m.group(3) or "", m.group(4) or "main"


class GitHubSourceAdapter(BaseSourceAdapter):
    """从 GitHub 仓库获取 SKILL.md。

    标识符格式：
        owner/repo              → 仓库根目录 SKILL.md（默认分支）
        owner/repo/path         → {path}/SKILL.md（默认分支）
        owner/repo:ref          → 仓库根目录 SKILL.md（指定分支）
        owner/repo/path:ref     → {path}/SKILL.md（指定分支）

    默认分支为 "main"。raw.githubusercontent.com 被墙时自动尝试镜像。
    """

    def can_handle(self, identifier: str) -> bool:
        if identifier.startswith("http://") or identifier.startswith("https://"):
            return False
        return bool(_PATTERN.match(identifier))

    def resolve(self, identifier: str) -> str:
        return self._build_url(identifier, "https://raw.githubusercontent.com")

    def _build_url(self, identifier: str, base_url: str) -> str:
        owner, repo, path, ref = _parse_identifier(identifier)
        skill_path = f"{path}/SKILL.md" if path else "SKILL.md"
        skill_path = skill_path.replace("//", "/")
        if "{mirror_path}" in base_url:
            return base_url.format(
                owner=owner, repo=repo, ref=ref, path=skill_path,
                mirror_path=f"{owner}/{repo}/{ref}/{skill_path}",
            )
        return f"{base_url}/{owner}/{repo}/{ref}/{skill_path}"

    def fetch(self, identifier: str) -> SourceBundle:
        owner, repo, path, ref = _parse_identifier(identifier)
        path = path.rstrip("/")

        # 1. 下载 SKILL.md（直连 + 镜像）
        urls = [self._build_url(identifier, "https://raw.githubusercontent.com")]
        urls.extend(self._build_url(identifier, m) for m in _get_mirrors())

        last_error = None
        main_resp = None
        main_url = ""
        for url in urls:
            try:
                resp = requests.get(url, timeout=30, allow_redirects=True)
                if resp.status_code == 404:
                    raise FileNotFoundError(
                        f"SKILL.md 未找到: {url}\n"
                        f"请检查仓库是否存在、路径是否正确。"
                    )
                resp.raise_for_status()
                main_resp = resp
                main_url = url
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

        # 2. 下载目录中所有文件（Trees API → Contents 递归兜底）
        files = self._download_directory(owner, repo, path, ref)

        return SourceBundle(
            content=main_resp.text,
            source="github",
            identifier=identifier,
            resolved_url=main_url,
            metadata={
                "repo_owner": owner,
                "repo_name": repo,
                "repo_path": path or "",
                "ref": ref,
            },
            files=files,
        )

    # ── 目录下载 ─────────────────────────────────────────────────

    def _download_directory(
        self, owner: str, repo: str, path: str, ref: str
    ) -> dict[str, str]:
        """下载 GitHub 目录中所有文件。

        优先 Git Trees API（1 次调用），Content API 递归兜底。
        SKILL.md 排除（已通过 raw URL 获取）。
        """
        files = self._download_via_tree(owner, repo, path, ref)
        if files is not None:
            return files
        logger.debug("Tree API unavailable for %s/%s, falling back to Contents", owner, repo)
        return self._download_recursive(owner, repo, path)

    def _download_via_tree(
        self, owner: str, repo: str, path: str, ref: str
    ) -> dict[str, str] | None:
        """通过 Git Trees API 下载整个目录（单次请求）。

        Returns:
            dict 或 {}（路径存在但没文件），None（回退到 Contents API）。
        """
        repo_full = f"{owner}/{repo}"
        cached = _TREE_CACHE.get(repo_full)
        if cached is None:
            branch, entries = self._fetch_repo_tree(owner, repo, ref)
            if branch is None:
                return None
            _TREE_CACHE[repo_full] = (branch, entries)
        else:
            _branch, entries = cached

        # 过滤目标路径下的 blob
        prefix = f"{path}/" if path else ""
        matching = [
            item for item in entries
            if item.get("type") == "blob"
            and (not prefix or item.get("path", "").startswith(prefix))
        ]
        if not matching:
            return {} if prefix else None  # 根目录空不算失败

        files: dict[str, str] = {}
        for item in matching:
            item_path = item["path"]
            rel_path = item_path[len(prefix):] if prefix else item_path
            if not rel_path or rel_path == "SKILL.md":
                continue
            # 跳过子目录中的文件（保留在路径中)
            content = self._fetch_file_content(owner, repo, item_path)
            if content is not None:
                files[rel_path] = content

        return files

    def _download_recursive(
        self, owner: str, repo: str, path: str
    ) -> dict[str, str]:
        """通过 Contents API 递归下载目录（兜底方案）。"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                logger.debug("Contents API returned %d for %s/%s", resp.status_code, owner, repo)
                return {}
        except requests.RequestException:
            return {}

        entries = resp.json()
        if not isinstance(entries, list):
            return {}

        files: dict[str, str] = {}
        for entry in entries:
            name = entry.get("name", "")
            entry_type = entry.get("type", "")

            if entry_type == "file":
                if name == "SKILL.md":
                    continue
                content = self._fetch_file_content(owner, repo, entry.get("path", ""))
                if content is not None:
                    files[name] = content
            elif entry_type == "dir":
                sub = self._download_recursive(owner, repo, entry.get("path", ""))
                for sub_name, sub_content in sub.items():
                    files[f"{name}/{sub_name}"] = sub_content

        return files

    def _fetch_repo_tree(
        self, owner: str, repo: str, ref: str
    ) -> tuple[str | None, list[dict]]:
        """获取 repo 的完整文件树。

        Returns:
            (default_branch, tree_entries) 或 (None, []) 失败时。
        """
        # 1. 获取默认分支的 tree sha
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            r = requests.get(repo_url, timeout=10)
            if r.status_code != 200:
                logger.debug("Repo API returned %d for %s/%s", r.status_code, owner, repo)
                return None, []
            repo_info = r.json()
            default_branch = repo_info.get("default_branch", ref)
        except requests.RequestException as e:
            logger.debug("Repo API failed for %s/%s: %s", owner, repo, e)
            return None, []

        # 2. 用 ref 或者默认分支获取 tree
        branch_ref = ref if ref != "main" else default_branch
        # 先获取该分支最新 commit 的 tree sha
        branch_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch_ref}?recursive=1"
        try:
            r = requests.get(branch_url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get("truncated"):
                    logger.debug("Tree API response truncated for %s/%s", owner, repo)
                    return default_branch, data.get("tree", [])
                return default_branch, data.get("tree", [])
            elif r.status_code == 404:
                # 可能 ref 不是有效的 tree sha，尝试先获取 commit
                commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch_ref}"
                try:
                    cr = requests.get(commit_url, timeout=10)
                    if cr.status_code == 200:
                        commit_sha = cr.json().get("sha", "")
                        tree_sha = cr.json().get("commit", {}).get("tree", {}).get("sha", "")
                        if tree_sha:
                            tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1"
                            tr = requests.get(tree_url, timeout=15)
                            if tr.status_code == 200:
                                tdata = tr.json()
                                return default_branch, tdata.get("tree", [])
                except requests.RequestException:
                    pass
            logger.debug("Tree API returned %d for %s/%s", r.status_code, owner, repo)
            return default_branch, []
        except requests.RequestException as e:
            logger.debug("Tree API failed for %s/%s: %s", owner, repo, e)
            return default_branch, []

    @staticmethod
    def _fetch_file_content(owner: str, repo: str, path: str) -> str | None:
        """获取单个文件内容。先用 raw URL，失败则用 Contents API。"""
        # 尝试 raw URL
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
        try:
            r = requests.get(raw_url, timeout=15)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass

        # 兜底：Contents API
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        try:
            r = requests.get(api_url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get("encoding") == "base64" and data.get("content"):
                    return base64.b64decode(data["content"]).decode("utf-8")
                return None
        except requests.RequestException as e:
            logger.debug("Fetch file failed %s/%s: %s", owner, repo, e)

        return None
