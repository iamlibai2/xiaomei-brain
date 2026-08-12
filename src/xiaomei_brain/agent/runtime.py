"""Factories for short-lived, isolated Agent execution runtimes.

An isolated runtime is not another Agent identity.  It reuses the deployed
Agent's LLM configuration, tools and durable stores while owning all mutable
ReAct state (messages, callbacks, cancellation and tool-call buffers).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable

from .core import Agent
from ..tools.registry import ToolRegistry


def clone_llm_for_isolated_run(llm: Any) -> Any:
    """Create an LLM client with independent retry and response state."""
    custom_clone = getattr(llm, "clone_for_isolated_run", None)
    if callable(custom_clone):
        return custom_clone()

    from .context_guard import ContextGuard
    from ..llm.client import LLMClient

    guard_tokens = llm.max_tokens if isinstance(llm, ContextGuard) else None
    base = llm._llm if isinstance(llm, ContextGuard) else llm
    registry = getattr(base, "_registry", None)
    if registry is None:
        raise RuntimeError("LLM provider registry 不可用，无法创建隔离客户端")
    cloned = LLMClient(
        provider=base.provider,
        model=base.model,
        registry=registry,
        api_key=base.api_key,
        max_retries=int(getattr(base, "_max_retries", LLMClient.DEFAULT_MAX_RETRIES)),
        timeout=int(getattr(base, "_timeout", LLMClient.DEFAULT_TIMEOUT)),
        fallback_configs=copy.deepcopy(getattr(base, "_fallback_configs", [])),
        interoception=None,
    )
    cloned.set_thinking(
        enabled=getattr(base, "thinking_enabled", None),
        effort=str(getattr(base, "thinking_effort", "default")),
    )
    # Isolated runtimes own mutable ReAct state but share the deployed
    # Agent's accounting sinks.
    cloned._token_callback = getattr(base, "_token_callback", None)
    cloned._usage_callback = getattr(base, "_usage_callback", None)
    cloned._trace_callback = getattr(base, "_trace_callback", None)
    return ContextGuard(cloned, max_tokens=guard_tokens) if guard_tokens else cloned


@dataclass(frozen=True)
class AgentRuntimeContext:
    """Turn-local identity and routing values for an isolated execution."""

    session_id: str
    turn_id: str = ""
    user_id: str = "system"
    memory_scope_id: str = "global"
    context_key: str = ""
    max_steps: int = 50


class AgentRuntimeFactory:
    """Create independent Agent Core instances for one deployed Agent."""

    def __init__(self, agent_instance: Any) -> None:
        self.agent_instance = agent_instance

    def copy_tools(self, allowed_tools: Iterable[str] | None = None) -> ToolRegistry:
        """Create an independent registry while reusing stateless Tool objects."""
        registry = ToolRegistry()
        source = getattr(self.agent_instance, "tools", None)
        if source is None:
            return registry
        allow = frozenset(allowed_tools) if allowed_tools is not None else None
        for tool in source.list_tools():
            if allow is None or tool.name in allow:
                registry.register(tool)
        return registry

    def create(
        self,
        context: AgentRuntimeContext,
        *,
        tools: ToolRegistry | None = None,
        allowed_tools: Iterable[str] | None = None,
    ) -> Agent:
        """Create a fresh Core and attach this Agent's shared durable world."""
        runtime = Agent(
            llm=clone_llm_for_isolated_run(self.agent_instance.llm),
            tools=tools if tools is not None else self.copy_tools(allowed_tools),
            system_prompt="",
            max_steps=max(1, context.max_steps),
        )
        runtime.user_id = context.user_id
        runtime.memory_scope_id = context.memory_scope_id
        runtime.session_id = context.session_id
        runtime.context_key = context.context_key or context.session_id
        runtime.turn_id = context.turn_id

        # These objects define the deployed Agent's world and remain shared.
        # Only the mutable ReAct execution state belongs to this new runtime.
        get_live = getattr(self.agent_instance, "_get_agent", None)
        live = get_live() if callable(get_live) else None
        attributes = (
            "self_model",
            "conversation_db",
            "dag",
            "longterm_memory",
            "short_term_memory",
            "memory_formation",
            "memory_extractor",
            "_procedure_memory",
            "_skill_loader",
            "identity_mgr",
            "people_service",
            "workspace_service",
            "workspace_asset_resolver",
            "tool_selection_context_providers",
            "exp_stream",
            "essence",
            "_living_cfg",
            "tool_execution_environment",
            "tool_workspace_root",
            "tool_working_directory",
            "tool_output_root",
            "tool_writable_roots",
            "tool_read_only_roots",
        )
        # AgentInstance owns the durable services; the live Core contains a few
        # late-bound integrations.  Copy both when available, with the live
        # value taking precedence.
        for source in (self.agent_instance, live):
            if source is None:
                continue
            for attribute in attributes:
                if hasattr(source, attribute):
                    setattr(runtime, attribute, getattr(source, attribute))
        return runtime


class IsolatedAgentProvider:
    """Present one isolated Core through the regular AgentInstance interface."""

    def __init__(self, agent_instance: Any, runtime: Agent) -> None:
        self._agent_instance = agent_instance
        self._runtime = runtime

    def _get_agent(self) -> Agent:
        return self._runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent_instance, name)
