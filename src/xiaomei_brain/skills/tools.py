"""技能工具 — skills_list（Tier 0 元数据）和 skill_view（Tier 1 完整内容）。

渐进式披露：
- skills_list: 列出所有可用技能，支持语义搜索，显示使用频率和工具绑定
- skill_view: 查看指定技能的完整 SKILL.md 内容，自动记录使用

用法::

    from xiaomei_brain.skills.tools import create_skill_tools
    for t in create_skill_tools(agent):
        tools.register(t)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..tools.base import Tool, tool

if TYPE_CHECKING:
    from ..agent.instance import AgentInstance

logger = logging.getLogger(__name__)


def create_skill_tools(agent: "AgentInstance") -> list[Tool]:
    """创建技能工具 — skills_list 和 skill_view。

    延迟绑定模式：工具调用时从 agent 身上获取 SkillLoader 引用。
    """

    def _loader():
        return getattr(agent, "_skill_loader", None)

    @tool(
        name="skills_list",
        description=(
            "列出本地可用的技能。技能是'如何做某事'的程序性知识（区别于工具是'能做什么'）。"
            "当你不确定如何完成一个任务时先查技能列表。"
            "支持语义搜索：提供 query 参数按描述搜索相关技能。"
        ),
    )
    def skills_list(query: str = "", top_k: int = 10) -> str:
        """列出可用技能（Tier 0 元数据）。

        Args:
            query: 搜索查询，为空则返回所有技能（按使用频率排序）
            top_k: 返回的最大技能数
        """
        loader = _loader()
        if not loader:
            return "技能系统未初始化。"

        results = loader.list_skills(query=query, top_k=top_k)
        if not results:
            return "没有找到技能。" if query else "当前没有任何可用技能。"

        lines = [f"共 {len(results)} 个技能:"]
        for s in results:
            parts = [f"  - **{s['name']}**"]
            if s.get("version"):
                parts.append(f" v{s['version']}")
            parts.append(f": {s['description']}")

            # 标签
            if s.get("tags"):
                parts.append(f"  [{', '.join(s['tags'])}]")

            # 使用统计
            if s.get("usage_count", 0) > 0:
                parts.append(f"  (使用 {s['usage_count']} 次)")

            # 工具绑定
            bindings = s.get("tool_bindings", [])
            if bindings:
                parts.append(f"  依赖工具: {', '.join(bindings)}")

            lines.append("".join(parts))

        if query:
            lines.append(f"\n(基于查询 '{query}' 的语义搜索结果)")
        return "\n".join(lines)

    @tool(
        name="skill_view",
        description=(
            "查看指定技能的完整 SKILL.md 内容（Tier 1）。"
            "技能内容包含使用场景、步骤说明、依赖工具、注意事项等详细信息。"
            "先通过 skills_list 找到需要的技能名称，再用 skill_view 查看详情。"
            "查看后自动记录使用统计。"
        ),
    )
    def skill_view(name: str) -> str:
        """查看技能完整内容。

        Args:
            name: 技能名称（从 skills_list 获取）
        """
        loader = _loader()
        if not loader:
            return "技能系统未初始化。"

        skill = loader.view_skill(name)
        if not skill:
            available = loader.list_names()
            hint = f"可用的技能: {', '.join(available)}" if available else "当前没有任何可用技能"
            return f"未找到技能 '{name}'。{hint}。"

        # 记录使用
        try:
            loader.record_usage(name)
        except Exception:
            pass

        lines = [
            f"# {skill['name']}",
            f"版本: {skill.get('version', '1.0.0')}",
        ]
        if skill.get("tags"):
            lines.append(f"标签: {', '.join(skill['tags'])}")

        # 工具绑定
        bindings = skill.get("tool_bindings", [])
        if bindings:
            lines.append(f"依赖工具: {', '.join(bindings)}")

        # 使用统计
        if skill.get("usage_count", 0) > 0:
            lines.append(f"使用次数: {skill['usage_count']}")

        lines.append(f"\n## 描述\n{skill['description']}")
        if skill.get("content"):
            lines.append(f"\n---\n{skill['content']}")

        return "\n".join(lines)

    return [skills_list, skill_view]
