"""Host-local AI model services shared by all local Agent processes.

The runtime owns model weights and inference processes only.  Agent-specific
identity templates, voice preferences, memories, and vector databases remain
inside each Agent's data directory.
"""

from .manager import LocalAIRuntimeManager

__all__ = ["LocalAIRuntimeManager"]
