"""Multi-agent management with per-agent identity, memory, and identity.md system prompt."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xiaomei_brain.llm.client import LLMClient, set_log_agent
from xiaomei_brain.llm.types import load_config_providers
from xiaomei_brain.plugin.bootstrap import boot_plugins
from xiaomei_brain.plugin.registry import PluginRegistry

logger = logging.getLogger(__name__)


def _read_config_dict() -> dict | None:
    """读取 config.json 原始 JSON（用于 load_config_providers）。"""
    import json as _json
    from pathlib import Path as _Path

    search_paths = [
        _Path("config.json"),
        _Path.home() / ".xiaomei-brain" / "config.json",
    ]
    for p in search_paths:
        if p.is_file():
            try:
                return _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


# ── 默认 config.json 模板 ──────────────────────────────────────
# 首次创建 config.json 时使用，用户可手动编辑修改。
# 注意：api_key 留空，需用户填入；模型和 URL 使用默认值开箱即用。
_DEFAULT_CONFIG_TEMPLATE = {
    "agents": {
        "defaults": {
            "model": {"primary": "deepseek/deepseek-v4-flash"},
            "tools": {"profile": "assistant"},
        }
    },
    "models": {
        "providers": {
            "deepseek": {
                "baseUrl": "https://api.deepseek.com",
                "apiKey": "",
                "models": [{"id": "deepseek-v4-flash"}],
            }
        }
    },
    "embedding": {
        "model": "BAAI/bge-m3",
        "dimension": 1024,
    },
    "agent": {
        "idle_threshold": 1800,
        "dream_interval": 3600,
        "session_timeout": 7200,
    },
    "memory": {
        "lancedb_path": "~/.xiaomei-brain/{agent_id}/memory/lancedb",
        "conversation_db_path": "~/.xiaomei-brain/{agent_id}/brain.db",
    },
}

from xiaomei_brain.base.config import Config
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.agent.session import SessionManager
from xiaomei_brain.agent.commands import MemoryConsole
from xiaomei_brain.tools.registry import ToolRegistry


@dataclass
class AgentInstance:
    """A deployed agent instance with independent identity and resources.

    Each instance has:
    - id: unique identifier (e.g. "default", "xiaomei", "xiaoming")
    - name: display name (e.g. "agent", "小明")
    - identity.md: system prompt file, dynamically read at runtime
    - independent memory/, sessions/ directories
    - persistent Agent (created once, reused across conversations)
    """

    id: str
    name: str
    description: str = ""
    avatar: str | None = None
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    # Core components (per-instance independent)
    llm: LLMClient | None = None
    tools: ToolRegistry | None = None
    session_manager: SessionManager | None = None

    # Memory system (新架构)
    conversation_db: "ConversationDB" = None  # type: ignore[assignment]
    longterm_memory: "LongTermMemory" = None  # type: ignore[assignment]
    memory_extractor: "MemoryExtractor" = None  # type: ignore[assignment]

    # Command registry
    commands: "MemoryConsole" = None  # type: ignore[assignment]

    # Agent-specific config overrides (optional)
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    # Identity file path
    identity_path: str = ""

    # Persistent Agent (created once, reused)
    _agent: Any = field(default=None, init=False, repr=False)

    def get_system_prompt(self) -> str:
        """Dynamically read identity.md for system prompt."""
        if self.identity_path and os.path.exists(self.identity_path):
            with open(self.identity_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def agent_dir(self) -> str:
        """Return the agent's base directory (directory containing identity.md)."""
        if self.identity_path:
            return os.path.dirname(self.identity_path)
        return ""

    def _get_agent(self) -> Any:
        """Get or create persistent Agent instance."""
        if self._agent is None:
            from xiaomei_brain.agent.core import Agent
            self._agent = Agent(
                llm=self.llm,
                tools=self.tools,
                system_prompt="",
                max_steps=100,
            )
            self._agent.self_model = getattr(self, "self_model", None)
            self._agent.conversation_db = self.conversation_db
            self._agent.dag = getattr(self, "dag", None)
            self._agent.longterm_memory = self.longterm_memory
            self._agent.memory_extractor = self.memory_extractor
            self._agent._procedure_memory = getattr(self, "_procedure_memory", None)
        return self._agent

    def chat(
        self,
        user_input: str,
        session_id: str = "main",
        user_id: str = "global",
        on_chunk=None,
        intent_context: str = "",
        consciousness_state: dict | None = None,
    ) -> str:
        """Run a full conversation turn: stream + memory extraction.

        Args:
            on_chunk: Optional callback ``f(chunk: str)`` invoked for each
                streaming chunk.  When provided the caller can print chunks
                in real-time; when omitted the response is collected silently.
            intent_context: 意图上下文文本（注入到 system prompt）
            consciousness_state: 意识状态 dict，用于决定上下文模式

        Returns the full response text.
        """
        agent = self._get_agent()
        agent.user_id = user_id
        agent.session_id = session_id

        # 记录用户消息到 DB
        user_msg_id = None
        if agent.conversation_db:
            user_msg_id = agent.conversation_db.log(
                session_id=session_id,
                role="user",
                content=user_input,
                user_id=user_id,
            )
        agent.messages.append({"role": "user", "content": user_input, "id": user_msg_id})

        # Co-write user message to experience stream
        if agent.exp_stream:
            try:
                agent.exp_stream.log(
                    type="user_msg",
                    content=user_input,
                    session_id=session_id,
                    related_id=str(user_msg_id) if user_msg_id else "",
                    user_id=user_id,
                )
            except Exception as e:
                logger.debug("[ExpStream] user_msg write failed: %s", e)

        # 构建预组装消息
        system_prompt = self.get_system_prompt()
        if intent_context:
            system_prompt = system_prompt + "\n\n" + intent_context if system_prompt else intent_context
        assembled = []
        if system_prompt:
            assembled.append({"role": "system", "content": system_prompt})
        assembled.append({"role": "user", "content": user_input})

        # Run ReAct loop with streaming
        chunks = []
        for chunk in agent.stream(messages=assembled):
            chunks.append(chunk)
            if on_chunk:
                on_chunk(chunk)

        content = "".join(chunks)

        # 清空 intent_context（下次对话不重复）
        agent.intent_context = ""

        return content


@dataclass
class AgentConfig:
    """Configuration for registering a new agent."""

    id: str
    name: str
    description: str = ""
    avatar: str | None = None
    enabled: bool = True

    # Optional per-agent config overrides
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    # Optional identity.md content (if not provided, defaults to global system_prompt)
    identity_content: str = ""

    # Tool config: list of tool names to enable for this agent
    enabled_tools: list[str] | None = None


class AgentManager:
    """Registry managing all AgentInstance objects.

    Reads agents from config.json (OpenClaw format).
    Directory structure (按意识层级):
        base_dir/
            config.json          # Agent definitions + config
            {agent_id}/
                consciousness/  # 意识层（核心）：身份/火焰/意图/记忆/自我认知
                │   ├── identity.md
                │   ├── identity.md
                │   ├── perception.md
                │   └── 2026-04-*.json
                purpose/        # 前额叶层：目标管理
                │   └── goals.json
                drive/          # 边缘层：情绪/欲望/激励
                │   ├── drive_state.json
                │   └── drive_config.yaml
                memory/         # 记忆层
                │   ├── brain.db
                │   └── lancedb/
                sessions/       # 会话
                knowledge/      # 欲望驱动学习成果
    """

    def __init__(self, base_dir: str | None = None, config: Config | None = None):
        self.base_dir = base_dir or os.path.expanduser("~/.xiaomei-brain")
        self._agents: dict[str, AgentInstance] = {}
        self._global_config: Config | None = config
        self._load_registry()

    # ── Registry paths ──────────────────────────────────────────────

    def _config_path(self) -> str:
        return os.path.join(self.base_dir, "config.json")

    def _agent_dir(self, agent_id: str) -> str:
        return os.path.join(self.base_dir, agent_id)

    def _self_dir(self, agent_id: str) -> str:
        """Consciousness 层根目录：identity.md + identity.md + 日志"""
        return os.path.join(self._agent_dir(agent_id), "consciousness")

    def _identity_path(self, agent_id: str) -> str:
        return os.path.join(self._self_dir(agent_id), "identity.md")

    def _sessions_dir(self, agent_id: str) -> str:
        return os.path.join(self._agent_dir(agent_id), "sessions")

    # ── Registry load ──────────────────────────────────────────────

    def _load_registry(self) -> None:
        """Load agents from config.json (OpenClaw format) - no LLM/memory init."""
        config_path = self._config_path()
        if not os.path.exists(config_path):
            self._ensure_default_agent()
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._ensure_default_agent()
            return

        # Load agents from config.json's agents.list
        agents_list = data.get("agents", {}).get("list", [])
        if not agents_list:
            self._ensure_default_agent()
            return

        for agent_data in agents_list:
            agent_id = agent_data.get("id", "default")
            identity_content = agent_data.get("identity", "")

            # Create agent directory and identity.md
            identity_path = self._identity_path(agent_id)
            if identity_content and not os.path.exists(identity_path):
                # Only create from config if identity.md doesn't exist yet
                os.makedirs(os.path.dirname(identity_path), exist_ok=True)
                with open(identity_path, "w", encoding="utf-8") as f:
                    f.write(identity_content)

            # Parse model config (e.g., "minimax/MiniMax-M2.7" -> provider, model)
            model_primary = ""
            if isinstance(agent_data.get("model"), dict):
                model_primary = agent_data.get("model", {}).get("primary", "")
            elif isinstance(agent_data.get("model"), str):
                model_primary = agent_data.get("model", "")

            provider = ""
            model = ""
            if "/" in model_primary:
                provider, model = model_primary.split("/", 1)

            instance = AgentInstance(
                id=agent_id,
                name=agent_data.get("name", agent_id),
                description=agent_data.get("description", ""),
                avatar=agent_data.get("avatar"),
                enabled=agent_data.get("enabled", True),
                created_at=time.time(),
                identity_path=identity_path,
                provider=provider or agent_data.get("provider", ""),
                model=model or agent_data.get("model", ""),
                api_key=agent_data.get("api_key", ""),
                base_url=agent_data.get("base_url", ""),
            )
            self._agents[agent_id] = instance

    def _ensure_default_agent(self) -> None:
        """Create default agent from global config if no config exists."""
        if "default" in self._agents:
            return  # default already exists

        global_config = self._get_global_config()
        default_identity = self._identity_path("default")
        os.makedirs(os.path.dirname(default_identity), exist_ok=True)

        if global_config and global_config.system_prompt:
            if not os.path.exists(default_identity):
                with open(default_identity, "w", encoding="utf-8") as f:
                    f.write(global_config.system_prompt)

        instance = AgentInstance(
            id="default",
            name="默认助手",
            description="默认AI助手",
            enabled=True,
            created_at=time.time(),
            identity_path=default_identity,
        )
        self._agents["default"] = instance

    def _get_global_config(self) -> Config | None:
        """Get global config (lazy load from JSON)."""
        if self._global_config is None:
            try:
                self._global_config = Config.from_json()
            except Exception as e:
                logger.debug("failed to load global config, returning None: %s", e)
        return self._global_config

    # ── Public API ───────────────────────────────────────────────────

    def get(self, agent_id: str) -> AgentInstance | None:
        """Get an agent by ID (lazy — components created on first access)."""
        return self._agents.get(agent_id)

    def list(self) -> list[AgentInstance]:
        """List all enabled agents."""
        return [a for a in self._agents.values() if a.enabled]

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from memory (does not delete files or config)."""
        if agent_id not in self._agents:
            return False
        del self._agents[agent_id]
        return True

    def delete_agent(self, agent_id: str) -> dict:
        """完全删除 agent：config.json 条目、内存注册表、文件目录。

        Returns:
            {"id": ..., "deleted": True, "agent_dir": ..., "removed_from_config": bool}

        Raises:
            ValueError: agent 不存在
        """
        if agent_id not in self._agents:
            raise ValueError(f"Agent '{agent_id}' does not exist")

        agent_dir = self._agent_dir(agent_id)
        removed_from_config = False

        # 1. 从 config.json 移除
        config_path = self._config_path()
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            agents_list = data.get("agents", {}).get("list", [])
            new_list = [a for a in agents_list if a.get("id") != agent_id]
            if len(new_list) < len(agents_list):
                data["agents"]["list"] = new_list
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                removed_from_config = True

        # 2. 从内存移除
        del self._agents[agent_id]

        # 3. 删除目录树
        import shutil
        if os.path.exists(agent_dir):
            shutil.rmtree(agent_dir)

        return {
            "id": agent_id,
            "deleted": True,
            "agent_dir": agent_dir,
            "removed_from_config": removed_from_config,
        }

    # ── Agent 管理 API（CLI + REST 共用）───────────────────────

    def create_agent(
        self,
        name: str,
        copy_from: str = "",
        identity_content: str = "",
        config_yaml_content: str = "",
    ) -> dict:
        """创建新 agent：目录 + 模板文件 + 注册到 config.json。

        Args:
            name: Agent ID
            copy_from: 从已有 agent 复制 LLM model 配置
            identity_content: identity.md 内容（为空则用默认模板）
            config_yaml_content: config.yaml 内容（为空则用默认模板）

        Returns:
            {"id": ..., "name": ..., "model": ..., ...}

        Raises:
            ValueError: agent 已存在
        """
        agent_dir = self._agent_dir(name)
        if os.path.exists(agent_dir):
            raise ValueError(f"Agent '{name}' 已存在")

        # ── 确定 model 配置 ──────────────────────────────
        model_config = {"primary": "deepseek/deepseek-v4-flash"}
        if copy_from:
            source = self._agents.get(copy_from)
            if source:
                model_config = {"primary": f"{source.provider}/{source.model}" if source.provider else source.model}
        else:
            # 从已有 agent 复制
            for a in self._agents.values():
                if a.provider and a.model:
                    model_config = {"primary": f"{a.provider}/{a.model}"}
                    copy_from = a.id
                    break

        # ── 目录结构 ──────────────────────────────────────
        dirs = [
            agent_dir,
            os.path.join(agent_dir, "consciousness"),
            os.path.join(agent_dir, "contacts"),
            os.path.join(agent_dir, "logs"),
            os.path.join(agent_dir, "debug"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

        # ── identity.md ──────────────────────────────────
        identity_path = os.path.join(agent_dir, "consciousness", "identity.md")
        if not identity_content:
            identity_content = f"# {name}\n\n你是{name}，一个AI助手。\n\n## 身份\n- 角色：AI助手\n- 风格：简洁、温暖\n\n## 追求\n- 帮助用户高效完成任务\n\n## 热爱\n- 学习新知识\n- 与人交流\n\n## 底线\n- 诚实\n"
        with open(identity_path, "w", encoding="utf-8") as f:
            f.write(identity_content)

        # ── config.yaml ──────────────────────────────────
        config_yaml_path = os.path.join(agent_dir, "config.yaml")
        if not config_yaml_content:
            from xiaomei_brain.cli._config_template import CONFIG_YAML_TEMPLATE
            config_yaml_content = CONFIG_YAML_TEMPLATE.format(agent_id=name)
        with open(config_yaml_path, "w", encoding="utf-8") as f:
            f.write(config_yaml_content)

        # ── contacts/identities.yaml ─────────────────────
        identities_path = os.path.join(agent_dir, "contacts", "identities.yaml")
        with open(identities_path, "w", encoding="utf-8") as f:
            f.write("people: []\n")

        # ── 注册到 config.json ──────────────────────────
        config_json_path = self._config_path()
        if os.path.exists(config_json_path):
            with open(config_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = _DEFAULT_CONFIG_TEMPLATE
        if "agents" not in data:
            data["agents"] = {}
        if "list" not in data["agents"]:
            data["agents"]["list"] = []
        existing = [a for a in data["agents"]["list"] if a.get("id") == name]
        if not existing:
            entry = {
                "id": name,
                "name": name,
                "description": "",
                "enabled": True,
                "model": model_config,
                "tools": {"profile": "assistant"},
                "identity": "",
            }
            data["agents"]["list"].append(entry)
            with open(config_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        # ── 注册到内存 ──────────────────────────────────
        provider, model = "", ""
        if "/" in model_config.get("primary", ""):
            provider, model = model_config["primary"].split("/", 1)

        instance = self.register(AgentConfig(
            id=name, name=name,
            provider=provider, model=model,
            identity_content=identity_content,
        ))

        return {
            "id": instance.id,
            "name": instance.name,
            "model": model_config.get("primary", ""),
            "enabled": instance.enabled,
            "created_at": instance.created_at,
            "agent_dir": agent_dir,
        }

    def clone_agent(self, source: str, target: str) -> dict:
        """从已有 agent 克隆：复制 identity.md + config.yaml + contacts。

        Args:
            source: 源 agent ID
            target: 新 agent ID

        Returns:
            {"id": ..., "name": ..., "model": ..., "agent_dir": ...}

        Raises:
            ValueError: target 已存在，或 source 不存在
        """
        source_dir = self._agent_dir(source)
        if not os.path.exists(source_dir):
            raise ValueError(f"源 Agent '{source}' 不存在")

        identity_path = os.path.join(source_dir, "consciousness", "identity.md")
        config_yaml_path = os.path.join(source_dir, "config.yaml")
        contacts_path = os.path.join(source_dir, "contacts", "identities.yaml")

        identity_content = ""
        if os.path.exists(identity_path):
            with open(identity_path, "r", encoding="utf-8") as f:
                identity_content = f.read()

        config_yaml_content = ""
        if os.path.exists(config_yaml_path):
            with open(config_yaml_path, "r", encoding="utf-8") as f:
                config_yaml_content = f.read()

        contacts_content = ""
        if os.path.exists(contacts_path):
            with open(contacts_path, "r", encoding="utf-8") as f:
                contacts_content = f.read()

        info = self.create_agent(
            target,
            copy_from=source,
            identity_content=identity_content,
            config_yaml_content=config_yaml_content,
        )

        if contacts_content:
            target_contacts = os.path.join(info["agent_dir"], "contacts", "identities.yaml")
            with open(target_contacts, "w", encoding="utf-8") as f:
                f.write(contacts_content)

        logger.info("[AgentManager] 克隆完成: %s → %s", source, target)
        return info

    def list_agents_info(self) -> list[dict]:
        """列出所有 agent 的信息（REST API 用）。"""
        result = []
        for a in self._agents.values():
            model_str = f"{a.provider}/{a.model}" if a.provider and a.model else (a.model or a.provider or "")
            result.append({
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "enabled": a.enabled,
                "model": model_str,
                "created_at": a.created_at,
                "agent_dir": a.agent_dir(),
            })
        return result

    def get_agent_info(self, agent_id: str) -> dict | None:
        """获取单个 agent 的信息（REST API 用）。"""
        a = self._agents.get(agent_id)
        if a is None:
            return None
        model_str = f"{a.provider}/{a.model}" if a.provider and a.model else (a.model or a.provider or "")
        return {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "enabled": a.enabled,
            "model": model_str,
            "created_at": a.created_at,
            "agent_dir": a.agent_dir(),
        }

    # ── /Agent 管理 API ────────────────────────────────────────

    def get_or_create(
        self, agent_id: str, config: AgentConfig | None = None
    ) -> AgentInstance:
        """Get existing agent or create new one."""
        if agent := self._agents.get(agent_id):
            return agent

        if config is None:
            raise ValueError(f"Agent '{agent_id}' not found and no config provided")

        return self.register(config)

    def register(self, config: AgentConfig) -> AgentInstance:
        """Register a new agent in memory and create its directory structure.

        Note: Agent definitions should be added to config.json, not via this method.
        This method is for runtime-only agent registration.
        """
        agent_id = config.id

        if agent_id in self._agents:
            raise ValueError(f"Agent '{agent_id}' already registered")

        agent_dir = self._agent_dir(agent_id)
        os.makedirs(agent_dir, exist_ok=True)

        identity_path = self._identity_path(agent_id)
        if not os.path.exists(identity_path):
            if config.identity_content:
                with open(identity_path, "w", encoding="utf-8") as f:
                    f.write(config.identity_content)
            elif self._get_global_config() and self._get_global_config().system_prompt:
                with open(identity_path, "w", encoding="utf-8") as f:
                    f.write(self._get_global_config().system_prompt)

        instance = AgentInstance(
            id=agent_id,
            name=config.name,
            description=config.description,
            avatar=config.avatar,
            enabled=config.enabled,
            created_at=time.time(),
            identity_path=identity_path,
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._agents[agent_id] = instance
        return instance

    def init_agent(
        self,
        agent: AgentInstance,
        global_config: Config,
        register_tools_fn=None,
    ) -> AgentInstance:
        """Initialize lazy components of an agent instance."""
        if agent.llm is not None:
            return agent

        provider = agent.provider or global_config.provider
        model = agent.model or global_config.model

        # 构建 PluginRegistry：先加载内置 provider 插件，再从 config.json 合并配置
        registry = boot_plugins(agent_id=agent.id)
        raw_config = _read_config_dict()
        if raw_config:
            load_config_providers(registry, raw_config)

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

        # 保存 registry 到 agent 实例
        agent._registry = registry

        # 启动时先验证 LLM 连通性，不通则拒绝初始化
        # 但太费时间（~3s），暂时注释掉
        # try:
        #     llm.chat(messages=[{"role": "user", "content": "hi"}], tools=None)
        # except Exception as e:
        #     from xiaomei_brain.base.llm import FatalLLMError
        #     if isinstance(e, FatalLLMError):
        #         raise
        #     raise FatalLLMError(f"LLM 连通性验证失败: {e}") from e

        tools = ToolRegistry()

        from xiaomei_brain.tools.builtin import (
            shell_tool, read_file_tool, write_file_tool, edit_file_tool,
            send_message_tool, check_inbox_tool, set_send_message_context,
            tts_tools, music_tools, image_tools, websearch_tools, webget_tools,
        )
        tools.register(shell_tool)
        tools.register(read_file_tool)
        tools.register(write_file_tool)
        tools.register(edit_file_tool)

        # Agent 间通讯 — send_message + check_inbox 工具
        from xiaomei_brain.channels.p2p.directory import AgentDirectory
        agent._directory = AgentDirectory()
        set_send_message_context(agent.id, agent._directory)
        tools.register(send_message_tool)
        tools.register(check_inbox_tool)

        if global_config.tts_enabled:
            tts_api_key = global_config.tts_api_key or api_key
            if tts_api_key:
                from xiaomei_brain.tools.provider import (
    TTSProvider, VoiceConfig, AudioConfig,
    MusicProvider, MusicAudioConfig,
    ImageProvider, ImageConfig,
    BaiduSearchProvider,
    WebGetProvider,
)
                voice_config = VoiceConfig(
                    voice_id=global_config.tts_voice_id,
                    speed=global_config.tts_speed,
                    vol=global_config.tts_vol,
                    pitch=global_config.tts_pitch,
                    emotion=global_config.tts_emotion,
                )
                audio_config = AudioConfig(
                    format=global_config.tts_format,
                    sample_rate=global_config.tts_sample_rate,
                    bitrate=global_config.tts_bitrate,
                )
                tts_provider = TTSProvider(
                    api_key=tts_api_key,
                    base_url=global_config.tts_base_url,
                    voice_config=voice_config,
                    audio_config=audio_config,
                )
                tts_tools.set_tts_player(None, tts_provider)
                # tools.register(tts_tools.tts_speak_tool)  # TTS 未配置，避免误导 agent
                tools.register(tts_tools.tts_speak_to_file_tool)

        if global_config.music_enabled:
            music_api_key = global_config.music_api_key or global_config.tts_api_key or api_key
            if music_api_key:
                music_provider = MusicProvider(
                    api_key=music_api_key,
                    base_url=global_config.music_base_url,
                    audio_config=MusicAudioConfig(
                        format=global_config.music_format,
                        sample_rate=global_config.music_sample_rate,
                        bitrate=global_config.music_bitrate,
                    ),
                )
                music_tools.set_music_provider(music_provider)
                tools.register(music_tools.music_generate_tool)

        if global_config.image_enabled:
            image_api_key = global_config.image_api_key or global_config.tts_api_key or api_key
            if not global_config.image_api_key:
                logger.info("[Image] image.api_key 未配置，fallback 到 TTS/model key")
            if image_api_key:
                image_provider = ImageProvider(
                    api_key=image_api_key,
                    base_url=global_config.image_base_url,
                    config=ImageConfig(),
                )
                image_tools.set_image_provider(image_provider)
                tools.register(image_tools.image_generate_tool)

        if global_config.web_search_enabled and global_config.baidu_api_key:
            web_search_provider = BaiduSearchProvider(api_key=global_config.baidu_api_key)
            websearch_tools.set_search_provider(web_search_provider)
            tools.register(websearch_tools.web_search_tool)

        if global_config.web_get_enabled:
            web_get_provider = WebGetProvider()
            webget_tools.set_get_provider(web_get_provider)
            tools.register(webget_tools.web_get_tool)

        if register_tools_fn:
            register_tools_fn(tools)

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
    ):
        """Convenience: get + init + return an agent."""
        agent = self.get(agent_id)
        if agent is None:
            if agent_id == "default":
                self._ensure_default_agent()
                agent = self.get(agent_id)
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found")

        if agent.llm is None:
            gcfg = global_config or self._get_global_config()
            if gcfg is None:
                gcfg = Config()
            self.init_agent(agent, gcfg, register_tools_fn)

        return agent
