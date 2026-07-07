"""Agent instance & config — shared types for registry and manager."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


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
    llm: Any = None  # LLMClient
    tools: Any = None  # ToolRegistry
    session_manager: Any = None  # SessionManager

    # Memory system (新架构)
    conversation_db: Any = None  # ConversationDB
    longterm_memory: Any = None  # LongTermMemory
    memory_extractor: Any = None  # MemoryExtractor

    # Command registry
    commands: Any = None  # MemoryConsole

    # Agent-specific config overrides (optional)
    provider: str = ""
    model: str = ""
    vision_model: str = ""      # e.g. "minimax/MiniMax-M3"
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
            import logging
            if self.tools is None:
                logging.getLogger(__name__).warning(
                    "[AgentInstance] _get_agent() called before init_agent() set self.tools. "
                    "llm=%s agent_id=%s",
                    self.llm is not None, self.id,
                )
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
            self._agent._dynamic_loader = getattr(self, "_dynamic_loader", None)
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
        import logging
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
                logging.getLogger(__name__).debug("[ExpStream] user_msg write failed: %s", e)

        # 构建预组装消息
        system_prompt = self.get_system_prompt()
        # 技能索引（简化路径：无 ConsciousLiving 时在此拼接）
        skill_loader = getattr(agent, '_skill_loader', None)
        if skill_loader:
            skill_index = skill_loader.build_skill_index_prompt(user_input)
            if skill_index:
                system_prompt = system_prompt + "\n\n" + skill_index if system_prompt else skill_index
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
    name: str = ""
    description: str = ""
    avatar: str = ""
    enabled: bool = True

    # Optional per-agent config overrides
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    # Optional identity.md content (if not provided, defaults to template)
    identity_content: str = ""

    # Tool config: list of tool names to enable for this agent
    enabled_tools: list[str] | None = None

    def __post_init__(self):
        if not self.name:
            self.name = self.id


def _extract_name_from_identity(identity_path: str) -> str | None:
    """从 identity.md 提取名字。

    支持两种格式:
      - "# 小美" — 名字直接在标题里（非关键字标题）
      - "# 名字\\n小美" — 名字在标题下一行
    """
    try:
        with open(identity_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("# ") or line.startswith("## "):
                    continue
                content = line[2:].strip()
                # 格式: "# 名字\n小美" — 名字在下一行
                if content in ("名字", "名称", "Name"):
                    try:
                        next_line = next(f).strip()
                    except StopIteration:
                        return None
                    if next_line and not next_line.startswith("#"):
                        return next_line
                    continue
                # 格式: "# 小美" — "小美" 本身不是标题关键字
                if content and content not in (
                    "出生", "性格", "擅长", "不擅长", "学习兴趣", "阶段目标",
                    "身份", "追求", "热爱", "底线", "种子", "生长记录",
                    "Birth", "Personality", "Skills", "Weaknesses",
                ):
                    return content
    except Exception:
        logger.debug("Failed to extract name from identity: %s", identity_path, exc_info=True)
    return None
