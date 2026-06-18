"""Base infrastructure: LLM client and configuration."""

from xiaomei_brain.llm.client import LLMClient, LLMError, FatalLLMError, set_log_agent
from xiaomei_brain.llm.types import ToolCall, NormalizedResponse as ChatResponse
from xiaomei_brain.base.config import Config
from xiaomei_brain.base.config_provider import ConfigProvider, get_provider, ConflictError

__all__ = [
    "LLMClient", "LLMError", "ToolCall", "ChatResponse",
    "Config",
    "ConfigProvider", "get_provider", "ConflictError",
]