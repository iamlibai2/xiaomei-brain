"""知名 Skill 站点及安装命令适配器。"""

from __future__ import annotations

import html
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .base import BaseSourceAdapter, SourceBundle


_SKILLS_SH = re.compile(
    r"^https?://(?:www\.)?skills\.sh/([^/]+)/([^/]+)/([^/?#]+)", re.IGNORECASE
)
_KNOWN_COMMAND = re.compile(
    r"^(?:npx\s+)?skills\s+add\s+|^skillhub\s+install\s+", re.IGNORECASE
)
_GITHUB_REPOSITORY = re.compile(
    r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_INSTALL_COMMAND_IN_HTML = re.compile(
    r"(?:npx\s+skills\s+add|skillhub\s+install)\s+[^<\r\n]+", re.IGNORECASE
)
_LINK = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def _split_command(command: str) -> list[str]:
    value = command.strip()
    if value.startswith("$"):
        value = value[1:].strip()
    if any(marker in value for marker in ("&&", "||", ";", "|", ">", "<", "`")):
        raise ValueError("Skill 安装命令不能包含管道、重定向或多条命令")
    return shlex.split(value, posix=True)


def _read_installed_bundle(root: Path, identifier: str) -> SourceBundle:
    manifests = list(root.rglob("SKILL.md"))
    if len(manifests) != 1:
        raise ValueError(
            f"安装命令应产生一个 Skill，实际发现 {len(manifests)} 个 SKILL.md"
        )
    manifest = manifests[0]
    skill_root = manifest.parent
    files: dict[str, str | bytes] = {}
    for path in skill_root.rglob("*"):
        if not path.is_file() or path == manifest:
            continue
        relative = path.relative_to(skill_root).as_posix()
        raw = path.read_bytes()
        try:
            files[relative] = raw.decode("utf-8")
        except UnicodeDecodeError:
            files[relative] = raw
    return SourceBundle(
        content=manifest.read_text(encoding="utf-8"),
        source="skillhub",
        identifier=identifier,
        resolved_url=identifier,
        files=files,
    )


def _fetch_with_skills_cli(
    repository: str, skill_name: str, identifier: str
) -> SourceBundle:
    """在隔离临时目录中调用官方 skills CLI，并只读取指定 Skill。"""
    executable = shutil.which("npx") or shutil.which("npx.cmd")
    if not executable:
        raise RuntimeError(
            "直接下载失败，且当前主机没有 npx，无法使用官方 skills CLI 兜底"
        )
    with tempfile.TemporaryDirectory(prefix="xiaomei-skills-") as temp:
        command = [executable, "--yes", "skills", "add", repository]
        if skill_name:
            command.extend(["--skill", skill_name])
        command.extend(["--agent", "codex", "--copy", "--yes"])
        completed = subprocess.run(
            command,
            cwd=temp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"skills CLI 获取失败: {detail}")
        bundle = _read_installed_bundle(Path(temp), identifier)
        bundle.source = "skills_cli"
        bundle.resolved_url = repository
        bundle.metadata["skill_name"] = skill_name
        return bundle


class MarketplaceSourceAdapter(BaseSourceAdapter):
    """解析 skills.sh、SkillHub 页面和受支持的安装命令。"""

    def can_handle(self, identifier: str) -> bool:
        value = identifier.strip()
        if _KNOWN_COMMAND.search(value):
            return True
        if _GITHUB_REPOSITORY.match(value):
            return True
        host = urlparse(value).hostname or ""
        return host.lower() in {
            "skills.sh", "www.skills.sh", "skillhub.cloud.tencent.com"
        }

    def resolve(self, identifier: str) -> str:
        return identifier.strip()

    def fetch(self, identifier: str) -> SourceBundle:
        value = identifier.strip()
        if _KNOWN_COMMAND.search(value):
            return self._fetch_command(value)
        match = _SKILLS_SH.match(value)
        if match:
            owner, repo, skill_name = match.groups()
            repository = f"https://github.com/{owner}/{repo}"
            bundle = _fetch_with_skills_cli(repository, skill_name, identifier)
            bundle.source = "skills.sh"
            bundle.identifier = identifier
            bundle.metadata["catalog_url"] = value
            return bundle
        github_repo = _GITHUB_REPOSITORY.match(value)
        if github_repo:
            owner, repo = github_repo.groups()
            repository = f"https://github.com/{owner}/{repo}"
            bundle = _fetch_with_skills_cli(repository, "", identifier)
            bundle.source = "github_cli"
            return bundle
        return self._fetch_catalog_page(value)

    def _fetch_command(self, command: str) -> SourceBundle:
        args = _split_command(command)
        lowered = [arg.lower() for arg in args]
        if lowered[:3] == ["npx", "skills", "add"]:
            args = args[1:]
            lowered = lowered[1:]
        if lowered[:2] == ["skills", "add"]:
            if len(args) < 3:
                raise ValueError("skills add 缺少仓库地址")
            repository = args[2]
            skill_name = ""
            for index, arg in enumerate(args[3:], start=3):
                if arg in {"--skill", "-s"} and index + 1 < len(args):
                    skill_name = args[index + 1]
                    break
            if skill_name:
                return _fetch_with_skills_cli(repository, skill_name, command)
            return _fetch_with_skills_cli(repository, "", command)

        if lowered[:2] != ["skillhub", "install"] or len(args) < 3:
            raise ValueError("仅支持 npx skills add 和 skillhub install 安装命令")
        executable = shutil.which("skillhub")
        if not executable:
            raise RuntimeError(
                "当前主机未安装 SkillHub CLI，无法执行 skillhub install；"
                "可改用该 Skill 的 SKILL.md、ZIP 或 GitHub 地址"
            )
        package = args[2]
        with tempfile.TemporaryDirectory(prefix="xiaomei-skillhub-") as temp:
            completed = subprocess.run(
                [executable, "install", package, "--dir", temp],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"SkillHub 安装失败: {detail}")
            return _read_installed_bundle(Path(temp), command)

    def _fetch_catalog_page(self, url: str) -> SourceBundle:
        response = requests.get(url, timeout=30, allow_redirects=True)
        response.raise_for_status()
        body = html.unescape(response.text)
        command = _INSTALL_COMMAND_IN_HTML.search(body)
        if command:
            return self._fetch_command(command.group(0).strip())
        for href in _LINK.findall(body):
            target = urljoin(url, href)
            lowered = target.lower().split("?", 1)[0]
            if lowered.endswith("skill.md") or lowered.endswith(".zip"):
                from .url import URLSourceAdapter
                return URLSourceAdapter().fetch(target)
        raise ValueError(
            "该 Skill 页面没有暴露可识别的安装命令、SKILL.md 或 ZIP 下载地址"
        )
