"""DingTalkAdapter — 钉钉通道适配器。

基于 dingtalk-stream SDK（官方），和飞书 FeishuAdapter 模式一致：
- SDK WebSocket 接收消息 → 内联回调 → Router + living.put_message()
- Router.deliver() → adapter.send() → SDK reply_text/markdown

不依赖 ConsciousLiving 上的特定回调方法，新增频道无需改 ConsciousLiving。
"""

from __future__ import annotations

import base64
import logging
import json
import re
import threading
import time
import uuid

from xiaomei_brain.assignments.models import AssignmentChannelMessage
from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities
from .client import DingTalkClient

logger = logging.getLogger(__name__)


def register(ctx):
    """插件入口：从 config.json 读取配置，注册钉钉频道。

    兼容新旧命名：clientId/clientSecret 优先，appKey/appSecret 兜底。
    """
    client_id = ctx.config.get("clientId") or ctx.config.get("appKey", "")
    client_secret = ctx.config.get("clientSecret") or ctx.config.get("appSecret", "")

    if not client_id or not client_secret:
        ctx.logger.warning("钉钉配置缺失（clientId/clientSecret），跳过注册")
        return

    ctx.register_channel("dingtalk", create_adapter(ctx.config))


def create_adapter(config: dict) -> "DingTalkAdapter":
    """Build an adapter from a normalized DingTalk account configuration."""
    client_id = (
        config.get("clientId")
        or config.get("appId")
        or config.get("appKey")
        or ""
    )
    client_secret = (
        config.get("clientSecret")
        or config.get("appSecret")
        or ""
    )
    if not client_id or not client_secret:
        raise ValueError("钉钉 Client ID 和 Client Secret 不能为空")
    account_id = config.get("accountId") or config.get("account_id") or "default"
    card_template_id = (
        config.get("cardTemplateId")
        or config.get("card_template_id")
        or ""
    )
    options = {"account_id": account_id}
    if card_template_id:
        options["card_template_id"] = card_template_id
    return DingTalkAdapter(DingTalkClient(client_id, client_secret, **options))


class DingTalkAdapter(ChannelAdapter):
    """钉钉通道适配器。

    消息流：
    1. SDK WebSocket 接收 → on_message 回调 → Router.register_peer() + living.put_message()
    2. Core 处理后 Router.deliver() → adapter.send() → client.reply(session_webhook, text)
    """

    def __init__(self, client: DingTalkClient) -> None:
        self._client = client
        # 缓存：session_id → {"session_webhook": ..., "sdk_message": ChatbotMessage}
        self._sessions: dict[str, dict] = {}
        self._sessions_lock = threading.Lock()
        self._living = None
        self._card_actions: dict[str, dict[str, dict]] = {}
        self._card_actions_lock = threading.Lock()
        self._assignment_notices: dict[
            tuple[str, str], tuple[object, ...]
        ] = {}
        self._assignment_card_bindings: dict[
            tuple[str, str], AssignmentChannelMessage
        ] = {}
        self._assignment_notice_lock = threading.Lock()
        self._artifact_delivery_lock = threading.Lock()
        self._artifact_deliveries_inflight: set[tuple[str, str, str]] = set()
        self._artifact_deliveries_sent: set[tuple[str, str, str]] = set()

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
        return "dingtalk"

    @property
    def embodiment_id(self) -> str:
        return f"dingtalk:{self._client.client_id}"

    @property
    def embodiment_label(self) -> str:
        return "钉钉机器人"

    @property
    def exposes_embodiment(self) -> bool:
        return True

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        """向钉钉用户/群发送消息。Core 通过 Router.deliver() 调用此方法。

        优先使用 SDK 的 sessionWebhook 回复（含 @发送者），
        缓存过期则降级为主动发送。
        """
        logger.info("[DingTalkAdapter] Router.deliver -> target=%s text=%s", target, text[:80])

        # 自动检测 Markdown
        msg_type = "text"
        if any(c in text for c in "#*>-[]`_") and "\n" in text:
            msg_type = "markdown"

        # 优先使用缓存的 session 信息回复
        with self._sessions_lock:
            session = self._sessions.get(target)
        if session:
            webhook = session.get("session_webhook", "")
            sdk_msg = session.get("sdk_message")
            if webhook:
                ok = self._client.reply(webhook, text, msg_type, incoming_msg=sdk_msg)
                if ok:
                    return
            # 回复失败，清除过期缓存
            with self._sessions_lock:
                self._sessions.pop(target, None)

        # 降级：主动发送
        is_group = target.startswith("cid")
        self._client.send(target, text, msg_type, is_group=is_group)

    def send_audio(self, target: str, audio) -> bool:
        """Expose a DingTalk robot as a remote speech body."""
        from xiaomei_brain.media_services.audio import encode_speech_as_opus

        encoded = encode_speech_as_opus(audio)
        with self._sessions_lock:
            session = dict(self._sessions.get(target) or {})
        is_group = bool(session.get("is_group", target.startswith("cid")))
        return self._client.send_audio(
            target,
            f"xiaomei-{int(time.time() * 1000)}.ogg",
            encoded.data,
            encoded.duration_ms,
            is_group=is_group,
        )

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
        """Render interaction protocol events as DingTalk cards."""
        if event == "interaction.requested":
            choices = [
                str(item).strip()
                for item in payload.get("choices", [])
                if str(item).strip()
            ][:4]
            if choices:
                actions = []
                buttons = []
                for index, choice in enumerate(choices):
                    action_id = f"choice-{index}-{uuid.uuid4().hex[:8]}"
                    buttons.append((action_id, choice, index == 0))
                    actions.append((action_id, {
                        "kind": "interaction",
                        "request_id": str(payload.get("id", "")),
                        "response": choice,
                        "conversation_id": target,
                        "session_id": session_id,
                        "turn_id": turn_id,
                    }))
                card_id = self._send_interactive_card(
                    target,
                    "想和你确认",
                    str(payload.get("question", "")),
                    buttons,
                    dict(actions),
                )
                if card_id:
                    return
        elif event == "action.proposed":
            summary = str(payload.get("summary", ""))
            reason = str(payload.get("reason", ""))
            markdown = f"**{summary}**"
            if reason:
                markdown += f"\n\n原因：{reason}"
            allow_id = f"allow-{uuid.uuid4().hex[:8]}"
            deny_id = f"deny-{uuid.uuid4().hex[:8]}"
            common = {
                "kind": "action",
                "action_id": str(payload.get("id", "")),
                "conversation_id": target,
                "session_id": session_id,
                "turn_id": turn_id,
            }
            card_id = self._send_interactive_card(
                target,
                "需要你的确认",
                markdown,
                [(allow_id, "允许", True), (deny_id, "拒绝", False)],
                {
                    allow_id: {**common, "decision": "allow"},
                    deny_id: {**common, "decision": "deny"},
                },
            )
            if card_id:
                return
        elif event.startswith("assignment."):
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

    def _is_group_target(self, target: str) -> bool:
        with self._sessions_lock:
            session = self._sessions.get(target) or {}
        if "is_group" in session:
            return bool(session["is_group"])
        return target.startswith("cid")

    @staticmethod
    def _card_data(
        title: str,
        markdown: str,
        buttons: list[tuple[str, str, bool]],
    ) -> dict:
        order = ["msgTitle", "staticMsgContent"]
        full: dict = {"order": order}
        if buttons:
            order.append("msgButtons")
            full["msgButtons"] = [
                {
                    "text": label,
                    "color": "blue" if primary else "gray",
                    "id": action_id,
                    "request": True,
                }
                for action_id, label, primary in buttons
            ]
        return {
            "msgTitle": title,
            "staticMsgContent": markdown,
            "flowStatus": "3",
            "sys_full_json_obj": json.dumps(full, ensure_ascii=False),
        }

    def _send_interactive_card(
        self,
        target: str,
        title: str,
        markdown: str,
        buttons: list[tuple[str, str, bool]],
        actions: dict[str, dict],
        *,
        out_track_id: str = "",
    ) -> str:
        out_track_id = out_track_id or self._client.new_card_id()
        with self._card_actions_lock:
            self._card_actions[out_track_id] = actions
        delivered = self._client.send_card(
            target,
            self._card_data(title, markdown, buttons),
            is_group=self._is_group_target(target),
            out_track_id=out_track_id,
        )
        if not delivered:
            with self._card_actions_lock:
                self._card_actions.pop(out_track_id, None)
        return delivered

    def _handle_card_action(self, callback: dict) -> tuple[bool, str]:
        out_track_id = str(callback.get("out_track_id", ""))
        operator = str(callback.get("operator_user_id", ""))
        action_ids = callback.get("action_ids") or []
        params = callback.get("params") or {}
        candidates = [str(item) for item in action_ids if str(item)]
        for key in ("action", "actionId", "id", "buttonId"):
            value = str(params.get(key, ""))
            if value and value not in candidates:
                candidates.append(value)
        if not out_track_id or not operator or not candidates:
            return False, "无法识别这次卡片操作。"

        with self._card_actions_lock:
            card_actions = self._card_actions.get(out_track_id) or {}
            value = {}
            action_id = ""
            for candidate in candidates:
                if candidate in card_actions:
                    action_id = candidate
                    value = dict(card_actions[candidate])
                    break
        if not value:
            for candidate in candidates:
                value = self._recover_assignment_action(out_track_id, candidate)
                if value:
                    action_id = candidate
                    break
        if not value:
            return False, "这张卡片已经失效。"

        expected_conversation = str(value.get("conversation_id", ""))
        callback_space = str(callback.get("space_id", ""))
        callback_space_type = str(callback.get("space_type", "")).upper()
        if callback_space.startswith("dtv1.card//") and "." in callback_space:
            callback_space = callback_space.rsplit(".", 1)[1]
        # In private robot space DingTalk may return an internal space ID that
        # differs from senderStaffId. The verified operator identity is the
        # authority there. Group cards, however, must stay in their group.
        if (
            callback_space_type == "IM_GROUP"
            and callback_space
            and expected_conversation
            and callback_space != expected_conversation
        ):
            return False, "这张卡片不属于当前会话。"

        living = self._living
        people = getattr(living, "_people_service", None) if living else None
        issuer = f"dingtalk:app:{self._client.client_id}"
        resolved = (
            people.resolve_verified_identity(issuer, operator)
            if people else None
        )
        if resolved is None:
            return False, "当前钉钉身份尚未绑定。"
        person, _binding = resolved
        session_id = str(value.get("session_id", ""))
        turn_id = str(value.get("turn_id", ""))
        kind = str(value.get("kind", ""))

        if kind == "interaction":
            broker = getattr(living, "_interaction_broker", None)
            response = str(value.get("response", "")).strip()
            accepted = bool(
                broker and broker.respond(
                    str(value.get("request_id", "")),
                    response,
                    session_id,
                    turn_id,
                    person.person_id,
                )
            )
            if accepted:
                with self._card_actions_lock:
                    self._card_actions.pop(out_track_id, None)
            return (
                (True, f"已选择：{response}")
                if accepted else (False, "问题已结束或不属于当前会话。")
            )

        if kind == "action":
            broker = getattr(living, "_action_broker", None)
            decision = str(value.get("decision", ""))
            accepted = bool(
                broker and broker.respond(
                    str(value.get("action_id", "")),
                    decision,
                    session_id,
                    turn_id,
                    person.person_id,
                )
            )
            if accepted:
                with self._card_actions_lock:
                    self._card_actions.pop(out_track_id, None)
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
                        f"dingtalk:{assignment_id}:{person.person_id}:"
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
        try:
            revision = max(0, int(payload.get("revision", 0) or 0))
        except (TypeError, ValueError):
            revision = 0
        pending = self._assignment_pending(assignment_id)
        title, markdown, buttons, actions = self._assignment_card_content(
            payload,
            pending,
            target,
            session_id,
        )
        notice_key = (
            status,
            markdown,
            repr(pending),
        )
        delivery_key = (assignment_id, target)

        with self._assignment_notice_lock:
            if self._assignment_notices.get(delivery_key) == notice_key:
                return
            binding = self._get_assignment_card_binding(assignment_id, target)
            if binding is not None and revision <= binding.last_revision:
                return

            card_data = self._card_data(title, markdown, buttons)
            out_track_id = binding.external_message_id if binding else ""
            if out_track_id:
                with self._card_actions_lock:
                    self._card_actions[out_track_id] = actions
                updated = self._client.update_card(out_track_id, card_data)
            else:
                updated = False
            if not updated:
                out_track_id = self._send_interactive_card(
                    target,
                    title,
                    markdown,
                    buttons,
                    actions,
                )
            if not out_track_id:
                logger.warning(
                    "[DingTalk/Assignment] status card delivery failed: %s",
                    assignment_id,
                )
                self.send(target, f"{title}\n\n{markdown}")
                return

            self._save_assignment_card_binding(
                AssignmentChannelMessage(
                    assignment_id=assignment_id,
                    channel="dingtalk",
                    account_id=str(getattr(self._client, "account_id", "default")),
                    conversation_id=target,
                    external_message_id=out_track_id,
                    last_revision=revision,
                    updated_at=time.time(),
                ),
            )
            self._assignment_notices[delivery_key] = notice_key

        if status == "completed" and payload.get("deliverables"):
            # The persisted card revision is also the delivery gate. Starting
            # the upload only after that gate prevents a replayed completion
            # event from sending the same files again after Agent restart.
            threading.Thread(
                target=self._send_assignment_deliverables,
                args=(target, assignment_id, list(payload["deliverables"])),
                name=f"dingtalk-deliver-{assignment_id[:8]}",
                daemon=True,
            ).start()

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
                "[DingTalk/Assignment] artifact storage unavailable: %s",
                assignment_id,
            )
            return
        from xiaomei_brain.gateway.artifacts import ArtifactError, read_stored_artifact

        for descriptor in deliverables[:10]:
            artifact_id = str(descriptor.get("id", ""))
            if not artifact_id:
                continue
            delivery_key = (target, assignment_id, artifact_id)
            with self._artifact_delivery_lock:
                if (
                    delivery_key in self._artifact_deliveries_inflight
                    or delivery_key in self._artifact_deliveries_sent
                ):
                    continue
                self._artifact_deliveries_inflight.add(delivery_key)

            delivered = False
            display_name = str(descriptor.get("name") or artifact_id)
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
                display_name = str(stored.get("name") or display_name)
                data = base64.b64decode(stored["data_base64"], validate=True)
                delivered = self._client.send_file(
                    target,
                    display_name,
                    data,
                    is_group=self._is_group_target(target),
                )
                if not delivered:
                    logger.warning(
                        "[DingTalk/Assignment] failed to deliver artifact: %s",
                        artifact_id,
                    )
            except (ArtifactError, ValueError):
                logger.exception(
                    "[DingTalk/Assignment] invalid deliverable: %s",
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
                    f"产物“{display_name}”未能通过钉钉发送，请在 Desktop 中查看。",
                )

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
                "[DingTalk/Assignment] failed to inspect checkpoint: %s",
                assignment_id,
            )
        return {}

    @staticmethod
    def _assignment_card_content(
        payload: dict,
        pending: dict,
        conversation_id: str,
        session_id: str,
    ) -> tuple[str, str, list[tuple[str, str, bool]], dict[str, dict]]:
        status = str(payload.get("status", ""))
        headings = {
            "accepted": "委托已接受",
            "queued": "已接受委托",
            "in_progress": "委托执行中",
            "waiting_person": "委托等待回复",
            "paused": "委托已暂停",
            "completed": "委托已完成",
            "failed": "委托执行失败",
            "cancelled": "委托已取消",
            "declined": "委托未接受",
        }
        heading = headings.get(status, "委托状态更新")
        assignment_title = str(
            payload.get("title") or payload.get("objective") or "未命名委托"
        )
        detail = str(
            payload.get("waiting_reason")
            or payload.get("terminal_reason")
            or payload.get("progress_summary")
            or ""
        )
        lines = [f"**{assignment_title}**"]
        if detail:
            lines.append(detail)
        completed = payload.get("completed_steps")
        total = payload.get("total_steps")
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
            lines.append("请直接回复当前会话，Agent 会从原进度继续。")

        common = {
            "kind": "assignment_resume",
            "assignment_id": str(payload.get("id", "")),
            "revision": payload.get("revision"),
            "conversation_id": conversation_id,
            "session_id": session_id,
        }
        buttons: list[tuple[str, str, bool]] = []
        actions: dict[str, dict] = {}
        if status == "waiting_person" and pending.get("kind") == "action":
            buttons = [
                ("assignment-approve", "允许", True),
                ("assignment-deny", "拒绝", False),
            ]
            actions = {
                "assignment-approve": {**common, "decision": "approve"},
                "assignment-deny": {**common, "decision": "deny"},
            }
        elif status == "waiting_person" and pending.get("choices"):
            for index, choice in enumerate(pending["choices"]):
                action_id = f"assignment-choice-{index}"
                buttons.append((action_id, choice, index == 0))
                actions[action_id] = {**common, "response": choice}
        elif status == "paused":
            buttons = [("assignment-continue", "继续执行", True)]
            actions = {"assignment-continue": common}
        return heading, "\n\n".join(lines), buttons, actions

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
                    "dingtalk",
                    str(getattr(self._client, "account_id", "default")),
                    target,
                )
                if stored is not None:
                    self._assignment_card_bindings[key] = stored
                    return stored
            except Exception:
                logger.exception(
                    "[DingTalk/Assignment] failed to load card binding: %s",
                    assignment_id,
                )
        return None

    def _save_assignment_card_binding(
        self,
        binding: AssignmentChannelMessage,
    ) -> None:
        living = self._living
        service = getattr(living, "_assignment_service", None) if living else None
        store = getattr(service, "store", None)
        upsert = getattr(store, "upsert_channel_message", None)
        if callable(upsert):
            try:
                binding = upsert(binding)
            except Exception:
                logger.exception(
                    "[DingTalk/Assignment] failed to persist card binding: %s",
                    binding.assignment_id,
                )
        self._assignment_card_bindings[
            (binding.assignment_id, binding.conversation_id)
        ] = binding

    def _recover_assignment_action(
        self,
        out_track_id: str,
        action_id: str,
    ) -> dict:
        """Recover buttons from durable Assignment state after Agent restart."""
        living = self._living
        service = getattr(living, "_assignment_service", None) if living else None
        store = getattr(service, "store", None)
        finder = getattr(store, "get_channel_message_by_external_id", None)
        if not callable(finder):
            return {}
        try:
            binding = finder(
                "dingtalk",
                str(getattr(self._client, "account_id", "default")),
                out_track_id,
            )
            if binding is None:
                return {}
            assignment = store.get_assignment(binding.assignment_id)
            if assignment is None:
                return {}
            pending = self._assignment_pending(binding.assignment_id)
            _title, _markdown, _buttons, actions = self._assignment_card_content(
                {
                    "id": assignment.id,
                    "status": assignment.status.value,
                    "revision": assignment.revision,
                },
                pending,
                binding.conversation_id,
                assignment.origin_session_id,
            )
            return dict(actions.get(action_id) or {})
        except Exception:
            logger.exception(
                "[DingTalk/Assignment] failed to recover card action: %s",
                out_track_id,
            )
            return {}

    def _handle_audio_message(
        self,
        msg_dict: dict,
        living,
        router,
        people,
        issuer: str,
    ) -> None:
        """Use the DingTalk Embodiment's remote ear without blocking Stream."""
        sender = str(msg_dict.get("sender", ""))
        conversation_id = str(msg_dict.get("conversation_id", ""))
        is_group = bool(msg_dict.get("is_group", False))
        output_target = conversation_id if is_group else sender
        try:
            with self._sessions_lock:
                self._sessions[output_target] = {
                    "is_group": is_group,
                    "conversation_id": conversation_id,
                    "sender": sender,
                    **({
                        "session_webhook": msg_dict.get("session_webhook", ""),
                        "sdk_message": msg_dict.get("sdk_message"),
                    } if msg_dict.get("session_webhook") else {}),
                }

            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            person_id = resolved[0].person_id if resolved is not None else ""
            if is_group:
                session_id = (
                    f"dingtalk-group-{self._client.client_id}-{conversation_id}"
                )
                if people:
                    people.store.ensure_session(
                        session_id,
                        "conversation",
                        f"{issuer}:chat:{conversation_id}",
                        metadata={
                            "channel": "dingtalk",
                            "issuer": issuer,
                            "conversation_id": conversation_id,
                        },
                    )
                if msg_dict.get("bot_mentioned") is not True:
                    gateway = getattr(living, "_gateway_inbound", None)
                    if gateway and hasattr(gateway, "observe_group_message"):
                        from xiaomei_brain.gateway.inbound import RawMessage
                        gateway.observe_group_message(RawMessage(
                            content="[语音]",
                            source="human",
                            channel="dingtalk",
                            peer_id=person_id,
                            peer_type="human",
                            session_id=session_id,
                            metadata={
                                "external_issuer": issuer,
                                "external_subject": sender,
                                "external_conversation_id": conversation_id,
                                "external_message_id": msg_dict.get("msg_id", ""),
                                "sender_display_name": (
                                    msg_dict.get("sender_name") or sender
                                ),
                                "message_type": "audio",
                            },
                        ))
                    return

            if resolved is None:
                self.send(
                    output_target,
                    "我收到了一段语音，但还不能确认你是谁。请先在 Desktop 中完成身份绑定。",
                )
                return
            person, _binding = resolved
            if not is_group:
                session_id = f"dingtalk-{person.person_id}"
                people.store.ensure_person_session(session_id, person.person_id)

            if not router.has_route(session_id, "dingtalk", output_target):
                router.register_peer(
                    peer_type="human",
                    peer_id=person.person_id,
                    channel="dingtalk",
                    session_id=session_id,
                    output_type="dingtalk",
                    output_target=output_target,
                    priority=10,
                )

            downloaded = self._client.download_message_media(
                str(msg_dict.get("download_code", "")),
            )
            if downloaded is None:
                raise RuntimeError("钉钉语音下载失败")
            audio_data, suffix = downloaded

            from xiaomei_brain.body.perception.remote_audio import (
                RemoteAudioPerception,
            )
            perception = RemoteAudioPerception().perceive(audio_data)
            text = str(perception.get("text", "")).strip()
            if not text:
                self.send(output_target, "我听到了语音，但没能辨认出其中的内容。")
                return

            mime_type = {
                ".ogg": "audio/ogg",
                ".amr": "audio/amr",
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
            }.get(suffix.lower(), "audio/ogg")
            saved_suffix = suffix if suffix != ".bin" else ".ogg"
            from xiaomei_brain.gateway.attachments import prepare_attachments
            attachment_id = f"audio_{uuid.uuid4().hex}"
            attachments, _images, _paths = prepare_attachments(
                getattr(living, "_agent_id", "default"),
                session_id,
                [{
                    "id": attachment_id,
                    "name": f"{attachment_id}{saved_suffix}",
                    "mime_type": mime_type,
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
                channel="dingtalk",
                peer_id=person.person_id,
                peer_type="human",
                session_id=session_id,
                attachments=attachments,
                metadata={
                    "external_issuer": issuer,
                    "external_subject": sender,
                    "external_conversation_id": conversation_id,
                    "external_message_id": msg_dict.get("msg_id", ""),
                    "message_type": "audio",
                    "audio_duration_ms": int(msg_dict.get("duration", 0) or 0),
                    "speech_emotion": str(perception.get("emotion", "")),
                    "speech_events": list(perception.get("events", []) or []),
                },
                reply_channel="dingtalk",
                reply_target=output_target,
            ))
            reason = getattr(admission, "reason", "")
            if reason and not getattr(admission, "silent", False):
                self.send(output_target, "这段语音暂时没有接收成功，请稍后重试。")
        except Exception:
            logger.exception("[DingTalk/Audio] remote hearing failed")
            try:
                self.send(output_target, "这段语音暂时无法处理，请稍后重试。")
            except Exception:
                logger.debug("Failed to report DingTalk audio error", exc_info=True)

    def setup(self, living=None) -> None:
        """启动通道，桥接 living 和钉钉消息。

        内联回调闭包捕捉 living._router + living.put_message()。
        """
        if not living or not self._client:
            return

        self._living = living

        router = living._router
        people = getattr(living, "_people_service", None)
        link_service = getattr(living, "_identity_link_service", None)
        issuer = f"dingtalk:app:{self._client.client_id}"
        adapter = self

        def on_message(msg_dict: dict) -> None:
            sender = msg_dict["sender"]
            conversation_id = msg_dict["conversation_id"]
            text = msg_dict["text"]
            is_group = msg_dict["is_group"]
            bot_mentioned = msg_dict.get("bot_mentioned")
            session_webhook = msg_dict.get("session_webhook", "")
            sdk_message = msg_dict.get("sdk_message")
            media_paths = msg_dict.get("media_paths", [])

            if msg_dict.get("msg_type") == "audio":
                threading.Thread(
                    target=self._handle_audio_message,
                    args=(msg_dict, living, router, people, issuer),
                    name="dingtalk-remote-hearing",
                    daemon=True,
                ).start()
                return

            output_target = conversation_id if is_group else sender
            resolved = (
                people.resolve_verified_identity(issuer, sender)
                if people else None
            )
            person_id = resolved[0].person_id if resolved is not None else ""

            if is_group:
                session_id = (
                    f"dingtalk-group-{self._client.client_id}-{conversation_id}"
                )
                if people:
                    people.store.ensure_session(
                        session_id,
                        "conversation",
                        f"{issuer}:chat:{conversation_id}",
                        metadata={
                            "channel": "dingtalk",
                            "issuer": issuer,
                            "conversation_id": conversation_id,
                        },
                    )

                # DingTalk deployments that deliver non-mention group events
                # can use the same observation path. Ordinary robot setups may
                # still only receive explicit mentions from the platform.
                if bot_mentioned is not True:
                    gw = getattr(living, "_gateway_inbound", None)
                    if gw and hasattr(gw, "observe_group_message"):
                        from xiaomei_brain.gateway.inbound import RawMessage
                        gw.observe_group_message(RawMessage(
                            content=text,
                            source="human",
                            channel="dingtalk",
                            peer_id=person_id,
                            peer_type="human",
                            session_id=session_id,
                            metadata={
                                "external_issuer": issuer,
                                "external_subject": sender,
                                "external_conversation_id": conversation_id,
                                "external_message_id": msg_dict.get("msg_id", ""),
                                "sender_display_name": (
                                    msg_dict.get("sender_name") or sender
                                ),
                                "message_type": msg_dict.get("msg_type", "text"),
                            },
                        ))
                    logger.info(
                        "[DingTalk] stored group observation: conversation=%s sender=%s",
                        conversation_id,
                        sender,
                    )
                    return

            # 缓存 session 信息用于回复（key 用 output_target，与 send() 对齐）
            with adapter._sessions_lock:
                adapter._sessions[output_target] = {
                    "is_group": is_group,
                    "conversation_id": conversation_id,
                    "sender": sender,
                    **({
                        "session_webhook": session_webhook,
                        "sdk_message": sdk_message,
                    } if session_webhook else {}),
                }

            match = re.search(
                r"(?:^|\n)\s*(?:绑定|bind)\s+(\d{6})\s*$",
                text,
                re.IGNORECASE,
            )
            if match:
                if is_group:
                    self.send(output_target, "请在与机器人的私聊中完成身份绑定。")
                    return
                try:
                    binding = (
                        link_service.consume(
                            "dingtalk", issuer, sender, match.group(1),
                        )
                        if link_service else None
                    )
                except ValueError as exc:
                    self.send(output_target, str(exc))
                    return
                if binding is None:
                    self.send(
                        output_target,
                        "绑定码无效或已过期，请在 Desktop 中重新生成。",
                    )
                    return
                self.send(output_target, "身份绑定成功，现在我能认出你了。")
                return

            if resolved is None:
                self.send(
                    output_target,
                    "我还不能确认你是谁。请在 Desktop 的渠道配置中生成绑定码，再发送“绑定 123456”。",
                )
                return
            person, _binding = resolved
            person_id = person.person_id
            if not is_group:
                session_id = f"dingtalk-{person_id}"
                people.store.ensure_person_session(session_id, person_id)

            # 注册 Peer 映射
            has_route = (
                router.has_route(session_id, "dingtalk", output_target)
                if hasattr(router, "has_route") else False
            )
            if not has_route:
                router.register_peer(
                    peer_type="human",
                    peer_id=person_id,
                    channel="dingtalk",
                    session_id=session_id,
                    output_type="dingtalk",
                    output_target=output_target,
                    priority=10,
                )

            ts = time.strftime("%H:%M:%S")
            logger.info("[DingTalk] <- %s: %s", sender, text[:80])

            gw = getattr(living, '_gateway_inbound', None)
            if gw:
                from xiaomei_brain.gateway.inbound import RawMessage
                result = gw.accept(RawMessage(
                    content=text, source="human", channel="dingtalk",
                    peer_id=person_id, peer_type="human",
                    images=media_paths, session_id=session_id,
                    metadata={
                        "external_issuer": issuer,
                        "external_subject": sender,
                        "external_conversation_id": conversation_id,
                        "external_message_id": msg_dict.get("msg_id", ""),
                    },
                    reply_channel="dingtalk", reply_target=output_target,
                ))
                reason = getattr(result, "reason", "")
                if reason and not getattr(result, "silent", False):
                    self.send(output_target, "这条消息暂时没有接收成功，请稍后重试。")
            else:
                living.put_message(text, source="human", session_id=session_id,
                                  images=media_paths)
            if hasattr(living, "_debug_log"):
                living._debug_log("dingtalk", f"{ts} <- {sender}: {text[:80]}")

        self._client.set_on_card_action(self._handle_card_action)
        logger.info("[DingTalkAdapter] 注册 on_message 回调，启动 client...")
        self._client.set_on_message(on_message)
        self._client.start()
        logger.info("[DingTalkAdapter] 通道已启动（Stream Mode）")

    def shutdown(self) -> None:
        """关闭钉钉通道。"""
        if self._client:
            try:
                self._client.stop()
                with self._sessions_lock:
                    self._sessions.clear()
                logger.info("[DingTalkAdapter] 通道已关闭")
            except Exception as e:
                logger.warning("[DingTalkAdapter] 关闭通道失败: %s", e)

    def status(self) -> dict:
        return self._client.status()
