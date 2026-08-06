"""Gateway RPC entry point: authentication, lookup, and safe dispatch."""

from __future__ import annotations

import logging
from typing import Any

from xiaomei_brain.people.challenge import ChallengeManager

from .method_registry import MethodRegistry
from .methods import (
    ActivityMethods,
    AgentStateMethods,
    AttachmentMethods,
    ArtifactMethods,
    AssignmentMethods,
    CapabilityMethods,
    ChatMethods,
    ChannelMethods,
    ConnectionMethods,
    EmbodimentMethods,
    ExecutionEnvironmentMethods,
    IdentityMethods,
    InteractionMethods,
    InvocationMethods,
    MediaServiceMethods,
    MemoryMethods,
    ModelMethods,
    ProjectMethods,
    SearchMethods,
    SessionMethods,
    ToolServiceMethods,
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
        self._capability_methods = CapabilityMethods(living)
        self._embodiment_methods = EmbodimentMethods(living)
        self._execution_environment_methods = ExecutionEnvironmentMethods(living)
        self._session_methods = SessionMethods(living, self._chat_methods.handle_history)
        self._attachment_methods = AttachmentMethods(living)
        self._interaction_methods = InteractionMethods(living)
        self._invocation_methods = InvocationMethods(living)
        self._memory_methods = MemoryMethods(living, self._identity_contexts)
        self._model_methods = ModelMethods(living)
        self._media_service_methods = MediaServiceMethods(living)
        self._tool_service_methods = ToolServiceMethods(living)
        self._identity_methods = IdentityMethods(
            living,
            self._connected_sessions,
            self._auth_sessions,
            self._identity_contexts,
            self._challenges,
        )
        self._artifact_methods = ArtifactMethods(living, self._identity_contexts)
        self._assignment_methods = AssignmentMethods(living, self._identity_contexts)
        self._activity_methods = ActivityMethods(living, self._identity_contexts)
        self._project_methods = ProjectMethods(living, self._identity_contexts)
        self._agent_state_methods = AgentStateMethods(
            living,
            self._identity_contexts,
        )
        self._search_methods = SearchMethods(living, self._identity_contexts)
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
            self._capability_methods,
            self._embodiment_methods,
            self._execution_environment_methods,
            self._session_methods,
            self._attachment_methods,
            self._interaction_methods,
            self._invocation_methods,
            self._memory_methods,
            self._model_methods,
            self._media_service_methods,
            self._tool_service_methods,
            self._identity_methods,
            self._artifact_methods,
            self._assignment_methods,
            self._activity_methods,
            self._project_methods,
            self._agent_state_methods,
            self._search_methods,
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
            "interaction.catalog": {"interaction.catalog"},
            "action.approval": {"action.respond"},
            "session.resume": {"session.resume"},
            "session.subscribe": {"session.subscribe"},
            "session.unsubscribe": {"session.unsubscribe"},
            "session.switch": {"session.switch"},
            "session.list": {"chat.sessions"},
            "search.unified": {"search.query"},
            "message.attachments": {"chat.send", "attachment.get"},
            "embodiment.desktop": {
                "embodiment.register",
                "embodiment.unregister",
                "embodiment.audio.input",
            },
            "embodiment.audio_stream": {
                "embodiment.register",
            },
            "embodiment.continuous_hearing": {
                "embodiment.hearing.acquire",
                "embodiment.hearing.release",
                "embodiment.audio.input",
            },
            "embodiment.camera_lease": {
                "embodiment.vision.acquire",
                "embodiment.vision.release",
            },
            "embodiment.commands": {
                "embodiment.register",
                "embodiment.command.respond",
            },
            "identity.biometrics": {
                "identity.biometrics.status",
                "identity.biometrics.enroll",
            },
            "attachment.read": {"attachment.get"},
            "artifact.read": {"artifact.get", "artifact.list"},
            "artifact.events": {"artifact.get"},
            "assignment.read": {"assignment.list", "assignment.get"},
            "assignment.artifacts": {"assignment.artifact.get"},
            "assignment.control": {
                "assignment.request_cancel",
                "assignment.request_resume",
            },
            "assignment.events": {"assignment.get"},
            "activity.read": {
                "activity.current",
                "activity.list",
                "activity.get",
            },
            "activity.events": {"activity.get"},
            "project.read": {
                "project.list",
                "project.get",
                "project.current",
            },
            "project.events": {"project.get"},
            "memory.read": {"memory.list"},
            "agent.state": {"agent.state.get"},
            "capability.read": {"capability.list", "capability.get"},
            "capability.activation": {"capability.enable", "capability.disable"},
            "capability.package.inspect": {"capability.package.inspect"},
            "capability.package.lifecycle": {
                "capability.package.list",
                "capability.package.install",
                "capability.package.activate",
                "capability.package.deactivate",
                "capability.package.uninstall",
            },
            "model.configuration": {
                "model.config.get",
                "model.catalog",
                "model.provider.test",
                "model.provider.configure",
                "model.provider.remove",
                "model.selection.set",
            },
            "message.retry": {"chat.retry"},
            "message.compact": {"chat.compact"},
            "media.service.configuration": {
                "media.service.list",
                "media.service.get",
                "media.service.configure",
                "media.service.test",
                "media.service.remove",
                "media.runtime.status",
            },
            "tool.service.configuration": {
                "tool.service.list",
                "tool.service.get",
                "tool.service.configure",
                "tool.service.test",
                "tool.service.remove",
            },
            "execution.environment.configuration": {
                "execution.environment.get",
                "execution.environment.status",
                "execution.environment.test",
                "execution.environment.save",
            },
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
        self._embodiment_methods.drop_connection(conn_id)
        self._connected_sessions.discard(conn_id)
        self._auth_sessions.discard(conn_id)
        self._identity_methods.drop_connection(conn_id)
