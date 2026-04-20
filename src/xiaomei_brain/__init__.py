"""Xiaomei Brain - A general-purpose AI Agent framework."""

# Agent core (from agent/ module)
from xiaomei_brain.agent import (
    Agent, AgentSession, SessionManager,
    AgentManager, AgentInstance,
    ContextManager, ContextExtractor,
    ReminderManager, ProactiveOutput, ProactiveTrigger, ProactiveMessage,
)

# Tools
from xiaomei_brain.tools.base import Tool, tool
from xiaomei_brain.tools.registry import ToolRegistry

# LLM
from xiaomei_brain.llm import LLMClient, LLMError

# Config
from xiaomei_brain.config import Config

# Memory
from xiaomei_brain.memory import (
    MemoryStore, MemoryResult, ConversationLogger,
    DreamProcessor, DreamScheduler, EpisodicMemory, WorkingMemory,
)

__all__ = [
    # Agent core
    "Agent", "AgentSession", "SessionManager",
    "AgentManager", "AgentInstance",
    "ContextManager", "ContextExtractor",
    "ReminderManager", "ProactiveOutput", "ProactiveTrigger", "ProactiveMessage",
    # Tools
    "Tool", "tool", "ToolRegistry",
    # LLM
    "LLMClient", "LLMError", "Config",
    # Memory
    "MemoryStore", "MemoryResult",
    "ConversationLogger", "DreamProcessor", "DreamScheduler",
    "EpisodicMemory", "WorkingMemory",
]