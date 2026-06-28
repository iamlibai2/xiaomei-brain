"""技能加载器 — 管理技能生命周期（导入、索引、检索）。

基于 SkillStorage（SQLite + LanceDB），提供便捷的高层 API。

用法::

    loader = SkillLoader(
        skills_dir="~/.xiaomei-brain/xiaomei/skills",
        db_path="~/.xiaomei-brain/xiaomei/brain.db",
    )
    loader.scan()       # 从 SKILL.md 文件导入到数据库
    loader.build_index()  # 构建向量索引（Storage 内部处理）

    # 渐进式披露
    results = loader.list_skills(query="浏览器自动化")
    skill = loader.view_skill("browser-automation")
    loader.record_usage("browser-automation")
"""

from __future__ import annotations

import logging
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

    def __init__(self, skills_dir: str, db_path: str) -> None:
        self._skills_dir = Path(skills_dir)
        self._db_path = Path(db_path)
        self._storage: Any = None

    def _get_storage(self):
        """懒加载 SkillStorage（向量索引与 LongTermMemory 共用 LanceDB）。"""
        if self._storage is None:
            from .storage import SkillStorage
            self._storage = SkillStorage(db_path=self._db_path)
        return self._storage

    # ── 导入与索引 ───────────────────────────────────────────────

    def scan(self) -> list[Skill]:
        """从 skills_dir 导入 SKILL.md 文件到数据库。

        首次运行：导入所有文件并建向量索引。
        后续运行：增量更新（已有技能按名称更新，新技能追加）。
        """
        storage = self._get_storage()
        n = storage.import_from_dir(self._skills_dir)
        logger.info("SkillLoader: imported %d skills from %s", n, self._skills_dir)
        return []  # Phase 2 no longer returns Skill objects from scan

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
        storage = self._get_storage()
        return storage.list_skills(query=query, top_k=top_k)

    def view_skill(self, name: str) -> dict[str, Any] | None:
        """查看技能完整内容（Tier 1）。"""
        storage = self._get_storage()
        return storage.view_skill(name)

    def list_names(self) -> list[str]:
        """返回所有已加载的技能名称。"""
        storage = self._get_storage()
        return storage.list_names()

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

    def build_skill_index_prompt(self, query: str, top_k: int = 5) -> str:
        """生成注入 system prompt 的动态技能索引文本。

        embed(query) → LanceDB 语义召回 → 格式化 <available_skills> 块。
        """
        storage = self._get_storage()
        return storage.build_skill_index_prompt(query=query, top_k=top_k)
