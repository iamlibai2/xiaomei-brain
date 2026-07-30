"""Domain-grouped Gateway RPC method providers."""

from .activities import ActivityMethods
from .agent_state import AgentStateMethods
from .attachments import AttachmentMethods
from .artifacts import ArtifactMethods
from .assignments import AssignmentMethods
from .chat import ChatMethods
from .channels import ChannelMethods
from .connection import ConnectionMethods
from .identity import IdentityMethods
from .interactions import InteractionMethods
from .media import MediaServiceMethods
from .memories import MemoryMethods
from .models import ModelMethods
from .sessions import SessionMethods
from .tools import ToolServiceMethods

__all__ = [
    "ActivityMethods",
    "AgentStateMethods",
    "AttachmentMethods",
    "ArtifactMethods",
    "AssignmentMethods",
    "ChatMethods",
    "ChannelMethods",
    "ConnectionMethods",
    "IdentityMethods",
    "InteractionMethods",
    "MediaServiceMethods",
    "MemoryMethods",
    "ModelMethods",
    "SessionMethods",
    "ToolServiceMethods",
]
