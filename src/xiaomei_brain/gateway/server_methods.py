"""Gateway RPC entry point: authentication, lookup, and safe dispatch."""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.people.challenge import ChallengeManager

from .method_registry import MethodRegistry
from .methods import (
    AttachmentMethods,
    ArtifactMethods,
    ChatMethods,
    ChannelMethods,
    ConnectionMethods,
    IdentityMethods,
    InteractionMethods,
    SessionMethods,
)
from .protocol import ErrorCode, build_error

logger = logging.getLogger(__name__)


class MethodRouter:
    """Compose domain method providers behind one authenticated RPC surface."""

    def __init__(self, living: Any = None, config: Any = None) -> None:
        self._living = living
        self._config = config
        self._connected_sessions: set[str] = set()
        # 只有完成 Person 签名认证的连接才进入这个集合。
        self._auth_sessions: set[str] = set()
        self._identity_contexts: dict[str, Any] = {}
        self._challenges = ChallengeManager()
        self._registry = MethodRegistry()

        self._connection_methods = ConnectionMethods(
            living,
            config,
            self._connected_sessions,
            capability_provider=self._capabilities,
        )
        self._chat_methods = ChatMethods(living)
        self._session_methods = SessionMethods(living, self._chat_methods.handle_history)
        self._attachment_methods = AttachmentMethods(living)
        self._interaction_methods = InteractionMethods(living)
        self._identity_methods = IdentityMethods(
            living,
            self._connected_sessions,
            self._auth_sessions,
            self._identity_contexts,
            self._challenges,
        )
        self._artifact_methods = ArtifactMethods(living)
        self._channel_methods = ChannelMethods(living, self._identity_contexts)

        self._registry.register_many(
            self._connection_methods.handlers,
            requires_auth=False,
        )
        self._registry.register_many(
            self._identity_methods.pre_auth_handlers,
            requires_auth=False,
        )
        for provider in (
            self._chat_methods,
            self._session_methods,
            self._attachment_methods,
            self._interaction_methods,
            self._identity_methods,
            self._artifact_methods,
            self._channel_methods,
        ):
            self._registry.register_many(provider.handlers)

        # Kept as a snapshot for lightweight integrations that inspect the
        # catalog. Dispatch itself always uses MethodRegistry metadata.
        self._handlers = self._registry.handlers

    def dispatch(self, conn_id: str, req_id: str, method: str, params: dict) -> dict:
        registered = self._registry.resolve(method)
        if conn_id not in self._auth_sessions and (
            registered is None or registered.requires_auth
        ):
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "请先 connect")
        if registered is None:
            return build_error(req_id, ErrorCode.METHOD_NOT_FOUND, f"未知方法: {method}")
        try:
            return registered.handler(conn_id, req_id, params)
        except Exception as exc:
            logger.exception("[MethodRouter] %s 处理失败", method)
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(exc))

    @property
    def method_names(self) -> tuple[str, ...]:
        return self._registry.names()

    def _capabilities(self) -> list[str]:
        """Describe features backed by the RPC methods actually registered."""
        methods = set(self._registry.names())
        capabilities = {
            "event.sequence",
            "event.timestamp",
        }
        requirements = {
            "message.lifecycle": {"chat.send"},
            "tool.lifecycle": {"chat.send"},
            "interaction.question": {"interaction.respond"},
            "action.approval": {"action.respond"},
            "session.resume": {"session.resume"},
            "session.list": {"chat.sessions"},
            "message.attachments": {"chat.send", "attachment.get"},
            "attachment.read": {"attachment.get"},
            "artifact.read": {"artifact.get"},
            "artifact.events": {"artifact.get"},
            "message.retry": {"chat.retry"},
            "identity.list": {"identity.list"},
            "identity.challenge": {
                "identity.register.begin",
                "identity.register.complete",
                "identity.authenticate.begin",
                "identity.authenticate.complete",
            },
            "identity.legacy_session_claim": {
                "identity.legacy_sessions.list",
                "identity.legacy_sessions.claim",
            },
            "channel.configuration": {
                "channel.config.get",
                "channel.test",
                "channel.configure",
                "channel.status",
                "channel.remove",
            },
            "identity.external_link": {
                "identity.link.begin",
                "identity.link.status",
                "identity.link.cancel",
                "identity.link.list",
                "identity.link.revoke",
            },
        }
        for capability, required_methods in requirements.items():
            if required_methods.issubset(methods):
                capabilities.add(capability)
        return sorted(capabilities)

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._connected_sessions.discard(conn_id)
        self._auth_sessions.discard(conn_id)
        self._identity_methods.drop_connection(conn_id)
