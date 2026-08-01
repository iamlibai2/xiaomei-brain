"""Agent lifecycle management — single agent initialization.

Multi-agent discovery + CRUD is delegated to AgentRegistry.
"""

from __future__ import annotations

import logging
import os

from xiaomei_brain.agent.instance import AgentConfig, AgentInstance
from xiaomei_brain.agent.registry import AgentRegistry
from xiaomei_brain.base.config import Config
from xiaomei_brain.cli.boot import boot_section, boot_line
from xiaomei_brain.llm.client import LLMClient, set_log_agent
from xiaomei_brain.llm.types import load_config_providers
from xiaomei_brain.plugin.bootstrap import boot_plugins

logger = logging.getLogger(__name__)


class AgentManager:
    """Single agent lifecycle: build + initialize.

    Multi-agent discovery, CRUD, and config merge delegated to AgentRegistry.
    Public API unchanged — ``AgentManager().build_agent("xiaomei")`` still works.
    """

    def __init__(self, base_dir: str | None = None, config: Config | None = None):
        self.registry = AgentRegistry(base_dir)
        self._global_config: Config | None = config

    # ── Path utilities ──────────────────────────────────────────────

    def _agent_dir(self, agent_id: str) -> str:
        return self.registry.agent_dir(agent_id)

    def _sessions_dir(self, agent_id: str) -> str:
        return os.path.join(self._agent_dir(agent_id), "sessions")

    # ── Multi-agent ops (delegated to AgentRegistry) ──────────────────

    def get(self, agent_id: str) -> AgentInstance | None:
        """Get agent by ID from cache or discover from directory."""
        return self.registry.get(agent_id) or self.registry.discover(agent_id)

    def list(self) -> list[AgentInstance]:
        """List all enabled agents."""
        return self.registry.list_all()

    def register(self, config: AgentConfig) -> AgentInstance:
        """Register a new agent in memory and create its directory structure."""
        return self.registry.register(config)

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from memory (does not delete files)."""
        return self.registry.unregister(agent_id)

    def create_agent(
        self,
        name: str,
        copy_from: str = "",
        identity_content: str = "",
        brain_yaml_content: str = "",
        display_name: str = "",
        description: str = "",
        ws_port: int = -1,
    ) -> dict:
        """Create a new agent: directories + brain.yaml + identity.md + agent config.json.

        No longer modifies global config.json.
        """
        return self.registry.create_agent(
            name=name,
            copy_from=copy_from,
            identity_content=identity_content,
            brain_yaml_content=brain_yaml_content,
            display_name=display_name,
            description=description,
            ws_port=ws_port,
        )

    def delete_agent(self, agent_id: str) -> dict:
        """Delete an agent: memory + directory tree. No longer modifies global config.json."""
        return self.registry.delete_agent(agent_id)

    def clone_agent(self, source: str, target: str) -> dict:
        """Clone an agent: copy identity.md + brain.yaml + contacts."""
        return self.registry.clone_agent(source, target)

    def list_agents_info(self) -> list[dict]:
        """List all agent info (REST API)."""
        return self.registry.list_agents_info()

    def get_agent_info(self, agent_id: str) -> dict | None:
        """Get single agent info (REST API)."""
        return self.registry.get_agent_info(agent_id)

    def get_or_create(
        self, agent_id: str, config: AgentConfig | None = None
    ) -> AgentInstance:
        """Get existing agent or create new one."""
        return self.registry.get_or_create(agent_id, config)

    # ── Global config ────────────────────────────────────────────────

    def _get_global_config(self) -> Config | None:
        """Get global config (lazy load from JSON)."""
        if self._global_config is None:
            try:
                self._global_config = Config.from_json()
            except Exception as e:
                logger.debug("failed to load global config, returning None: %s", e)
        return self._global_config

    # ── Core: single agent initialization ────────────────────────────

    def init_agent(
        self,
        agent: AgentInstance,
        global_config: Config,
        register_tools_fn=None,
    ) -> AgentInstance:
        """Initialize lazy components of an agent instance.

        Uses registry.load_merged_config() for per-agent config overrides
        (providers, MCP, channels, bindings).
        """
        if agent.llm is not None:
            return agent

        provider = agent.provider or global_config.provider
        model = agent.model or global_config.model

        # 构建 PluginRegistry：先加载内置 provider 插件，再从 merged config 合并配置
        registry = boot_plugins(agent_id=agent.id)
        merged_config = self.registry.load_merged_config(agent.id)
        if merged_config:
            load_config_providers(registry, merged_config)

        # 解析 API key（优先级：agent 指定 → config.json provider 配置 → env var → 全局 fallback）
        api_key = ""
        # 1. 从 config.json _provider_configs 中获取该 provider 的专属 key
        if provider and provider in global_config._provider_configs:
            api_key = global_config._provider_configs[provider].get("api_key", "")
        # 2. 如果 config 里没有，尝试从 provider profile 的 env vars 获取
        prov_profile = registry.get_provider(provider)
        if not api_key and prov_profile:
            for env_var in prov_profile.env_vars:
                api_key = os.environ.get(env_var, "")
                if api_key:
                    break
        # 3. 最终 fallback：agent → 已解析的 key → 全局 config
        api_key = agent.api_key or api_key or global_config.api_key

        # 设置 LLM 日志目录
        set_log_agent(agent.id)

        masked = api_key[:8] + "****" + api_key[-4:] if len(api_key) > 12 else "***"
        logger.info("[init_agent] provider=%s model=%s api_key=%s base_url=%s",
                    provider, model, masked, prov_profile.base_url if prov_profile else "N/A")

        llm = LLMClient(
            provider=provider,
            model=model,
            registry=registry,
            api_key=api_key,
        )
        model_config = (
            merged_config.get("model", {})
            if isinstance(merged_config, dict)
            else {}
        )
        thinking_config = (
            model_config.get("thinking", {})
            if isinstance(model_config, dict)
            else {}
        )
        if isinstance(thinking_config, dict):
            llm.set_thinking(
                enabled=thinking_config.get("enabled"),
                effort=str(thinking_config.get("effort", "default")),
            )

        # 保存 PluginRegistry 到 agent 实例
        agent._registry = registry

        from xiaomei_brain.tools.registry import ToolRegistry
        tools = ToolRegistry()

        from xiaomei_brain.tools.builtin import (
            command_tool, read_tool, write_tool, edit_tool, glob_tool, grep_tool,
            process_tool,
            present_artifacts_tool,
            send_message_tool, check_inbox_tool, set_send_message_context,
            websearch_tools, webget_tools,
        )
        tools.register(command_tool)
        tools.register(read_tool)
        tools.register(write_tool)
        tools.register(edit_tool)
        tools.register(glob_tool)
        tools.register(grep_tool)
        tools.register(process_tool)
        tools.register(present_artifacts_tool)
        # Agent 间通讯 — send_message + check_inbox 工具
        from xiaomei_brain.plugins.channels.p2p.directory import AgentDirectory
        agent._directory = AgentDirectory()
        set_send_message_context(agent.id, agent._directory)
        tools.register(send_message_tool)
        tools.register(check_inbox_tool)

        # Generic URL fetching remains a core tool. Vendor-specific media and
        # search clients are initialized by their own plugins.
        from xiaomei_brain.tools.provider import WebGetProvider

        # ── Vision 视觉理解（perception 层） ──────────────────────────────
        if agent.vision_model and "/" in agent.vision_model:
            vis_provider, vis_model = agent.vision_model.split("/", 1)
            vis_api_key = ""
            if vis_provider in global_config._provider_configs:
                vis_api_key = global_config._provider_configs[vis_provider].get("api_key", "")
            vis_profile = registry.get_provider(vis_provider)
            if not vis_api_key and vis_profile:
                for ev in vis_profile.env_vars:
                    vis_api_key = os.environ.get(ev, "")
                    if vis_api_key:
                        break
            vis_api_key = vis_api_key or api_key
            vis_base_url = vis_profile.base_url if vis_profile else "https://api.minimaxi.com/v1"
            if vis_api_key:
                try:
                    agent.vision_llm = LLMClient(
                        provider=vis_provider,
                        model=vis_model,
                        registry=registry,
                        api_key=vis_api_key,
                    )
                except ValueError as exc:
                    logger.warning("[Vision] fallback model initialization failed: %s", exc)
                from xiaomei_brain.body.perception.vision import set_vision_config
                set_vision_config(api_key=vis_api_key, base_url=vis_base_url, model=vis_model)
                logger.info("[Vision] 已启用: %s/%s", vis_provider, vis_model)

        # ── Web Search Provider ─────────────────────────────────────────
        websearch_tools.set_registry(registry)

        if registry.get_web_search_providers():
            tools.register(websearch_tools.web_search_tool)

        if global_config.web_get_enabled:
            web_get_provider = WebGetProvider()
            webget_tools.set_get_provider(web_get_provider)
            tools.register(webget_tools.web_get_tool)

        # ── 加载插件工具 ────────────────────────────────────────────────
        for plugin_tool in registry.get_agent_tools():
            try:
                tools.register(plugin_tool)
            except ValueError:
                pass  # 插件工具和核心工具同名时跳过

        if register_tools_fn:
            register_tools_fn(tools)

        # ── 加载 MCP Server 工具 ────────────────────────────────────────
        from xiaomei_brain.mcp.client import bootstrap_mcp_servers, register_config_listener, _on_config_changed

        mcp_config = merged_config
        servers_cfg = (mcp_config or {}).get("mcp_servers", {})
        enabled_servers = [n for n, c in servers_cfg.items() if isinstance(c, dict) and c.get("enabled", True)]
        if enabled_servers:
            boot_section("MCP 工具")

            def _on_mcp_status(name, ok, tool_count, error=None):
                label = name if len(name) <= 20 else name[:17] + "..."
                if ok:
                    boot_line(label, "OK", f"{tool_count} 个工具")
                else:
                    boot_line(label, "FAIL", error or "连接失败")

            bootstrap_mcp_servers(tools, mcp_config, on_status=_on_mcp_status)
        else:
            bootstrap_mcp_servers(tools, mcp_config)
        register_config_listener(tools)

        # ── 启动 config.json 热重载（监听全局 + agent 两个文件）────────────
        from xiaomei_brain.base.config import ConfigReloader
        _reloader = ConfigReloader(os.path.expanduser("~/.xiaomei-brain/config.json"))
        _reloader.add_listener(_on_config_changed)
        _reloader.start()

        # 同时监听 agent 自己的 config.json
        agent_config_path = os.path.join(self._agent_dir(agent.id), "config.json")
        if os.path.exists(agent_config_path):
            _agent_reloader = ConfigReloader(agent_config_path)
            _agent_reloader.add_listener(_on_config_changed)
            _agent_reloader.start()

        # ── 注册延迟绑定工具（依赖 ConsciousLiving 后期初始化的组件）─────
        from xiaomei_brain.tools.builtin.dag_expand import create_dag_tools
        for dag_tool in create_dag_tools(agent):
            tools.register(dag_tool)

        from xiaomei_brain.tools.builtin.thought_search import create_thought_tools
        for thought_tool in create_thought_tools(agent):
            tools.register(thought_tool)

        from xiaomei_brain.tools.builtin.memory_search import create_memory_search_tools
        for ms_tool in create_memory_search_tools(agent):
            tools.register(ms_tool)

        from xiaomei_brain.tools.builtin.goal import create_goal_tools
        for goal_tool in create_goal_tools(agent):
            tools.register(goal_tool)

        # Assignment is the durable agreement with a Person. Goal/PACE stays
        # the Agent's private planning layer underneath that agreement.
        from xiaomei_brain.assignments import create_assignment_tools
        for assignment_tool in create_assignment_tools(agent):
            tools.register(assignment_tool)

        from xiaomei_brain.tools.builtin.being import create_being_tool
        tools.register(create_being_tool(agent))

        from xiaomei_brain.tools.builtin.pleasure import create_pleasure_lever
        tools.register(create_pleasure_lever(agent))

        from xiaomei_brain.schedule import create_cron_tools
        for cron_tool in create_cron_tools(agent):
            tools.register(cron_tool)

        from xiaomei_brain.tools.builtin.manage_session import create_session_tool
        tools.register(create_session_tool(agent))

        from xiaomei_brain.tools.builtin.clarify import create_clarify_tool
        tools.register(create_clarify_tool(agent))

        # ── 全局 Embedding 初始化（必须在 SkillStorage / DynamicToolLoader 之前）──
        from xiaomei_brain.base.shared_embedder import SharedEmbedder
        SharedEmbedder.get_or_create(model_name=global_config.embedding_model)

        # ── 技能系统 ──────────────────────────────────────────────────
        from xiaomei_brain.skills import SkillLoader, create_skill_tools
        skills_dir = os.path.join(self._agent_dir(agent.id), "skills")
        brain_db_path = os.path.join(self._agent_dir(agent.id), "memory", "brain.db")

        # 兼容 .agents/skills/ 生态（npx skills add 的标准安装路径）
        extra_dirs = []
        for candidate in [".agents/skills", "../.agents/skills"]:
            p = os.path.abspath(candidate)
            if os.path.isdir(p):
                extra_dirs.append(p)
        extra_dirs.extend(registry.get_skill_directories())

        boot_section("技能系统")
        skill_loader = SkillLoader(
            skills_dir=skills_dir,
            db_path=brain_db_path,
            extra_dirs=extra_dirs,
        )
        try:
            skill_loader.scan()
            skill_names = skill_loader.list_names()
            boot_line("加载技能", "OK", f"{len(skill_names)} 个" if skill_names else "空")
        except Exception:
            logger.exception("[技能系统] 加载失败")
            boot_line("加载技能", "FAIL", "扫描或向量索引出错，已跳过")
            skill_names = []
        agent._skill_loader = skill_loader
        for skill_tool in create_skill_tools(agent):
            tools.register(skill_tool)

        # ── 用户能力体系 ──────────────────────────────────────────────
        # Build the business-level registry before the dynamic Tool index so
        # capability_status participates in normal semantic retrieval.
        from xiaomei_brain.capabilities import (
            CapabilityConfigurationService,
            CapabilityRegistry,
            create_capability_tools,
        )
        capability_configuration = CapabilityConfigurationService(
            os.path.join(self._agent_dir(agent.id), "config.json")
        )
        from xiaomei_brain.tool_services import ToolServiceConfigurationService
        tool_service_configuration = ToolServiceConfigurationService(
            agent.id,
            base_dir=self.registry.base_dir,
        )
        capability_registry = CapabilityRegistry(
            plugin_registry=registry,
            tool_registry=tools,
            skill_loader=skill_loader,
            configuration=capability_configuration,
            tool_service_configuration=tool_service_configuration,
        )
        agent._capability_registry = capability_registry
        for capability_tool in create_capability_tools(agent):
            tools.register(capability_tool)

        # ── 动态工具加载 ───────────────────────────────────────────────
        dynamic_cfg = {}
        if merged_config:
            dynamic_cfg = merged_config.get("xiaomei_brain", {}).get("tools", {}).get("dynamic", {})
        if dynamic_cfg.get("enabled", True):
            from xiaomei_brain.tools.dynamic import DynamicToolLoader, set_active_loader
            top_k = dynamic_cfg.get("top_k", 10)
            lance_path = os.path.join(self._agent_dir(agent.id), "memory", "lancedb")
            boot_section("工具索引")
            loader = DynamicToolLoader(tools, top_k=top_k, lance_db_path=lance_path)
            loader.build_index()
            total_tools = len(tools.list_tools())
            boot_line("向量索引", "OK", f"{total_tools} 个工具")
            agent._dynamic_loader = loader
            set_active_loader(loader)

        capability_registry.bind_dynamic_tool_loader(
            getattr(agent, "_dynamic_loader", None)
        )
        capability_views = capability_registry.list()
        ready_count = sum(
            view.status.value in {"ready", "degraded"}
            for view in capability_views
        )
        boot_section("能力体系")
        boot_line(
            "可用能力",
            "OK",
            f"{ready_count}/{len(capability_views)} 项",
        )

        from xiaomei_brain.agent.session import SessionManager
        session_manager = SessionManager(session_dir=self._sessions_dir(agent.id))

        # ── 赋值 ─────────────────────────────────────────────────────────
        agent.llm = llm
        agent.tools = tools
        agent.session_manager = session_manager

        return agent

    def build_agent(
        self,
        agent_id: str,
        global_config: Config | None = None,
        register_tools_fn=None,
    ) -> AgentInstance:
        """Convenience: discover + init + return an agent."""
        agent = self.get(agent_id)
        if agent is None:
            if agent_id == "default":
                self.registry._ensure_default_agent()
                agent = self.get(agent_id)
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found")

        if agent.llm is None:
            gcfg = global_config or self._get_global_config()
            if gcfg is None:
                gcfg = Config()
            self.init_agent(agent, gcfg, register_tools_fn)

        return agent
