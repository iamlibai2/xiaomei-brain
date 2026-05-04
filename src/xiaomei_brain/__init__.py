"""Xiaomei Brain - A general-purpose AI Agent framework."""

# Agent core (from agent/ module)
from xiaomei_brain.agent import (
    Agent, AgentSession, SessionManager,
    AgentManager, AgentInstance,
    ReminderManager, ProactiveOutput, ProactiveTrigger, ProactiveMessage,
)

# Tools
from xiaomei_brain.tools.base import Tool, tool
from xiaomei_brain.tools.registry import ToolRegistry

# LLM & Config (base infrastructure)
from xiaomei_brain.base.llm import LLMClient, LLMError
from xiaomei_brain.base.config import Config

# Memory
from xiaomei_brain.memory import (
    LongTermMemory,
    MemoryExtractor,
    ConversationDB,
    SelfModel,
)

__all__ = [
    # Agent core
    "Agent", "AgentSession", "SessionManager",
    "AgentManager", "AgentInstance",
    "ReminderManager", "ProactiveOutput", "ProactiveTrigger", "ProactiveMessage",
    # Tools
    "Tool", "tool", "ToolRegistry",
    # LLM
    "LLMClient", "LLMError", "Config",
    # Memory
    "LongTermMemory",
    "MemoryExtractor",
    "ConversationDB",
    "SelfModel",
]
