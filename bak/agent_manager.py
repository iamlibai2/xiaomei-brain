"""Multi-agent management with per-agent identity, memory, and talent.md system prompt."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .llm import LLMClient
from .memory import MemoryStore, EpisodicMemory
from .memory.layers import WorkingMemory
from .session import SessionManager
from .tools.registry import ToolRegistry


@dataclass
class AgentInstance:
    """A deployed agent instance with independent identity and resources.

    Each instance has:
    - id: unique identifier (e.g. "default", "xiaomei", "xiaoming")
    - name: display name (e.g. "小美", "小明")
    - talent.md: system prompt file, dynamically read at runtime
    - independent memory/, sessions/ directories
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
    memory: MemoryStore | None = None
    episodic_memory: EpisodicMemory | None = None
    session_manager: SessionManager | None = None
    working_memory: WorkingMemory | None = None

    # Agent-specific config overrides (optional)
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    # Talent file path
    talent_path: str = ""

    def get_system_prompt(self) -> str:
        """Dynamically read talent.md for system prompt."""
        if self.talent_path and os.path.exists(self.talent_path):
            with open(self.talent_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def agent_dir(self) -> str:
        """Return the agent's base directory (directory containing talent.md)."""
        if self.talent_path:
            return os.path.dirname(self.talent_path)
        return ""


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

    # Optional talent.md content (if not provided, defaults to global system_prompt)
    talent_content: str = ""

    # Tool config: list of tool names to enable for this agent
    enabled_tools: list[str] | None = None


class AgentManager:
    """Registry managing all AgentInstance objects.

    Reads agents from config.json (OpenClaw format).
    Directory structure:
        base_dir/
            config.json          # Agent definitions + config
            {agent_id}/
                talent.md        # Per-agent system prompt
                memory/          # Per-agent memory store
                sessions/        # Per-agent sessions
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
        return os.path.join(self.base_dir, "agents", agent_id)

    def _talent_path(self, agent_id: str) -> str:
        return os.path.join(self._agent_dir(agent_id), "talent.md")

    def _memory_dir(self, agent_id: str) -> str:
        return os.path.join(self._agent_dir(agent_id), "memory")

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
            talent_content = agent_data.get("talent", "")

            # Create agent directory and talent.md
            talent_path = self._talent_path(agent_id)
            if talent_content:
                os.makedirs(os.path.dirname(talent_path), exist_ok=True)
                with open(talent_path, "w", encoding="utf-8") as f:
                    f.write(talent_content)

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
                talent_path=talent_path,
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
        default_talent = self._talent_path("default")
        os.makedirs(os.path.dirname(default_talent), exist_ok=True)

        if global_config and global_config.system_prompt:
            if not os.path.exists(default_talent):
                with open(default_talent, "w", encoding="utf-8") as f:
                    f.write(global_config.system_prompt)

        instance = AgentInstance(
            id="default",
            name="小美",
            description="默认AI助手",
            enabled=True,
            created_at=time.time(),
            talent_path=default_talent,
        )
        self._agents["default"] = instance

    def _get_global_config(self) -> Config | None:
        """Get global config (lazy load from JSON)."""
        if self._global_config is None:
            try:
                self._global_config = Config.from_json()
            except Exception:
                pass
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

        talent_path = self._talent_path(agent_id)
        if config.talent_content:
            with open(talent_path, "w", encoding="utf-8") as f:
                f.write(config.talent_content)
        elif self._get_global_config() and self._get_global_config().system_prompt:
            with open(talent_path, "w", encoding="utf-8") as f:
                f.write(self._get_global_config().system_prompt)

        instance = AgentInstance(
            id=agent_id,
            name=config.name,
            description=config.description,
            avatar=config.avatar,
            enabled=config.enabled,
            created_at=time.time(),
            talent_path=talent_path,
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
        api_key = agent.api_key or global_config.api_key
        base_url = agent.base_url or global_config.base_url

        llm = LLMClient(
            model=model,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
        )

        tools = ToolRegistry()

        from .tools.builtin import (
            shell_tool, read_file_tool, write_file_tool,
            tts_tools, music_tools, image_tools, websearch_tools, webget_tools,
        )
        from .tools.builtin.memory import create_memory_tools

        tools.register(shell_tool)
        tools.register(read_file_tool)
        tools.register(write_file_tool)

        if global_config.tts_enabled:
            tts_api_key = global_config.tts_api_key or api_key
            if tts_api_key:
                from .speech import TTSProvider, VoiceConfig, AudioConfig
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
                tools.register(tts_tools.tts_speak_tool)
                tools.register(tts_tools.tts_speak_to_file_tool)

        if global_config.music_enabled:
            music_api_key = global_config.music_api_key or global_config.tts_api_key or api_key
            if music_api_key:
                from .speech import MusicProvider, MusicAudioConfig
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
            if image_api_key:
                from .image import ImageProvider, ImageConfig
                image_provider = ImageProvider(
                    api_key=image_api_key,
                    base_url=global_config.image_base_url,
                    config=ImageConfig(),
                )
                image_tools.set_image_provider(image_provider)
                tools.register(image_tools.image_generate_tool)

        if global_config.web_search_enabled and global_config.baidu_api_key:
            from .websearch import BaiduSearchProvider
            web_search_provider = BaiduSearchProvider(api_key=global_config.baidu_api_key)
            websearch_tools.set_search_provider(web_search_provider)
            tools.register(websearch_tools.web_search_tool)

        if global_config.web_get_enabled:
            from .webget import WebGetProvider
            web_get_provider = WebGetProvider()
            webget_tools.set_get_provider(web_get_provider)
            tools.register(webget_tools.web_get_tool)

        memory = MemoryStore(
            memory_dir=self._memory_dir(agent.id),
            max_topics=global_config.memory_max_topics,
            max_topic_chars=global_config.memory_max_topic_chars,
            min_score=global_config.memory_similarity_threshold,
        )
        episodic_memory = EpisodicMemory(memory_dir=self._memory_dir(agent.id))

        for mem_tool in create_memory_tools(memory, episodic_memory):
            tools.register(mem_tool)

        if register_tools_fn:
            register_tools_fn(tools)

        session_manager = SessionManager(session_dir=self._sessions_dir(agent.id))
        working_memory = WorkingMemory()

        agent.llm = llm
        agent.tools = tools
        agent.memory = memory
        agent.episodic_memory = episodic_memory
        agent.session_manager = session_manager
        agent.working_memory = working_memory

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
