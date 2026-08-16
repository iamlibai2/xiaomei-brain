"""Gateway — 统一入站门。所有外部消息的唯一入口。

Gateway = 感官/运动神经：接收信号 → 过滤噪声 → 送达意识层。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Types ────────────────────────────────────────────────────

@dataclass
class RawMessage:
    """Gateway 接受的原始入站消息。"""
    content: str
    source: str = ""              # "human" | "agent" | "system"
    channel: str = "cli"          # "cli" | "ws" | "feishu" | "dingtalk" | "comms"
    peer_id: str = ""             # 发送方标识
    peer_type: str = "human"      # "human" | "agent"
    images: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    urgent: bool = False
    session_id: str = ""          # 外部指定的 session_id，空则由 Gateway 分配
    # A shared Person session is not itself a reply address.
    reply_channel: str = ""
    reply_target: str = ""


@dataclass
class Accepted:
    """消息通过 Gateway，准备入队。"""
    living_message: Any  # LivingMessage


@dataclass
class Rejected:
    """消息被 Gateway 拒绝。"""
    reason: str              # THROTTLED / UNAUTHORIZED / HANDLED / EMPTY
    silent: bool = False     # True = 不通知发送方


AcceptResult = Accepted | Rejected


@dataclass(frozen=True)
class GroupMessageCapture:
    """Durable identities created while perceiving one group message."""

    accepted: bool
    group_message_id: int | None = None
    workspace_observation_id: str = ""


# ── Gateway ──────────────────────────────────────────────────

class Gateway:
    """统一入站门。

    所有外部消息的唯一入口。做机械层面的预处理（清洗、认证、限流、
    身份解析、会话路由），然后将纯净消息送入 Living 队列。
    """

    def __init__(self, living, router, config=None):
        self._living = living
        self._router = router
        self._config = config
        self._identity_mgr = None
        self._channels: dict[str, Any] = {}
        self._ws_server = None
        self._ws_thread = None

    # ── Dependencies (set after init) ──────────────────────

    def set_identity_mgr(self, mgr) -> None:
        self._identity_mgr = mgr

    def set_ws_server(self, server, thread) -> None:
        """注册 WS Gateway，由 Gateway 统一管理生命周期。"""
        self._ws_server = server
        self._ws_thread = thread

    # ── Channel lifecycle ──────────────────────────────────

    def register_channel(self, name: str, adapter) -> None:
        """注册通道适配器。"""
        self._channels[name] = adapter
        logger.info("[Gateway] 注册通道: %s", name)

    def get_channel(self, name: str):
        """Return the currently active adapter for a channel."""
        return self._channels.get(name)

    def replace_channel(self, name: str, adapter) -> None:
        """Start a replacement adapter, then retire the previous one."""
        previous = self._channels.get(name)
        adapter.setup(living=self._living)
        self._channels[name] = adapter
        if previous is not None and previous is not adapter:
            try:
                previous.shutdown()
            except Exception:
                logger.warning("[Gateway] failed to stop old channel: %s", name, exc_info=True)
        logger.info("[Gateway] channel hot-reloaded: %s", name)

    def remove_channel(self, name: str) -> bool:
        """Stop and unregister one external channel."""
        adapter = self._channels.pop(name, None)
        if adapter is None:
            return False
        adapter.shutdown()
        logger.info("[Gateway] channel removed: %s", name)
        return True

    def open_channels(self) -> None:
        """启动所有已注册通道。"""
        for name, adapter in self._channels.items():
            if hasattr(adapter, "setup"):
                try:
                    adapter.setup(living=self._living)
                    logger.info("[Gateway] 通道已启动: %s", name)
                except Exception as e:
                    logger.error("[Gateway] 通道启动失败: %s %s", name, e)

    def close_channels(self) -> None:
        """关闭所有通道（含 WS Gateway）。"""
        # 关闭 WS Gateway
        if self._ws_server is not None:
            try:
                self._ws_server.should_exit = True
                logger.info("[Gateway] WS Gateway 已请求关闭")
            except Exception as e:
                logger.warning("[Gateway] 关闭 WS Gateway 失败: %s", e)

        # 关闭所有插件通道适配器
        for name, adapter in self._channels.items():
            if hasattr(adapter, "shutdown"):
                try:
                    adapter.shutdown()
                    logger.info("[Gateway] 通道已关闭: %s", name)
                except Exception as e:
                    logger.warning("[Gateway] 关闭通道失败: %s %s", name, e)

    def is_open(self) -> bool:
        """通道是否全部开启（至少注册过）。"""
        return len(self._channels) > 0

    # ── Inbound ───────────────────────────────────────────

    def accept(self, raw: RawMessage) -> AcceptResult:
        """唯一入站入口。返回 Accepted 或 Rejected。"""
        # 1. Sanitize
        content = self._sanitize(raw.content)
        if content is None:
            return Rejected(reason="EMPTY", silent=True)

        # 2. Empty check
        if not content.strip() and not raw.attachments and not raw.images:
            logger.debug("[Gateway] 忽略空消息")
            return Rejected(reason="EMPTY", silent=True)

        # 3. Identity and session are needed before checking whether this is a
        # response to a Turn that is intentionally waiting for the user.
        user_id = raw.peer_id if raw.peer_type == "human" else self._living.user_id
        user_display_name = self._resolve_identity(raw.peer_id)
        if not user_display_name:
            user_display_name = "这位用户"
        routed = self._route_message(raw)
        session_id = raw.session_id or self._default_session(raw, routed)
        context_key = self._context_key(raw, session_id, user_id)

        # 4. Resolve conversational control replies before ordinary enqueueing.
        # Clarify and Action wait inside the current Turn; matching responses
        # must wake that Turn instead of becoming a new queued message.
        if self._handle_conversation_control(raw, content, user_id, session_id):
            return Rejected(reason="HANDLED", silent=True)

        # A durable Assignment clarification behaves like a delayed reply to
        # this conversation. Match only one pending_interaction in the same
        # Person/session; pending Actions always require explicit approve/deny.
        assignment_id = ""
        if raw.source == "human":
            service = getattr(
                getattr(self._living, "agent", None),
                "assignment_service",
                None,
            )
            if service is not None:
                try:
                    from xiaomei_brain.assignments import ActorType, AssignmentActor

                    pending = service.pending_interaction_for_session(
                        actor=AssignmentActor(ActorType.PERSON, user_id),
                        session_id=session_id,
                    )
                    if pending is not None:
                        assignment_id = pending.id
                except (PermissionError, ValueError):
                    logger.warning(
                        "Failed to match Assignment reply for %s in %s",
                        user_id,
                        session_id,
                        exc_info=True,
                    )

        # 5. Rate-limit check. Human messages are always accepted into Living's
        # FIFO queue, including while another Turn is being processed.
        if raw.source != "human" and not raw.urgent:
            sig = getattr(self._living, '_interoception_signals', None)
            if sig and getattr(sig, 'throttle', False):
                logger.warning("[Gateway] 限流激活，丢弃非紧急消息: %.50s", content)
                return Rejected(reason="THROTTLED", silent=True)

        turn_id = str(uuid.uuid4())
        message_id = self._persist_human_message(
            raw=raw,
            content=content,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        if message_id is False:
            return Rejected(reason="PERSISTENCE_FAILED", silent=False)

        # 7. Enqueue to Living (passes display_name through)
        reply_route = self._reply_route(raw, routed)
        if (
            reply_route is not None
            and raw.peer_type == "human"
            and hasattr(self._router, "note_active_route")
        ):
            self._router.note_active_route(user_id, reply_route, session_id)
        is_local_terminal = (
            session_id == "main" or session_id.startswith("cli-")
        )
        if (
            reply_route is not None
            and not is_local_terminal
            and hasattr(self._router, "bind_turn")
        ):
            self._router.bind_turn(turn_id, reply_route)
        from xiaomei_brain.consciousness.living import LivingMessage
        message_kwargs = dict(
            content=content,
            user_id=user_id,
            session_id=session_id,
            source=raw.source,
            images=raw.images,
            display_name=user_display_name,
            turn_id=turn_id,
        )
        workspace_observation_id = str(
            raw.metadata.get("workspace_observation_id") or ""
        )
        if workspace_observation_id:
            message_kwargs["observation_id"] = workspace_observation_id
        if isinstance(message_id, int):
            message_kwargs["message_id"] = message_id
        invocation = raw.metadata.get("invocation")
        if isinstance(invocation, dict):
            message_kwargs["invocation"] = dict(invocation)
        continued_from_turn_id = str(
            raw.metadata.get("continued_from_turn_id") or ""
        ).strip()
        if continued_from_turn_id:
            message_kwargs["continued_from_turn_id"] = continued_from_turn_id
        try:
            import inspect
            put_parameters = inspect.signature(self._living.put_message).parameters
            if "context_key" in put_parameters:
                message_kwargs["context_key"] = context_key
            if assignment_id and "assignment_id" in put_parameters:
                message_kwargs["assignment_id"] = assignment_id
        except (TypeError, ValueError):
            pass
        # Preserve compatibility with lightweight channel adapters that
        # implement the older put_message signature when there is no attachment.
        if raw.attachments:
            message_kwargs["attachments"] = raw.attachments
        msg = self._living.put_message(**message_kwargs)
        if msg is not None:
            msg.context_key = context_key
            if assignment_id:
                msg.assignment_id = assignment_id
        # Lightweight test doubles and third-party Living implementations may
        # still return None. Preserve the accepted-message contract for them.
        if msg is None:
            msg = LivingMessage(
                content=content,
                user_id=user_id,
                session_id=session_id,
                source=raw.source,
                images=raw.images,
                attachments=raw.attachments,
                invocation=dict(invocation) if isinstance(invocation, dict) else {},
                turn_id=turn_id,
                continued_from_turn_id=continued_from_turn_id,
                message_id=message_id if isinstance(message_id, int) else None,
                observation_id=str(
                    raw.metadata.get("workspace_observation_id") or ""
                ),
                context_key=context_key,
                assignment_id=assignment_id,
            )
            msg.user_display_name = user_display_name
        return Accepted(living_message=msg)

    def observe_group_message(self, raw: RawMessage) -> bool:
        """Compatibility wrapper for background-only channel adapters."""
        return self.capture_group_message(raw).accepted

    def capture_group_message(self, raw: RawMessage) -> GroupMessageCapture:
        """Persist group perception and return its traceable business identity.

        This method never creates a Turn.  A channel adapter may subsequently
        pass an explicitly mentioned message through ``accept`` while carrying
        the returned Observation ID.
        """
        content = self._sanitize(raw.content)
        if content is None or not content.strip() or not raw.session_id:
            return GroupMessageCapture(accepted=False)

        agent = getattr(self._living, "agent", None)
        db = getattr(agent, "conversation_db", None)
        if db is None or not hasattr(db, "log_group_message"):
            return GroupMessageCapture(accepted=False)

        metadata = dict(raw.metadata)
        external_message_id = str(metadata.pop("external_message_id", "") or "")
        issuer = str(metadata.get("external_issuer", "") or "")
        external_subject = str(metadata.get("external_subject", "") or "")
        display_name = str(metadata.pop("sender_display_name", "") or "")
        message_type = str(metadata.pop("message_type", "text") or "text")
        timestamp = metadata.pop("external_timestamp", None)
        try:
            created_at = float(timestamp) if timestamp is not None else time.time()
            if created_at > 10_000_000_000:
                created_at /= 1000
        except (TypeError, ValueError):
            created_at = time.time()

        try:
            group_message_id = db.log_group_message(
                session_id=raw.session_id,
                channel=raw.channel,
                issuer=issuer,
                external_message_id=external_message_id,
                external_subject=external_subject,
                person_id=raw.peer_id or None,
                display_name=display_name,
                content=content,
                message_type=message_type,
                metadata=metadata,
                created_at=created_at,
            )
            if group_message_id is None and hasattr(db, "get_group_message"):
                existing = db.get_group_message(issuer, external_message_id)
                group_message_id = (
                    int(existing["id"]) if existing is not None else None
                )
            observation_id = ""
            if group_message_id is not None:
                observation_id = self._project_group_observation(
                    raw,
                    group_message_id=group_message_id,
                    content=content,
                    external_message_id=external_message_id,
                    external_subject=external_subject,
                    display_name=display_name,
                    occurred_at=created_at,
                )
                if observation_id and hasattr(db, "update_group_message_metadata"):
                    db.update_group_message_metadata(
                        group_message_id,
                        {"workspace_observation_id": observation_id},
                    )
            return GroupMessageCapture(
                accepted=True,
                group_message_id=group_message_id,
                workspace_observation_id=observation_id,
            )
        except Exception:
            logger.exception(
                "[Gateway] failed to persist group observation: channel=%s session=%s",
                raw.channel,
                raw.session_id,
            )
            return GroupMessageCapture(accepted=False)

    def _project_group_observation(
        self,
        raw: RawMessage,
        *,
        group_message_id: int,
        content: str,
        external_message_id: str,
        external_subject: str,
        display_name: str,
        occurred_at: float,
    ) -> str:
        """Project group chatter only into an explicitly focused Workspace."""
        agent = getattr(self._living, "agent", None)
        service = getattr(agent, "workspace_service", None)
        if service is None:
            return ""
        workspace_id = service.store.focused_workspace_id(raw.session_id)
        if not workspace_id:
            return ""
        try:
            channel = str(raw.channel or "channel").strip().lower()
            locator = f"channel:{channel}:session:{raw.session_id}"
            source = service.business.store.find_data_source(
                workspace_id,
                kind="channel",
                locator=locator,
            )
            if source is None:
                source = service.business.create_data_source(
                    workspace_id,
                    kind="channel",
                    name=f"{channel} group conversation",
                    locator=locator,
                    session_id=raw.session_id,
                )
            source_person_id = ""
            peer_id = str(raw.peer_id or "").strip()
            if (
                peer_id.startswith("person_")
                and service.store.person_is_linked(workspace_id, peer_id)
            ):
                source_person_id = peer_id
            attributes = {
                "channel": channel,
                "group": True,
                "processing_mode": str(
                    raw.metadata.get("processing_mode") or "background"
                ),
                "display_name": display_name,
                "external_peer_id": peer_id,
            }
            if external_subject:
                attributes["external_subject"] = external_subject
            remote_attachment = raw.metadata.get("remote_attachment")
            if isinstance(remote_attachment, dict):
                attributes["remote_attachment"] = {
                    "id": str(remote_attachment.get("id") or ""),
                    "name": str(remote_attachment.get("name") or ""),
                    "message_type": str(
                        remote_attachment.get("message_type") or "file"
                    ),
                    "status": "remote",
                }
            observation = service.business.observe(
                workspace_id,
                content=content,
                data_source_id=source.id,
                source_person_id=source_person_id,
                external_ref=(
                    f"external:{external_message_id}"
                    if external_message_id
                    else f"group_message:{group_message_id}"
                ),
                attributes=attributes,
                occurred_at=occurred_at,
                session_id=raw.session_id,
            )
            return observation.id
        except Exception:
            # group_messages remains the authoritative channel record.
            logger.exception(
                "[Gateway] failed to project group observation: channel=%s session=%s",
                raw.channel,
                raw.session_id,
            )
            return ""

    def _handle_conversation_control(
        self,
        raw: RawMessage,
        content: str,
        user_id: str,
        session_id: str,
    ) -> bool:
        """Resolve channel text as Clarify/Action control without creating a Turn."""
        desktop_audio = (
            raw.channel == "ws"
            and str(raw.metadata.get("message_type", "")) == "audio"
        )
        # Desktop text answers use the explicit interaction.respond RPC so a
        # normal typed message can never accidentally dismiss a card. Spoken
        # answers have no card-click path, therefore the one pending Clarify
        # in this verified Person/session may consume them conversationally.
        if (
            raw.source != "human"
            or raw.peer_type != "human"
            or (raw.channel == "ws" and not desktop_audio)
        ):
            return False
        capabilities = self._channel_capabilities(raw.channel)

        # Voice never approves a side-effecting Action implicitly. Those keep
        # using the explicit action.respond boundary in Desktop.
        if (
            not desktop_audio
            and content.strip().lower().startswith("/approve")
            and capabilities.action_approval
        ):
            parts = content.strip().split()
            if len(parts) != 3 or parts[2].lower() not in {"allow", "allow-once", "deny"}:
                self._deliver_control_message(
                    session_id,
                    "用法：/approve <action_id> allow 或 /approve <action_id> deny",
                )
                return True
            broker = getattr(self._living, "_action_broker", None)
            accepted = broker is not None and broker.respond_from_channel(
                parts[1], parts[2].lower(), session_id, user_id,
            )
            if not accepted:
                self._deliver_control_message(session_id, "审批请求不存在、已结束或不属于你。")
            return True

        if capabilities.clarify:
            broker = getattr(self._living, "_interaction_broker", None)
            if broker is not None and broker.respond_pending(content, session_id, user_id):
                return True
        return False

    def _channel_capabilities(self, channel: str):
        from .channel_adapter import ChannelCapabilities

        adapter = self._channels.get(channel)
        if adapter is None and hasattr(self._router, "get_adapter"):
            adapter = self._router.get_adapter(channel)
        return getattr(adapter, "capabilities", ChannelCapabilities())

    def _deliver_control_message(self, session_id: str, text: str) -> None:
        route = (
            self._router.route_for_session(session_id)
            if hasattr(self._router, "route_for_session") else None
        )
        if route is not None:
            self._router.deliver(text, route)

    def _persist_human_message(
        self,
        *,
        raw: RawMessage,
        content: str,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> int | None | bool:
        """Persist external human input before it enters the Living queue."""
        if raw.source != "human" or raw.peer_type != "human":
            return None
        agent = getattr(self._living, "agent", None)
        db = getattr(agent, "conversation_db", None)
        if db is None:
            return None

        from xiaomei_brain.gateway.attachments import public_attachment_metadata

        metadata: dict[str, Any] = {
            "turn_id": turn_id,
            # Keep the durable conversation origin independent of the
            # channel-specific session-id convention. Desktop uses this to
            # distinguish external conversations in the unified session list.
            "channel": raw.channel,
            # Gateway acceptance only means the input is durable and waiting
            # in Living's FIFO queue.  ConversationDriver changes this to
            # ``processing`` when the Turn actually starts.
            "status": "queued",
            "queued_at": time.time(),
        }
        external_message_id = str(
            raw.metadata.get("external_message_id") or "",
        ).strip()
        if external_message_id:
            metadata["external_message_id"] = external_message_id
        external_timestamp = raw.metadata.get("external_timestamp")
        if external_timestamp is not None:
            metadata["external_timestamp"] = external_timestamp
        external_subject = str(
            raw.metadata.get("external_subject") or "",
        ).strip()
        if external_subject:
            metadata["external_subject"] = external_subject
        workspace_observation_id = str(
            raw.metadata.get("workspace_observation_id") or "",
        ).strip()
        if workspace_observation_id:
            metadata["workspace_observation_id"] = workspace_observation_id
        retry_of = raw.metadata.get("retry_of")
        if isinstance(retry_of, int) and retry_of > 0:
            metadata["retry_of"] = retry_of
        continued_from_turn_id = str(
            raw.metadata.get("continued_from_turn_id") or ""
        ).strip()
        if continued_from_turn_id:
            metadata["continued_from_turn_id"] = continued_from_turn_id
        invocation = raw.metadata.get("invocation")
        if isinstance(invocation, dict):
            metadata["invocation"] = {
                "kind": str(invocation.get("kind") or ""),
                "id": str(invocation.get("id") or ""),
                "process_template_id": str(
                    invocation.get("process_template_id") or ""
                ),
            }
        if raw.metadata.get("message_type") == "audio":
            metadata["message_type"] = "audio"
            metadata["audio_duration_ms"] = int(
                raw.metadata.get("audio_duration_ms", 0) or 0
            )
            emotion = str(raw.metadata.get("speech_emotion", "")).strip()
            if emotion:
                metadata["speech_emotion"] = emotion
            events = raw.metadata.get("speech_events")
            if isinstance(events, list):
                metadata["speech_events"] = [
                    str(item) for item in events[:10] if str(item).strip()
                ]
        public_attachments = public_attachment_metadata(raw.attachments)
        if public_attachments:
            metadata["attachments"] = public_attachments
        elif raw.images:
            metadata["images"] = raw.images
        try:
            message_id = db.log(
                session_id=session_id,
                role="user",
                content=content,
                user_id=user_id,
                metadata=metadata,
            )
        except Exception:
            logger.exception("[Gateway] failed to persist accepted human message")
            return False

        exp_stream = getattr(agent, "exp_stream", None)
        if exp_stream:
            try:
                exp_stream.log(
                    type="user_msg",
                    content=content,
                    session_id=session_id,
                    related_id=str(message_id),
                    user_id=user_id,
                )
            except Exception as exc:
                logger.debug("[ExpStream] user_msg write failed: %s", exc)
        return message_id

    # ── Internal ───────────────────────────────────────────

    @staticmethod
    def _sanitize(text: str) -> str | None:
        """清洗输入。返回 None 表示消息应丢弃。"""
        if not isinstance(text, str):
            return None
        from xiaomei_brain.agent.message_utils import clean_input
        return clean_input(text)

    def _resolve_identity(self, peer_id: str) -> str:
        people = getattr(self._living, "_people_service", None)
        person = people.store.get_person(peer_id) if people and peer_id else None
        if person is not None:
            return person.display_name
        """解析用户身份，返回 display name。"""
        if not peer_id or not self._identity_mgr:
            return ""
        identity = self._identity_mgr.resolve(peer_id)
        if identity:
            return self._identity_mgr.get_display_name(peer_id)
        return ""

    def _route_message(self, raw: RawMessage):
        """Resolve the peer rule once for session and route fallback."""
        route_message = getattr(self._router, "route", None)
        if not callable(route_message):
            return None
        from xiaomei_brain.gateway.router import InboundMsg
        return route_message(InboundMsg(
            content=raw.content,
            peer_type=raw.peer_type,
            peer_id=raw.peer_id,
            channel=raw.channel,
            images=raw.images,
        ))

    @staticmethod
    def _default_session(raw: RawMessage, routed: Any) -> str:
        """Determine a session when the transport did not provide one."""
        # Agent comms → comms- prefix
        if raw.source == "agent" and raw.peer_type == "agent":
            return f"comms-{raw.peer_id}"
        return getattr(routed, "session_id", "main")

    def _context_key(
        self,
        raw: RawMessage,
        session_id: str,
        person_id: str,
    ) -> str:
        """Resolve the runtime dialogue boundary independently of routing."""
        explicit = raw.metadata.get("context_key")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        people = getattr(self._living, "_people_service", None)
        session = people.store.get_session(session_id) if people else None
        if session is not None and session.scope_type == "conversation":
            return f"conversation:{session.scope_id}"

        # Desktop/WebSocket exposes explicit user-created sessions, so those
        # remain independent. Default private channels follow the Person across
        # CLI, Feishu and DingTalk.
        if raw.channel == "ws":
            return f"session:{session_id}"
        if raw.peer_type == "human" and person_id:
            return f"person:{person_id}"
        return f"session:{session_id}"

    def _reply_route(self, raw: RawMessage, routed: Any):
        if raw.reply_channel and raw.reply_target:
            from xiaomei_brain.gateway.router import OutputRoute
            return OutputRoute(raw.reply_channel, raw.reply_target)
        route = getattr(routed, "output_route", None)
        if route is not None:
            return route
        route_for_session = getattr(self._router, "route_for_session", None)
        if raw.session_id and callable(route_for_session):
            return route_for_session(raw.session_id)
        return None
