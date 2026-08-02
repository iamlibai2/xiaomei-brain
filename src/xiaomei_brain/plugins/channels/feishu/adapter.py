"""FeishuAdapter — 飞书通道适配器。

消息流：飞书 WS 事件 → 内联回调 → Router.register_peer() + living.put_message()。
不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
import warnings
import uuid

# 飞书 SDK (lark_oapi) 内部使用了已弃用的 pkg_resources API
warnings.filterwarnings("ignore", category=UserWarning, module="lark_oapi")

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities
from xiaomei_brain.assignments.models import AssignmentChannelMessage
from .types import OutboundMsg
from .client import FeishuChannel

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：注册飞书频道。"""
    app_id = ctx.config.get("appId") or ctx.config.get("app_id") or os.getenv("FEISHU_APP_ID", "")
    app_secret = ctx.config.get("appSecret") or ctx.config.get("app_secret") or os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        ctx.logger.warning("飞书配置缺失，跳过注册")
        return
    ctx.register_channel("feishu", create_adapter(ctx.config))


def create_adapter(config: dict) -> "FeishuAdapter":
    """Build an adapter from a normalized Feishu account configuration."""
    app_id = config.get("appId") or config.get("app_id") or os.getenv("FEISHU_APP_ID", "")
    app_secret = config.get("appSecret") or config.get("app_secret") or os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError("飞书 appId 和 appSecret 不能为空")
    account_id = config.get("accountId") or config.get("account_id") or "default"
    return FeishuAdapter(FeishuChannel(
        app_id=app_id,
        app_secret=app_secret,
        account_id=account_id,
    ))


class FeishuAdapter(ChannelAdapter):
    """飞书通道适配器。"""

    def __init__(self, channel: FeishuChannel) -> None:
        self._channel = channel
        self._living = None
        self._assignment_notices: dict[
            tuple[str, str], tuple[object, ...]
        ] = {}
        self._assignment_card_bindings: dict[
            tuple[str, str], AssignmentChannelMessage
        ] = {}
        self._assignment_notice_lock = threading.Lock()
        self._artifact_delivery_lock = threading.Lock()
        self._artifact_deliveries_inflight: set[tuple[str, str, str, str]] = set()
        self._artifact_deliveries_sent: set[tuple[str, str, str, str]] = set()

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            structured_events=True,
            clarify=True,
            action_approval=True,
            attachments=True,
            message_update=True,
            audio_input=True,
            audio_output=True,
        )

    @property
    def channel_type(self) -> str:
        return "feishu"

    @property
    def embodiment_id(self) -> str:
        return f"feishu:{self._channel.account_id}"

    @property
    def embodiment_label(self) -> str:
        return "飞书机器人"

    @property
    def exposes_embodiment(self) -> bool:
        return True

    def setup(self, living=None) -> None:
        """设置回调并启动飞书通道。

        回调内联在适配器中：解析平台消息 → Router 注册 peer → put_message()。
        这样 ConsciousLiving 不需要知道飞书的存在。
        """
        if not living or not self._channel:
            return

        self._living = living

        router = living._router
        people = getattr(living, "_people_service", None)
        link_service = getattr(living, "_identity_link_service", None)
        issuer = f"feishu:app:{self._channel.app_id}"

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            chat_type = msg_dict.get("chat_type", "p2p")
            logger.info(
                "[Feishu/Inbound] sender=%s chat_type=%s text=%r",
                sender,
                chat_type,
                text[:200],
            )

            if msg_dict.get("msg_type") == "audio":
                # SDK callbacks share the WebSocket receive path. Downloading,
                # decoding and STT must never hold up its heartbeat.
                threading.Thread(
                    target=self._handle_audio_message,
                    args=(msg_dict, living, router, people, issuer),
                    name="feishu-remote-hearing",
                    daemon=True,
                ).start()
                return

            if not text:
                logger.info("[Feishu/Inbound] ignored empty message")
                return

            is_group = chat_type != "p2p"
            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            person_id = resolved[0].person_id if resolved is not None else ""

            if is_group:
                session_id = (
                    f"feishu-group-{self._channel.app_id}-{conversation_id}"
                )
                if people:
                    people.store.ensure_session(
                        session_id,
                        "conversation",
                        f"{issuer}:chat:{conversation_id}",
                        metadata={
                            "channel": "feishu",
                            "issuer": issuer,
                            "conversation_id": conversation_id,
                        },
                    )

                # Ordinary group chatter is perception, not a request. Store it
                # separately so it cannot enter fresh_tail, dreams or personal
                # memory, and never create a Turn or a reply.
                if not msg_dict.get("bot_mentioned", False):
                    gw = getattr(living, "_gateway_inbound", None)
                    if gw and hasattr(gw, "observe_group_message"):
                        from xiaomei_brain.gateway.inbound import RawMessage
                        gw.observe_group_message(RawMessage(
                            content=text,
                            source="human",
                            channel="feishu",
                            peer_id=person_id,
                            peer_type="human",
                            session_id=session_id,
                            metadata={
                                "external_issuer": issuer,
                                "external_subject": sender,
                                "external_conversation_id": conversation_id,
                                "external_message_id": msg_dict.get("message_id", ""),
                                "external_timestamp": msg_dict.get("timestamp"),
                                "sender_display_name": (
                                    resolved[0].display_name
                                    if resolved is not None
                                    else (
                                        msg_dict.get("sender_name")
                                        if msg_dict.get("sender_name") not in {"", "user"}
                                        else sender
                                    )
                                ),
                                "message_type": msg_dict.get("msg_type", "text"),
                            },
                        ))
                    logger.info(
                        "[Feishu/Inbound] stored group observation: %s",
                        conversation_id,
                    )
                    return

            # Feishu replies and mentions may add a prefix before the command.
            # Only accept a six-digit command on the final line so ordinary
            # conversation containing the word "绑定" cannot consume a code.
            match = re.search(
                r"(?:^|\n)\s*(?:绑定|bind)\s+(\d{6})\s*$",
                text,
                re.IGNORECASE,
            )
            if match:
                if chat_type != "p2p":
                    self.send(conversation_id, "请在与机器人的私聊中完成身份绑定。")
                    return
                try:
                    binding = (
                        link_service.consume("feishu", issuer, sender, match.group(1))
                        if link_service else None
                    )
                except ValueError as exc:
                    self.send(conversation_id, str(exc))
                    return
                if binding is None:
                    self.send(conversation_id, "绑定码无效或已过期，请在 Desktop 中重新生成。")
                    return
                self.send(conversation_id, "身份绑定成功，现在我能认出你了。")
                return

            if resolved is None:
                self.send(
                    conversation_id,
                    "我还不能确认你是谁。请在 Desktop 的渠道配置中生成绑定码，再发送“绑定 123456”。",
                )
                return
            person, _binding = resolved
            person_id = person.person_id
            if not is_group:
                session_id = f"feishu-{person_id}"
                people.store.ensure_person_session(session_id, person_id)

            # 注册 peer（确保 Router 能匹配到）
            has_route = (
                router.has_route(session_id, "feishu", conversation_id)
                if hasattr(router, "has_route") else False
            )
            if not has_route:
                router.register_peer(
                    peer_type="human", peer_id=person_id,
                    channel="feishu", session_id=session_id,
                    output_type="feishu", output_target=conversation_id,
                    priority=10,
                )

            ts = time.strftime("%H:%M:%S")
            logger.info("[Feishu] ──────────────────────────────────────────")
            logger.info("[Feishu/Step1] 收到: sender=%s conv=%s text=%s", sender, conversation_id, text[:80])
            logger.info("[Feishu/Step2] 注册 peer: feishu → session=%s output_target=%s", session_id, conversation_id)
            logger.info("[Feishu/Step3] put_message → Layer 1 队列 (session=%s)", session_id)

            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=text, source="human", channel="feishu",
                    peer_id=person_id, peer_type="human",
                    session_id=session_id,
                    metadata={
                        "external_issuer": issuer,
                        "external_subject": sender,
                        "external_conversation_id": conversation_id,
                        "external_message_id": msg_dict.get("message_id", ""),
                    },
                    reply_channel="feishu",
                    reply_target=conversation_id,
                ))
                # External channels cannot inspect Gateway return values.
                # Surface exceptional admission failures instead of silence.
                reason = getattr(result, "reason", "")
                if reason and not getattr(result, "silent", False):
                    self.send(conversation_id, "这条消息暂时没有接收成功，请稍后重试。")
            else:
                living.put_message(text, source="human", session_id=session_id)
            if hasattr(living, "_debug_log"):
                living._debug_log("feishu", f"{ts} ← {sender}: {text[:80]}")
            logger.info("[Feishu/Step4] 等待主循环处理 (session=%s)", session_id)

        self._channel.set_on_message(on_message)

        def on_card_action(callback: dict) -> tuple[bool, str]:
            value = callback.get("value") or {}
            operator = str(callback.get("operator_open_id", ""))
            conversation_id = str(callback.get("conversation_id", ""))
            expected_conversation = str(value.get("conversation_id", ""))
            if not operator or (
                expected_conversation and conversation_id != expected_conversation
            ):
                return False, "这张卡片不属于当前会话。"

            resolved = people.resolve_verified_identity(issuer, operator) if people else None
            if resolved is None:
                return False, "当前飞书身份尚未绑定。"
            person, _binding = resolved
            session_id = str(value.get("session_id", ""))
            turn_id = str(value.get("turn_id", ""))
            kind = str(value.get("kind", ""))

            if kind == "interaction":
                broker = getattr(living, "_interaction_broker", None)
                response = str(value.get("response", "")).strip()
                accepted = bool(
                    broker
                    and broker.respond(
                        str(value.get("request_id", "")),
                        response,
                        session_id,
                        turn_id,
                        person.person_id,
                    )
                )
                return (
                    (True, f"已选择：{response}")
                    if accepted else (False, "问题已结束或不属于当前会话。")
                )

            if kind == "action":
                broker = getattr(living, "_action_broker", None)
                decision = str(value.get("decision", ""))
                accepted = bool(
                    broker
                    and broker.respond(
                        str(value.get("action_id", "")),
                        decision,
                        session_id,
                        turn_id,
                        person.person_id,
                    )
                )
                if not accepted:
                    return False, "审批已结束或不属于当前会话。"
                return True, "已允许此操作。" if decision == "allow" else "已拒绝此操作。"

            if kind == "assignment_resume":
                from xiaomei_brain.assignments import (
                    ActorType,
                    AssignmentActor,
                    AssignmentConflictError,
                )

                service = getattr(living, "_assignment_service", None)
                scheduler = getattr(living, "_assignment_scheduler", None)
                if service is None or scheduler is None:
                    return False, "委托执行服务尚未就绪。"
                assignment_id = str(value.get("assignment_id", ""))
                response = str(value.get("response", "")).strip()
                decision = str(value.get("decision", "")).strip()
                actor = AssignmentActor(ActorType.PERSON, person.person_id)
                try:
                    service.request_resume(
                        assignment_id,
                        actor=actor,
                        response=response,
                        decision=decision,
                        idempotency_key=(
                            f"feishu:{assignment_id}:{person.person_id}:"
                            f"{value.get('revision', '')}:"
                            f"{decision or response or 'continue'}"
                        ),
                    )
                    queued = scheduler.request_resume(
                        assignment_id,
                        trigger_actor_id=person.person_id,
                        response=response,
                        decision=decision,
                    )
                except (ValueError, PermissionError, AssignmentConflictError) as exc:
                    return False, str(exc)
                return (
                    (True, "委托已继续执行。")
                    if queued else (False, "委托暂时无法继续。")
                )

            return False, "无法识别这张卡片的操作。"

        self._channel.set_on_card_action(on_card_action)
        self._channel.start()
        logger.info("[FeishuAdapter] 通道已启动")

    def shutdown(self) -> None:
        """关闭飞书通道。"""
        if self._channel:
            try:
                self._channel.stop()
                logger.info("[FeishuAdapter] 通道已关闭")
            except Exception as e:
                logger.warning("[FeishuAdapter] 关闭通道失败: %s", e)

    def status(self) -> dict:
        return self._channel.status()

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        logger.info("[FeishuAdapter] Router.deliver → target=%s text=%s", target, text[:80])
        msg = OutboundMsg(text=text)
        self._channel.send(target, msg)

    def send_audio(self, target: str, audio) -> bool:
        """Expose the Feishu chat as a remote speech body."""
        from xiaomei_brain.media_services.audio import encode_speech_as_opus

        encoded = encode_speech_as_opus(audio)
        return self._channel.send_audio(
            target,
            f"xiaomei-{int(time.time() * 1000)}.opus",
            encoded.data,
            encoded.duration_ms,
        )

    def _handle_audio_message(
        self,
        msg_dict: dict,
        living,
        router,
        people,
        issuer: str,
    ) -> None:
        """Use Feishu as a remote ear, then enter through the normal Gateway."""
        conversation_id = str(msg_dict.get("conversation_id", ""))
        sender = str(msg_dict.get("sender", ""))
        try:
            if msg_dict.get("chat_type", "p2p") != "p2p":
                logger.info("[Feishu/Audio] group voice is ignored without a mention")
                return
            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            if resolved is None:
                self.send(
                    conversation_id,
                    "我收到了一段语音，但还不能确认你是谁。请先在 Desktop 中完成身份绑定。",
                )
                return
            person, _binding = resolved
            session_id = f"feishu-{person.person_id}"
            people.store.ensure_person_session(session_id, person.person_id)
            if not router.has_route(session_id, "feishu", conversation_id):
                router.register_peer(
                    peer_type="human",
                    peer_id=person.person_id,
                    channel="feishu",
                    session_id=session_id,
                    output_type="feishu",
                    output_target=conversation_id,
                    priority=10,
                )

            audio_data = self._channel.download_message_resource(
                str(msg_dict.get("message_id", "")),
                str(msg_dict.get("file_key", "")),
            )
            from xiaomei_brain.body.perception.remote_audio import (
                RemoteAudioPerception,
            )
            result = RemoteAudioPerception().perceive(audio_data)
            text = str(result.get("text", "")).strip()
            if not text:
                self.send(conversation_id, "我听到了语音，但没能辨认出其中的内容。")
                return

            from xiaomei_brain.gateway.attachments import prepare_attachments
            attachment_id = f"audio_{uuid.uuid4().hex}"
            attachments, _images, _paths = prepare_attachments(
                getattr(living, "_agent_id", "default"),
                session_id,
                [{
                    "id": attachment_id,
                    "name": f"{attachment_id}.opus",
                    "mime_type": "audio/opus",
                    "size": len(audio_data),
                    "data_base64": base64.b64encode(audio_data).decode("ascii"),
                }],
            )
            gateway = getattr(living, "_gateway_inbound", None)
            if gateway is None:
                raise RuntimeError("Gateway 尚未初始化")
            from xiaomei_brain.gateway.inbound import RawMessage
            admission = gateway.accept(RawMessage(
                content=text,
                source="human",
                channel="feishu",
                peer_id=person.person_id,
                peer_type="human",
                session_id=session_id,
                attachments=attachments,
                metadata={
                    "external_issuer": issuer,
                    "external_subject": sender,
                    "external_conversation_id": conversation_id,
                    "external_message_id": msg_dict.get("message_id", ""),
                    "message_type": "audio",
                    "audio_duration_ms": int(msg_dict.get("duration", 0) or 0),
                    "speech_emotion": str(result.get("emotion", "")),
                    "speech_events": list(result.get("events", []) or []),
                },
                reply_channel="feishu",
                reply_target=conversation_id,
            ))
            reason = getattr(admission, "reason", "")
            if reason and not getattr(admission, "silent", False):
                self.send(conversation_id, "这段语音暂时没有接收成功，请稍后重试。")
        except Exception:
            logger.exception("[Feishu/Audio] remote hearing failed")
            try:
                self.send(conversation_id, "这段语音暂时无法处理，请稍后重试。")
            except Exception:
                logger.debug("Failed to report Feishu audio error", exc_info=True)

    def send_event(
        self,
        target: str,
        event: str,
        payload: dict,
        *,
        session_id: str = "",
        turn_id: str = "",
        timestamp: int = 0,
    ) -> None:
        """Render structured interaction events as native Feishu cards."""
        if event == "interaction.requested":
            choices = [
                str(item).strip()
                for item in payload.get("choices", [])
                if str(item).strip()
            ]
            if choices:
                logger.info(
                    "[Feishu/Card] sending Clarify card: target=%s "
                    "request=%s choices=%d",
                    target,
                    payload.get("id", ""),
                    len(choices[:4]),
                )
                self._channel.send_card(
                    target,
                    self._interaction_card(
                        payload,
                        choices[:4],
                        target,
                        session_id,
                        turn_id,
                    ),
                )
                return
        elif event == "action.proposed":
            self._channel.send_card(
                target,
                self._action_card(payload, target, session_id, turn_id),
            )
            return
        elif event == "artifact.presented":
            artifact_id = str(payload.get("id", ""))
            if session_id and artifact_id:
                artifact_session_id = str(payload.get("session_id") or session_id)
                threading.Thread(
                    target=self._send_conversation_artifact,
                    args=(target, artifact_session_id, dict(payload)),
                    name=f"feishu-artifact-{artifact_id[:8]}",
                    daemon=True,
                ).start()
            return
        elif event.startswith("assignment."):
            # Assignment progress updates one existing card, so lifecycle
            # detail stays visible without adding messages to the chat.
            if event == "assignment.changed":
                self._send_assignment_notice(target, payload, session_id)
            return
        super().send_event(
            target,
            event,
            payload,
            session_id=session_id,
            turn_id=turn_id,
            timestamp=timestamp,
        )

    def _send_conversation_artifact(
        self,
        target: str,
        session_id: str,
        descriptor: dict,
    ) -> None:
        """Send one persisted conversation artifact back to its Feishu chat."""
        artifact_id = str(descriptor.get("id", ""))
        if not artifact_id:
            return
        delivery_key = (
            target,
            session_id,
            artifact_id,
            str(descriptor.get("turn_id") or ""),
        )
        with self._artifact_delivery_lock:
            if (
                delivery_key in self._artifact_deliveries_inflight
                or delivery_key in self._artifact_deliveries_sent
            ):
                return
            self._artifact_deliveries_inflight.add(delivery_key)

        delivered = False
        display_name = str(descriptor.get("name") or artifact_id)
        try:
            living = self._living
            db = getattr(getattr(living, "agent", None), "conversation_db", None)
            if living is None or db is None:
                raise RuntimeError("Agent artifact storage is unavailable")

            from xiaomei_brain.gateway.artifacts import read_stored_artifact

            artifact = db.get_artifact_metadata(session_id, artifact_id)
            if artifact is None:
                raise RuntimeError("Conversation artifact does not exist")
            stored = read_stored_artifact(
                getattr(living, "_agent_id", "default"),
                session_id,
                artifact,
            )
            display_name = str(stored.get("name") or display_name)
            data = base64.b64decode(stored["data_base64"], validate=True)
            delivered = self._channel.send_file(target, display_name, data)
            if not delivered:
                logger.warning(
                    "[Feishu/Artifact] failed to deliver conversation artifact: %s",
                    artifact_id,
                )
        except Exception:
            logger.exception(
                "[Feishu/Artifact] conversation artifact delivery failed: %s",
                artifact_id,
            )
        finally:
            with self._artifact_delivery_lock:
                self._artifact_deliveries_inflight.discard(delivery_key)
                if delivered:
                    self._artifact_deliveries_sent.add(delivery_key)

        if not delivered:
            self.send(
                target,
                f"产物“{display_name}”未能通过飞书发送，请在 Desktop 中查看。",
            )

    def _send_assignment_notice(
        self,
        target: str,
        payload: dict,
        session_id: str,
    ) -> None:
        assignment_id = str(payload.get("id", ""))
        status = str(payload.get("status", ""))
        if not assignment_id or status not in {
            "accepted",
            "queued",
            "in_progress",
            "waiting_person",
            "paused",
            "completed",
            "failed",
            "cancelled",
            "declined",
        }:
            return
        detail_key = str(
            payload.get("waiting_reason")
            or payload.get("terminal_reason")
            or payload.get("progress_summary")
            or ""
        )
        delivery_key = (assignment_id, target)
        try:
            revision = max(0, int(payload.get("revision", 0) or 0))
        except (TypeError, ValueError):
            revision = 0
        pending = self._assignment_pending(assignment_id)
        notice_key = (
            status,
            detail_key,
            payload.get("completed_steps"),
            payload.get("total_steps"),
            repr(pending),
        )
        card = self._assignment_card(payload, pending, target, session_id)

        # A status card is one durable external representation of an
        # Assignment. Serialize create/update decisions so concurrent worker
        # notifications cannot create duplicate cards or apply stale states.
        with self._assignment_notice_lock:
            if self._assignment_notices.get(delivery_key) == notice_key:
                return
            binding = self._get_assignment_card_binding(assignment_id, target)
            if binding is not None and revision <= binding.last_revision:
                return

            message_id = binding.external_message_id if binding else ""
            updated = False
            update_card = getattr(self._channel, "update_card", None)
            if message_id and callable(update_card):
                updated = bool(update_card(message_id, card))
            if not updated:
                message_id = str(self._channel.send_card(target, card) or "")
            if not message_id:
                logger.warning(
                    "[Feishu/Assignment] status card delivery failed: %s",
                    assignment_id,
                )
                return

            self._save_assignment_card_binding(
                AssignmentChannelMessage(
                    assignment_id=assignment_id,
                    channel="feishu",
                    account_id=str(getattr(self._channel, "account_id", "default")),
                    conversation_id=target,
                    external_message_id=message_id,
                    last_revision=revision,
                    updated_at=time.time(),
                ),
            )
            self._assignment_notices[delivery_key] = notice_key
        if status == "completed" and payload.get("deliverables"):
            # File uploads are network I/O and must not hold the Assignment
            # worker after its durable completion has already been committed.
            threading.Thread(
                target=self._send_assignment_deliverables,
                args=(target, assignment_id, list(payload["deliverables"])),
                name=f"feishu-deliver-{assignment_id[:8]}",
                daemon=True,
            ).start()

    def _get_assignment_card_binding(
        self,
        assignment_id: str,
        target: str,
    ) -> AssignmentChannelMessage | None:
        key = (assignment_id, target)
        cached = self._assignment_card_bindings.get(key)
        if cached is not None:
            return cached
        living = self._living
        service = getattr(living, "_assignment_service", None) if living else None
        store = getattr(service, "store", None)
        getter = getattr(store, "get_channel_message", None)
        if callable(getter):
            try:
                stored = getter(
                    assignment_id,
                    "feishu",
                    str(getattr(self._channel, "account_id", "default")),
                    target,
                )
                if stored is not None:
                    self._assignment_card_bindings[key] = stored
                    return stored
            except Exception:
                logger.exception(
                    "[Feishu/Assignment] failed to load card binding: %s",
                    assignment_id,
                )
        return None

    def _save_assignment_card_binding(
        self,
        binding: AssignmentChannelMessage,
    ) -> None:
        key = (binding.assignment_id, binding.conversation_id)
        living = self._living
        service = getattr(living, "_assignment_service", None) if living else None
        store = getattr(service, "store", None)
        upsert = getattr(store, "upsert_channel_message", None)
        if callable(upsert):
            try:
                binding = upsert(binding)
            except Exception:
                # The in-memory binding still prevents duplicate cards in the
                # current process; a later event can retry durable persistence.
                logger.exception(
                    "[Feishu/Assignment] failed to persist card binding: %s",
                    binding.assignment_id,
                )
        self._assignment_card_bindings[key] = binding

    def _assignment_pending(self, assignment_id: str) -> dict:
        living = self._living
        service = getattr(living, "_assignment_service", None) if living else None
        if service is None:
            return {}
        try:
            for run in service.store.list_runs(assignment_id):
                if not run.safe_to_resume or not run.checkpoint:
                    continue
                action = run.checkpoint.get("pending_action")
                if isinstance(action, dict):
                    return {
                        "kind": "action",
                        "summary": str(action.get("summary", "")),
                        "reason": str(action.get("reason", "")),
                    }
                interaction = run.checkpoint.get("pending_interaction")
                if isinstance(interaction, dict):
                    raw_choices = interaction.get("choices")
                    choices = raw_choices if isinstance(raw_choices, (list, tuple)) else []
                    return {
                        "kind": "interaction",
                        "question": str(interaction.get("question", "")),
                        "choices": [
                            str(choice)
                            for choice in choices[:4]
                            if str(choice).strip()
                        ],
                    }
                break
        except Exception:
            logger.exception(
                "[Feishu/Assignment] failed to inspect checkpoint: %s",
                assignment_id,
            )
        return {}

    def _send_assignment_deliverables(
        self,
        target: str,
        assignment_id: str,
        deliverables: list[dict],
    ) -> None:
        living = self._living
        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        if living is None or db is None:
            logger.warning(
                "[Feishu/Assignment] artifact storage unavailable: %s",
                assignment_id,
            )
            return
        from xiaomei_brain.gateway.artifacts import ArtifactError, read_stored_artifact

        for descriptor in deliverables[:10]:
            artifact_id = str(descriptor.get("id", ""))
            if not artifact_id:
                continue
            try:
                artifact = db.get_artifact_metadata(
                    f"assignment:{assignment_id}",
                    artifact_id,
                )
                if artifact is None:
                    raise ArtifactError("委托产物不存在")
                stored = read_stored_artifact(
                    getattr(living, "_agent_id", "default"),
                    f"assignment:{assignment_id}",
                    artifact,
                )
                data = base64.b64decode(stored["data_base64"], validate=True)
                if not self._channel.send_file(
                    target,
                    str(stored.get("name") or artifact_id),
                    data,
                ):
                    logger.warning(
                        "[Feishu/Assignment] failed to deliver artifact: %s",
                        artifact_id,
                    )
            except (ArtifactError, ValueError):
                logger.exception(
                    "[Feishu/Assignment] invalid deliverable: %s",
                    artifact_id,
                )

    @staticmethod
    def _assignment_card(
        payload: dict,
        pending: dict,
        conversation_id: str,
        session_id: str,
    ) -> dict:
        status = str(payload.get("status", ""))
        labels = {
            "accepted": ("blue", "委托已接受"),
            "queued": ("blue", "已接受委托"),
            "in_progress": ("blue", "委托执行中"),
            "waiting_person": ("orange", "委托等待回复"),
            "paused": ("orange", "委托已暂停"),
            "completed": ("green", "委托已完成"),
            "failed": ("red", "委托执行失败"),
            "cancelled": ("grey", "委托已取消"),
            "declined": ("grey", "委托未接受"),
        }
        template, heading = labels.get(status, ("blue", "委托状态更新"))
        title = str(payload.get("title") or payload.get("objective") or "未命名委托")
        detail = str(
            payload.get("waiting_reason")
            or payload.get("terminal_reason")
            or payload.get("progress_summary")
            or ""
        )
        completed = payload.get("completed_steps")
        total = payload.get("total_steps")
        lines = [f"**{title}**"]
        if detail:
            lines.append(detail)
        if completed is not None and total:
            lines.append(f"进度：{completed}/{total}")
        if status == "waiting_person" and pending.get("question"):
            lines.append(str(pending["question"]))
        elif status == "waiting_person" and pending.get("summary"):
            lines.append(str(pending["summary"]))
            if pending.get("reason"):
                lines.append(str(pending["reason"]))
        if (
            status == "waiting_person"
            and pending.get("kind") != "action"
            and not pending.get("choices")
        ):
            lines.append("请直接回复这条会话，Agent 会从原进度继续。")

        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(lines)}}
        ]

        def resume_value(*, response: str = "", decision: str = "") -> dict:
            return {
                "kind": "assignment_resume",
                "assignment_id": str(payload.get("id", "")),
                "revision": payload.get("revision"),
                "response": response,
                "decision": decision,
                "conversation_id": conversation_id,
                "session_id": session_id,
            }

        actions = []
        if status == "waiting_person" and pending.get("kind") == "action":
            actions = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "允许"},
                    "type": "primary",
                    "value": resume_value(decision="approve"),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "拒绝"},
                    "type": "danger",
                    "value": resume_value(decision="deny"),
                },
            ]
        elif status == "waiting_person" and pending.get("choices"):
            actions = [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": choice},
                    "type": "primary" if index == 0 else "default",
                    "value": resume_value(response=choice),
                }
                for index, choice in enumerate(pending["choices"])
            ]
        elif status == "paused":
            actions = [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "继续执行"},
                "type": "primary",
                "value": resume_value(),
            }]
        if actions:
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": heading},
            },
            "elements": elements,
        }

    @staticmethod
    def _interaction_card(
        payload: dict,
        choices: list[str],
        conversation_id: str,
        session_id: str,
        turn_id: str,
    ) -> dict:
        question = str(payload.get("question", "")).strip()
        request_id = str(payload.get("id", ""))
        actions = []
        for index, choice in enumerate(choices):
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": choice},
                "type": "primary" if index == 0 else "default",
                "value": {
                    "kind": "interaction",
                    "request_id": request_id,
                    "response": choice,
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                },
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "想和你确认"},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": question}},
                {"tag": "action", "actions": actions},
            ],
        }

    @staticmethod
    def _action_card(
        payload: dict,
        conversation_id: str,
        session_id: str,
        turn_id: str,
    ) -> dict:
        action_id = str(payload.get("id", ""))
        summary = str(payload.get("summary", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        risk = str(payload.get("risk_level", "")).strip()
        detail = summary
        if reason:
            detail += f"\n\n**原因：** {reason}"
        if risk:
            detail += f"\n\n**风险级别：** {risk}"

        def value(decision: str) -> dict:
            return {
                "kind": "action",
                "action_id": action_id,
                "decision": decision,
                "conversation_id": conversation_id,
                "session_id": session_id,
                "turn_id": turn_id,
            }

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"tag": "plain_text", "content": "需要你的确认"},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": detail}},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "允许"},
                            "type": "primary",
                            "value": value("allow"),
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "拒绝"},
                            "type": "danger",
                            "value": value("deny"),
                        },
                    ],
                },
            ],
        }
