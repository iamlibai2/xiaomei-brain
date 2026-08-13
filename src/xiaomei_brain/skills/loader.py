"""技能加载器 — 管理技能生命周期（导入、索引、检索）。

基于 SkillStorage（SQLite + LanceDB），提供便捷的高层 API。

用法::

    loader = SkillLoader(
        skills_dir="~/.xiaomei-brain/{agent_id}/skills",
        db_path="~/.xiaomei-brain/{agent_id}/memory/brain.db",
    )
    loader.scan()       # 从 SKILL.md 文件导入到数据库
    loader.build_index()  # 构建向量索引（Storage 内部处理）

    # 渐进式披露
    results = loader.list_skills(query="web scraping")
    skill = loader.view_skill("web-artifacts-builder")
    loader.record_usage("web-artifacts-builder")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能 — SKILL.md 的内存表示。"""

    name: str
    description: str
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    path: str = ""
    dir_name: str = ""
    content: str = ""
    tool_bindings: list[str] = field(default_factory=list)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)

    def to_embedding_text(self) -> str:
        tags_str = " ".join(self.tags)
        return f"{self.name}: {self.description} {tags_str}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "dir_name": self.dir_name,
        }


class SkillLoader:
    """技能加载器 — 封装 SkillStorage，提供渐进式披露。

    - list_skills() → Tier 0 元数据
    - view_skill()  → Tier 1 完整内容
    - record_usage() → 记录使用，驱动排序
    """

    def __init__(
        self,
        skills_dir: str,
        db_path: str,
        extra_dirs: list[str] | None = None,
    ) -> None:
        self._skills_dir = Path(skills_dir)
        self._db_path = Path(db_path)
        self._extra_dirs: list[Path] = [Path(d) for d in (extra_dirs or [])]
        self._storage: Any = None
        self._disabled_names: set[str] = set()
        self._package_disabled_names: set[str] = set()
        self._scan_lock = threading.RLock()
        self._source_snapshot: tuple[tuple[str, int, int], ...] | None = None

    def set_disabled_names(self, names: set[str] | list[str]) -> None:
        """Hide capability-owned Skills without deleting their stored data."""
        self._disabled_names = {str(name).strip() for name in names if str(name).strip()}

    def set_package_disabled_names(self, names: set[str] | list[str]) -> None:
        """Hide Skills left in storage by packages not loaded for this Agent."""
        self._package_disabled_names = {
            str(name).strip() for name in names if str(name).strip()
        }

    def _effective_disabled_names(self) -> set[str]:
        return self._disabled_names | self._package_disabled_names

    def _get_storage(self):
        """懒加载 SkillStorage（向量索引与 LongTermMemory 共用 LanceDB）。"""
        if self._storage is None:
            from .storage import SkillStorage
            self._storage = SkillStorage(db_path=self._db_path)
        return self._storage

    # ── 导入与索引 ───────────────────────────────────────────────

    def scan(self) -> list[Skill]:
        """从 skills_dir + extra_dirs 导入 SKILL.md 文件到数据库。

        首次运行：导入所有文件并建向量索引。
        后续运行：增量更新（已有技能按名称更新，新技能追加）。
        extra_dirs（如 .agents/skills/）的技能导入 but 不覆盖同名已有技能。
        """
        with self._scan_lock:
            storage = self._get_storage()

            # Import lower-priority shared/package Skills first. Later directories
            # win name conflicts, and Agent-local Skills are imported last.
            for extra_dir in self._extra_dirs:
                if extra_dir.is_dir():
                    m = storage.import_from_dir(extra_dir)
                    if m:
                        logger.info("SkillLoader: imported %d skills from %s", m, extra_dir)
                else:
                    logger.debug("SkillLoader: extra dir not found: %s", extra_dir)

            n = storage.import_from_dir(self._skills_dir)
            logger.info("SkillLoader: imported %d Agent-local skills from %s", n, self._skills_dir)
            self._source_snapshot = self._snapshot_sources()

        return []  # Phase 2 no longer returns Skill objects from scan

    def _snapshot_sources(self) -> tuple[tuple[str, int, int], ...]:
        """Return a cheap fingerprint of every discoverable SKILL.md file."""
        files: list[tuple[str, int, int]] = []
        for root in [*self._extra_dirs, self._skills_dir]:
            if not root.is_dir():
                continue
            for path in root.rglob("SKILL.md"):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
        return tuple(sorted(files))

    def refresh_if_changed(self) -> bool:
        """Import newly installed or edited Skill files without restarting."""
        with self._scan_lock:
            current = self._snapshot_sources()
            if self._source_snapshot is not None and current == self._source_snapshot:
                return False
            self.scan()
            return True

    def build_index(self) -> None:
        """构建向量索引（已在 import_from_dir 中自动完成，此处为兼容旧 API）。"""
        self._get_storage()
        logger.info("SkillLoader: index built (via SkillStorage)")

    def rebuild(self) -> None:
        """重建索引 — 重新导入 SKILL.md 文件。"""
        self.scan()

    # ── 检索 ─────────────────────────────────────────────────────

    def list_skills(self, query: str = "", top_k: int = 10) -> list[dict[str, Any]]:
        """列出技能元数据（Tier 0）。

        Args:
            query: 语义搜索查询，为空则返回所有（按使用频率排序）
            top_k: 返回数量
        """
        self.refresh_if_changed()
        storage = self._get_storage()
        disabled_names = self._effective_disabled_names()
        results = storage.list_skills(
            query=query,
            top_k=max(top_k, top_k + len(disabled_names)),
        )
        return [item for item in results if item.get("name") not in disabled_names][:top_k]

    def view_skill(self, name: str) -> dict[str, Any] | None:
        """查看技能完整内容（Tier 1）。"""
        self.refresh_if_changed()
        if name in self._effective_disabled_names():
            return None
        storage = self._get_storage()
        skill = storage.view_skill(name)
        if not skill:
            return None
        skill = dict(skill)
        content = str(skill.get("content") or "")
        resource_root = str(skill.get("resource_root") or "").strip()
        if resource_root:
            resource_context = "\n".join([
                "<skill_resources>",
                f"root: {resource_root}",
                "Relative paths such as scripts/, assets/, references/, "
                "templates/ and examples/ are relative to this root, not to "
                "the Agent Workspace. Use an absolute path built from this root.",
                "Do not search for bundled Skill resources in the Agent Workspace.",
                "</skill_resources>",
            ])
            skill["runtime_content"] = f"{resource_context}\n\n{content}"
        else:
            skill["runtime_content"] = content
        return skill

    def resource_roots(self) -> list[str]:
        """Return every installed Skill package root for read-only tool access."""
        self.refresh_if_changed()
        return self._get_storage().list_resource_roots()

    def list_names(self) -> list[str]:
        """返回所有已加载的技能名称。"""
        self.refresh_if_changed()
        storage = self._get_storage()
        disabled_names = self._effective_disabled_names()
        return [name for name in storage.list_names() if name not in disabled_names]

    # ── 写操作 ──────────────────────────────────────────────────

    def record_usage(self, name: str) -> None:
        """记录技能使用（增加使用计数）。"""
        storage = self._get_storage()
        storage.record_usage(name)

    def add_skill(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str] | None = None,
        tool_bindings: list[str] | None = None,
    ) -> int:
        """手动添加技能。"""
        storage = self._get_storage()
        return storage.add_skill(
            name=name, description=description, content=content,
            tags=tags, tool_bindings=tool_bindings,
        )

    def remove_skill(self, name: str) -> bool:
        """删除技能。"""
        storage = self._get_storage()
        return storage.remove_skill(name)

    def build_skill_index_prompt(
        self,
        query: str,
        top_k: int = 3,
        required_names: list[str] | tuple[str, ...] | None = None,
    ) -> str:
        """生成注入 system prompt 的动态技能索引文本。

        embed(query) → LanceDB 语义召回 → 格式化 <available_skills> 块。
        """
        prompt, _selection = self.build_skill_index_prompt_with_selection(
            query,
            top_k=top_k,
            required_names=required_names,
        )
        return prompt

    def build_skill_index_prompt_with_selection(
        self,
        query: str,
        top_k: int = 3,
        required_names: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Build the Skill index and return the exact candidates used."""
        skills: list[dict[str, Any]] = []
        seen: set[str] = set()
        for name in required_names or ():
            skill = self.view_skill(str(name))
            if skill and skill["name"] not in seen:
                skills.append(skill)
                seen.add(skill["name"])
        for skill in self.list_skills(query=query, top_k=top_k):
            # Prefetch must stay conservative. Active ``discover`` still
            # returns nearby candidates when no reliable Skill is found.
            distance = skill.get("_distance")
            if distance is not None and float(distance) > 0.82:
                continue
            if skill["name"] not in seen:
                skills.append(skill)
                seen.add(skill["name"])
        required = {str(name) for name in (required_names or ())}
        selection = [
            {
                "name": str(skill.get("name") or ""),
                "description": str(skill.get("description") or "")[:300],
                "source": "capability" if str(skill.get("name") or "") in required else "semantic",
            }
            for skill in skills
        ]
        if not skills:
            return "", selection
        lines = [
            "\n<技能>",
            "在回复前先浏览以下技能。如果某个技能与当前任务明确相关，"
            "你必须用 skill_view(技能名) 加载该技能并严格按其指示执行。"
            "不要因为它只是语义上的近邻就加载；不确定时使用 discover 主动搜索。"
            "技能包含针对特定任务的深入知识——API 端点、工具专用命令和经过验证的"
            "高效工作流程，优于通用方法。即使你觉得用基础工具就能处理，也先加载技能——"
            "因为技能定义了该任务在此环境中的正确做法。"
            "技能可能包含你的项目记忆、用户偏好或之前确定的约定，"
            "忽略它们意味着丢失上下文。遇到困难或需要反复尝试的任务，"
            "完成后请主动提出将其保存为技能。"
            "如果确实没有相关技能，可以跳过。",
            "<available_skills>",
        ]
        for skill in skills:
            tags = f" [{', '.join(skill.get('tags', []))}]" if skill.get("tags") else ""
            lines.append(f"  - {skill['name']}: {skill['description']}{tags}")
        lines.extend([
            "</available_skills>",
            "使用 skill_view(name) 加载技能完整内容。",
            "</技能>",
        ])
        return "\n".join(lines), selection
