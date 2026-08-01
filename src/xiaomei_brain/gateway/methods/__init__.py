"""Domain-grouped Gateway RPC method providers."""

from .activities import ActivityMethods
from .agent_state import AgentStateMethods
from .attachments import AttachmentMethods
from .artifacts import ArtifactMethods
from .assignments import AssignmentMethods
from .chat import ChatMethods
from .capabilities import CapabilityMethods
from .channels import ChannelMethods
from .connection import ConnectionMethods
from .embodiments import EmbodimentMethods
from .identity import IdentityMethods
from .interactions import InteractionMethods
from .media import MediaServiceMethods
from .memories import MemoryMethods
from .models import ModelMethods
from .search import SearchMethods
from .sessions import SessionMethods
from .tools import ToolServiceMethods

__all__ = [
    "ActivityMethods",
    "AgentStateMethods",
    "AttachmentMethods",
    "ArtifactMethods",
    "AssignmentMethods",
    "ChatMethods",
    "CapabilityMethods",
    "ChannelMethods",
    "ConnectionMethods",
    "EmbodimentMethods",
    "IdentityMethods",
    "InteractionMethods",
    "MediaServiceMethods",
    "MemoryMethods",
    "ModelMethods",
    "SearchMethods",
    "SessionMethods",
    "ToolServiceMethods",
]
