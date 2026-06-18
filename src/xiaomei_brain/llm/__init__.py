"""LLM 适配层 — 基于插件体系的 multi-provider 通用架构。

Usage:
    from xiaomei_brain.llm import LLMClient

    client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=registry)
    response = client.chat(messages=[...], tools=[...])
"""

from xiaomei_brain.llm.client import LLMClient, LLMError, FatalLLMError, set_log_agent
from xiaomei_brain.llm.types import (
    ProviderProfile,
    ModelDefinition,
    ModelApi,
    NormalizedResponse,
    ToolCall,
    load_config_providers,
)

__all__ = [
    "LLMClient", "LLMError", "FatalLLMError", "set_log_agent",
    "ProviderProfile", "ModelDefinition", "ModelApi",
    "NormalizedResponse", "ToolCall",
    "load_config_providers",
]
