"""技能系统 — 标准 SKILL.md 格式的技能加载、存储与检索。

架构：
- SkillStorage: SQLite 元数据 + LanceDB 向量索引
- SkillLoader: 高层 API，管理技能生命周期
- tools: skills_list / skill_view Agent 工具

渐进式披露：
- skills_list() → Tier 0 元数据（名称、描述、标签、工具绑定、使用统计）
- skill_view()  → Tier 1 完整 SKILL.md 内容（自动记录使用）

用法::

    from xiaomei_brain.skills import SkillLoader, create_skill_tools

    loader = SkillLoader(
        skills_dir="~/.xiaomei-brain/xiaomei/skills",
        db_path="~/.xiaomei-brain/xiaomei/brain.db",
    )
    loader.scan()

    for t in create_skill_tools(agent):
        tools.register(t)
"""

from .loader import SkillLoader, Skill
from .storage import SkillStorage
from .tools import create_skill_tools

__all__ = ["SkillLoader", "Skill", "SkillStorage", "create_skill_tools"]
