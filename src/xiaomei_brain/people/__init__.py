"""Agent 本地人物与外部身份绑定。"""

from .models import (
    ConversationSession,
    IdentityBinding,
    IdentityContext,
    IdentityEvent,
    IdentityLinkRequest,
    Person,
)
from .link_service import IdentityLinkService
from .service import PeopleService
from .biometrics import PeopleBiometricService
from .store import PeopleStore

__all__ = [
    "ConversationSession",
    "IdentityBinding",
    "IdentityContext",
    "IdentityEvent",
    "IdentityLinkRequest",
    "IdentityLinkService",
    "PeopleBiometricService",
    "PeopleService",
    "PeopleStore",
    "Person",
]
