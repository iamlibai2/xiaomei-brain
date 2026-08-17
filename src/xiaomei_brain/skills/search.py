"""外部 Skill 结构化搜索。"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import requests


def _search_skills_sh(query: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    """调用官方 skills CLI 使用的非交互搜索接口。"""
    try:
        response = requests.get(
            "https://skills.sh/api/search",
            params={"q": query, "limit": limit},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return [], f"unavailable: {type(exc).__name__}"

    results: list[dict[str, Any]] = []
    for item in payload.get("skills", []):
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("id") or "").strip().strip("/")
        if not skill_id:
            continue
        results.append({
            "name": str(item.get("name") or skill_id.rsplit("/", 1)[-1]),
            "description": str(item.get("description") or item.get("summary") or ""),
            "source_name": "skills.sh",
            "publisher": str(item.get("source") or ""),
            "installs": int(item.get("installs") or 0),
            "version": str(item.get("version") or ""),
            "detail_url": f"https://skills.sh/{skill_id}",
            "learn_source": f"https://skills.sh/{skill_id}",
        })
    results.sort(key=lambda item: item["installs"], reverse=True)
    return results[:limit], "ok"


def _skillhub_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("skills", "results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _search_skillhub(query: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    """调用主机上已安装的 SkillHub CLI；未安装时不自动安装。"""
    executable = shutil.which("skillhub") or shutil.which("skillhub.exe")
    if not executable:
        return [], "not_installed"
    try:
        completed = subprocess.run(
            [executable, "search", query, "--limit", str(limit), "--json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"unavailable: {type(exc).__name__}"
    if completed.returncode != 0:
        return [], f"error: exit_code={completed.returncode}"
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return [], "error: invalid_json"

    results: list[dict[str, Any]] = []
    for item in _skillhub_items(payload):
        namespace = str(item.get("namespace") or "").strip()
        slug = str(item.get("slug") or item.get("name") or "").strip()
        coordinate = str(item.get("coordinate") or "").strip()
        if not coordinate:
            coordinate = f"{namespace}/{slug}" if namespace else slug
        if not coordinate:
            continue
        results.append({
            "name": str(item.get("displayName") or item.get("name") or slug),
            "description": str(item.get("summary") or item.get("description") or ""),
            "source_name": "skillhub",
            "publisher": namespace,
            "installs": int(item.get("installs") or item.get("downloadCount") or 0),
            "version": str(item.get("version") or ""),
            "detail_url": str(item.get("url") or ""),
            "learn_source": f"skillhub install {coordinate}",
        })
    return results[:limit], "ok"


def find_external_skills(query: str, *, limit: int = 8) -> dict[str, Any]:
    """搜索已接入的结构化 Skill 源，并返回统一候选。"""
    normalized = str(query or "").strip()
    if len(normalized) < 2:
        raise ValueError("query 至少需要 2 个字符")
    bounded_limit = max(1, min(int(limit), 20))
    skills_sh, skills_sh_status = _search_skills_sh(normalized, bounded_limit)
    skillhub, skillhub_status = _search_skillhub(normalized, bounded_limit)

    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*skills_sh, *skillhub]:
        key = str(item.get("learn_source") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        combined.append(item)
        if len(combined) >= bounded_limit:
            break

    web_search_recommended = len(combined) < min(3, bounded_limit)
    return {
        "query": normalized,
        "results": combined,
        "count": len(combined),
        "sources": {
            "skills.sh": skills_sh_status,
            "skillhub": skillhub_status,
        },
        "web_search_recommended": web_search_recommended,
        "web_search_hint": (
            f"搜索 {normalized} Agent Skill SKILL.md GitHub，并比较来源可信度和内容"
            if web_search_recommended else ""
        ),
        "next_step": (
            "候选不足，可自行调用 web_search 扩大范围；找到合适来源后调用 learn_skill。"
            if web_search_recommended
            else "比较候选的相关性、来源和安装量，选择后调用 learn_skill。"
        ),
    }
