"""技能工具 — 发现、读取和创建当前 Agent 的 Skill。

渐进式披露：
- skills_list: 列出所有可用技能，支持语义搜索，显示使用频率和工具绑定
- skill_view: 查看指定技能的完整 SKILL.md 内容，自动记录使用
- create_skill: 从受控 Workspace 安装或更新 Agent 自己编写的 Skill
- find_skill: 从结构化 Skill 生态搜索候选
- learn_skill: 从外部来源学习、校验、安装并热加载 Skill

用法::

    from xiaomei_brain.skills.tools import create_skill_tools
    for t in create_skill_tools(agent):
        tools.register(t)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..tools.base import Tool, tool
from ..tools.execution_context import current_tool_execution
from .authoring import install_authored_skill, install_external_skill
from .resources import activate_skill_resource_root
from .search import find_external_skills
from .sources import resolve_source

if TYPE_CHECKING:
    from ..agent.instance import AgentInstance

logger = logging.getLogger(__name__)


def create_skill_tools(agent: "AgentInstance") -> list[Tool]:
    """创建 Skill 发现、读取和创建工具。

    延迟绑定模式：工具调用时从 agent 身上获取 SkillLoader 引用。
    """

    def _loader():
        return getattr(agent, "_skill_loader", None)

    def _refresh_installed_skill(loader, name: str) -> dict:
        loader.refresh_if_changed()
        skill = loader.view_skill(name)
        if not skill:
            raise RuntimeError(f"Skill 已写入但热加载失败: {name}")
        configure_paths = getattr(agent, "configure_tool_paths", None)
        agent_dir = getattr(agent, "agent_dir", None)
        if callable(configure_paths) and callable(agent_dir):
            base_dir = agent_dir()
            if base_dir:
                configure_paths(base_dir, extra_read_only_roots=loader.resource_roots())
        return skill

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
            logger.debug("Failed to record skill usage for '%s'", name, exc_info=True)

        lines = [
            f"# {skill['name']}",
            f"版本: {skill.get('version', '1.0.0')}",
        ]

        # Skill 是带资源的只读包，不只是被复制进数据库的一段 Markdown。
        # 相对资源路径属于 Skill 根目录，绝不能按 Agent Workspace 解析。
        # 选中 Skill 后仅开放它自己的根目录，供后续文件工具只读访问。
        resource_root = str(skill.get("resource_root") or "").strip()
        if resource_root:
            activate_skill_resource_root(agent, skill)
            lines.extend([
                "",
                "## Skill 资源目录",
                f"只读根目录: {resource_root}",
                "SKILL.md 中的 scripts/、assets/、references/、templates/、"
                "examples/ 等相对路径都必须相对于这个根目录解析。",
                "不要在 Agent Workspace 中搜索或猜测这些 Skill 自带资源；"
                "执行脚本或读取资源时请使用上面的根目录组成绝对路径。",
            ])
        if skill.get("tags"):
            lines.append(f"标签: {', '.join(skill['tags'])}")

        # 工具绑定
        bindings = skill.get("tool_bindings", [])
        if bindings:
            lines.append(f"依赖工具: {', '.join(bindings)}")

        # 使用统计
        if bindings:
            dynamic_loader = getattr(agent, "_dynamic_loader", None)
            activate = getattr(dynamic_loader, "activate_required_tools", None)
            if callable(activate):
                activation = activate(bindings)
                missing = (
                    activation[1]
                    if isinstance(activation, tuple) and len(activation) == 2
                    else []
                )
                if missing:
                    lines.append(
                        "Unavailable required tools: " + ", ".join(missing)
                    )

        if skill.get("usage_count", 0) > 0:
            lines.append(f"使用次数: {skill['usage_count']}")

        lines.append(f"\n## 描述\n{skill['description']}")
        if skill.get("content"):
            lines.append(f"\n---\n{skill['content']}")

        return "\n".join(lines)

    @tool(
        name="create_skill",
        description=(
            "把当前 Agent Workspace 中已经写好的 Skill 目录安装或更新为当前 Agent 的作业指南。"
            "适合把经过讨论形成的长期工作方法、领域知识和执行策略保存为 Skill；"
            "它不会创建能力包、不会新增程序工具，也不会重启 Agent。"
            "源目录根部必须有 SKILL.md，可包含 scripts、templates、references 等资源。"
            "如为某个 preparing Mission 编写指南，可传 mission_id 同时绑定该 Skill；"
            "绑定不会自动激活 Mission，也不会授予外部发布、付费或删除权限。"
        ),
    )
    def create_skill(source_dir: str, mission_id: str = "") -> str:
        loader = _loader()
        if not loader:
            raise RuntimeError("技能系统未初始化")
        context = current_tool_execution()
        if context is None or not context.workspace_root:
            raise RuntimeError("create_skill 只能在 Agent 的受控 Workspace 中执行")
        raw_source = Path(str(source_dir or "").strip())
        if not str(raw_source) or raw_source.is_absolute():
            raise ValueError("source_dir 必须是 Workspace 相对目录")

        installed = install_authored_skill(
            source_dir=Path(context.workspace_root) / raw_source,
            workspace_root=Path(context.workspace_root),
            skills_dir=loader.skills_dir,
            tool_registry=context.tool_registry,
        )
        _refresh_installed_skill(loader, installed.name)

        bound_mission: dict | None = None
        normalized_mission_id = str(mission_id or "").strip()
        if normalized_mission_id:
            mission_service = getattr(agent, "mission_service", None)
            if mission_service is None:
                raise RuntimeError("Mission 系统尚未初始化，Skill 已安装但未绑定")
            mission = mission_service.update_definition(
                normalized_mission_id,
                skill_name=installed.name,
            )
            bound_mission = mission.to_dict()

        return json.dumps({
            "success": True,
            "skill": {
                "name": installed.name,
                "description": installed.description,
                "version": installed.version,
                "requires_tools": list(installed.requires_tools),
                "install_dir": str(installed.install_dir),
            },
            "hot_loaded": True,
            "restart_required": False,
            "mission": bound_mission,
            "message": (
                "Skill 已安装并立即生效；Mission 已绑定但仍需显式激活。"
                if bound_mission else "Skill 已安装并立即生效。"
            ),
        }, ensure_ascii=False)

    @tool(
        name="find_skill",
        description=(
            "按任务或领域搜索外部标准 Skill。当前搜索 skills.sh，并在本机存在 SkillHub CLI 时"
            "同时搜索 SkillHub；返回候选名称、来源、安装量和可直接交给 learn_skill 的 source。"
            "它只搜索和比较，不安装。如果结果不足或结构化来源不可用，结果会建议你自行调用"
            "web_search 扩大范围；找到合适候选后再调用 learn_skill。"
        ),
    )
    def find_skill(query: str, limit: int = 8) -> str:
        return json.dumps(
            find_external_skills(query, limit=limit),
            ensure_ascii=False,
        )

    @tool(
        name="learn_skill",
        description=(
            "从可信外部来源获取并安装一个标准 Skill，安装后立即热加载，无需重启 Agent。"
            "source 支持 GitHub、skills.sh、腾讯 SkillHub、直接 SKILL.md/ZIP 地址，"
            "以及 npx skills add 或 skillhub install 安装命令。也可使用用户指定的网页；"
            "网页必须公开可识别的安装命令或标准 Skill 下载地址。"
            "当现有技能不足、当前任务反复失败，或你判断值得借鉴外部成熟经验时使用；"
            "应先搜索并比较来源，再安装最合适的一项。安装成功后必须用 skill_view 阅读完整指南，"
            "并在真实任务中验证效果。安装只写入 Skill 文件，不会自动执行其中脚本。"
        ),
    )
    def learn_skill(source: str) -> str:
        loader = _loader()
        if not loader:
            raise RuntimeError("技能系统未初始化")
        source = str(source or "").strip()
        if not source:
            raise ValueError("source 不能为空")
        context = current_tool_execution()
        registry = context.tool_registry if context is not None else None
        adapter = resolve_source(source)
        bundle = adapter.fetch(source)
        installed = install_external_skill(
            content=bundle.content,
            files=bundle.files,
            skills_dir=loader.skills_dir,
            tool_registry=registry,
        )
        _refresh_installed_skill(loader, installed.name)
        return json.dumps({
            "success": True,
            "skill": {
                "name": installed.name,
                "description": installed.description,
                "version": installed.version,
                "requires_tools": list(installed.requires_tools),
                "install_dir": str(installed.install_dir),
            },
            "source": {
                "type": bundle.source,
                "identifier": bundle.identifier,
                "resolved_url": bundle.resolved_url,
            },
            "hot_loaded": True,
            "restart_required": False,
            "next_step": f"使用 skill_view(name='{installed.name}') 阅读完整指南，并在当前任务中验证。",
        }, ensure_ascii=False)

    return [skills_list, skill_view, create_skill, find_skill, learn_skill]
