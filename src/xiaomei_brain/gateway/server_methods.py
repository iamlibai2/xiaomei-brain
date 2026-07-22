"""Gateway RPC 方法处理 — req → handler → res/event。"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from typing import Any

from .protocol import build_response, build_error, ErrorCode
from .schemas import (
    ConnectParams,
    ChatSendParams,
    ChatRetryParams,
    ChatAbortParams,
    ChatHistoryParams,
    AttachmentGetParams,
    ChatSessionsParams,
    SessionResumeParams,
    InteractionRespondParams,
    ActionRespondParams,
    format_error,
)
from .auth import check_token
from .attachments import (
    AttachmentError,
    attachment_fingerprint,
    cleanup_attachments,
    prepare_attachments,
    read_stored_attachment,
    restore_attachment_refs,
)
from .artifact_methods import ArtifactMethods

logger = logging.getLogger(__name__)


class MethodRouter:
    """将 RPC method 名路由到处理函数。"""

    def __init__(self, living: Any = None, config: Any = None) -> None:
        self._living = living
        self._config = config
        self._handlers: dict[str, callable] = {
            "connect": self._handle_connect,
            "chat.send": self._handle_chat_send,
            "chat.retry": self._handle_chat_retry,
            "chat.abort": self._handle_chat_abort,
            "chat.history": self._handle_chat_history,
            "attachment.get": self._handle_attachment_get,
            "chat.sessions": self._handle_chat_sessions,
            "session.resume": self._handle_session_resume,
            "interaction.respond": self._handle_interaction_respond,
            "action.respond": self._handle_action_respond,
            "identity.list": self._handle_identity_list,
        }
        self._artifact_methods = ArtifactMethods(living)
        self._handlers.update(self._artifact_methods.handlers)
        # 已认证的 session
        self._auth_sessions: set[str] = set()
        self._chat_receipts_lock = threading.Lock()
        self._chat_receipts: OrderedDict[
            tuple[str, str], tuple[str, str, str, dict[str, Any]]
        ] = OrderedDict()

    def dispatch(self, conn_id: str, req_id: str, method: str, params: dict) -> dict:
        """分发 RPC 请求到对应 handler。

        Returns:
            res 帧 dict。
        """
        # 非 connect 方法需要先认证
        if method != "connect" and conn_id not in self._auth_sessions:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "请先 connect")

        handler = self._handlers.get(method)
        if handler is None:
            return build_error(req_id, ErrorCode.METHOD_NOT_FOUND,
                               f"未知方法: {method}")

        try:
            return handler(conn_id, req_id, params)
        except Exception as e:
            logger.error("[MethodRouter] %s 处理失败: %s", method, e)
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(e))

    # ── Handlers ──────────────────────────────

    def _handle_connect(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ConnectParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        if not check_token(p.token, self._config):
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "Token 无效")

        self._auth_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已认证: conn=%s client=%s", conn_id[:8], p.client)

        # 重连：客户端带了之前的 session_id → 复用
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        turn_registry = getattr(self._living, "_turn_registry", None) if self._living else None
        active_turn = turn_registry.snapshot(session_id) if turn_registry is not None else None

        # 设置 user_id 并加载 fresh_tail（WS 连接也需要"带着记忆醒来"）
        if p.user_id and self._living:
            self._living.user_id = p.user_id
            agent_core = self._living.agent._get_agent()
            if agent_core:
                agent_core.user_id = p.user_id
            if active_turn is None:
                self._living.load_fresh_tail()
                # 保存 attention 会话，防止后续 switch_to 覆盖 fresh_tail
                if hasattr(self._living, '_attention') and self._living._attention:
                    ws_sid = f"ws-{session_id}"
                    self._living._attention.save_session(ws_sid)
                    self._living._attention._current_session = ws_sid
                logger.info("[Gateway] fresh_tail 已加载: user_id=%s session=%s", p.user_id, session_id)
            else:
                logger.info(
                    "[Gateway] 活动 Turn 重连，保持现有上下文: session=%s turn=%s",
                    session_id,
                    active_turn.get("turn_id", ""),
                )

        return build_response(req_id, result={
            "session_id": session_id,
            "agent_name": getattr(self._living, "_agent_id", ""),
            "reconnect": bool(p.session_id),
            "protocol_version": 2,
            "capabilities": [
                "message.lifecycle",
                "tool.lifecycle",
                "interaction.question",
                "session.resume",
                "action.approval",
                "message.attachments",
                "attachment.read",
                "artifact.read",
                "artifact.events",
                "message.retry",
            ],
        })

    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSendParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        content = p.content.strip()
        if not content and not p.attachments and not p.attachment_refs:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "消息内容和附件不能同时为空")
        if len(p.attachments) + len(p.attachment_refs) > 4:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "一次最多发送 4 个附件")
        if len(p.attachment_refs) != len(set(p.attachment_refs)):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "附件引用不能重复")
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        user_id = p.user_id or "ws-user"
        attachments_fingerprint = (
            attachment_fingerprint(p.attachments)
            + ":" + ",".join(p.attachment_refs)
            + f":retry={p.retry_of_message_id or ''}"
        )
        receipt_key = (session_id, p.client_request_id)
        with self._chat_receipts_lock:
            receipt = self._chat_receipts.get(receipt_key)
            if receipt is not None:
                original_content, original_user_id, original_fingerprint, original_response = receipt
                if (
                    original_content != content
                    or original_user_id != user_id
                    or original_fingerprint != attachments_fingerprint
                ):
                    return build_error(
                        req_id,
                        ErrorCode.INVALID_PARAMS,
                        "client_request_id 已被同一会话中的其他消息使用",
                    )
                self._chat_receipts.move_to_end(receipt_key)
                return build_response(req_id, result={**original_response, "duplicate": True})

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")

        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        if p.retry_of_message_id is not None:
            source = db.get_user_message(p.retry_of_message_id, session_id) if db else None
            if source is None or source.get("content", "").strip() != content:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试消息不属于该会话或内容不一致")
            try:
                source_metadata = json.loads(source.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                source_metadata = {}
            if not isinstance(source_metadata, dict) or source_metadata.get("status") not in {
                "failed", "interrupted",
            }:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "只有失败或已中断的消息可以重试")
            source_attachment_ids = [
                item.get("id") for item in source_metadata.get("attachments", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            if source_attachment_ids != p.attachment_refs:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试必须使用原消息的附件")

        saved_paths = []
        try:
            prepared_attachments, image_paths, saved_paths = prepare_attachments(
                getattr(living, "_agent_id", "default"), session_id, p.attachments,
            )
            referenced = []
            for attachment_id in p.attachment_refs:
                metadata = db.get_attachment_metadata(session_id, attachment_id) if db else None
                if metadata is None:
                    raise AttachmentError("引用附件不属于该会话或不存在")
                referenced.append(metadata)
            restored, restored_images = restore_attachment_refs(
                getattr(living, "_agent_id", "default"), session_id, referenced,
            )
            combined = [*prepared_attachments, *restored]
            combined_ids = [str(item.get("id", "")) for item in combined]
            if len(combined_ids) != len(set(combined_ids)):
                raise AttachmentError("附件标识不能重复")
            if sum(int(item.get("size", 0)) for item in combined) > 8 * 1024 * 1024:
                raise AttachmentError("单条消息的附件合计不能超过 8 MB")
            prepared_attachments.extend(restored)
            image_paths.extend(restored_images)
        except AttachmentError as exc:
            cleanup_attachments(saved_paths)
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        except OSError as exc:
            cleanup_attachments(saved_paths)
            logger.exception("Failed to persist chat attachments")
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, f"保存附件失败: {exc}")

        gw = getattr(living, '_gateway_inbound', None)
        if gw:
            from .inbound import RawMessage, Accepted
            result = gw.accept(RawMessage(
                content=content, source="human", channel="ws",
                peer_id=user_id, peer_type="human",
                session_id=session_id,
                images=image_paths,
                attachments=prepared_attachments,
                metadata={"retry_of": p.retry_of_message_id} if p.retry_of_message_id else {},
            ))
            accepted = isinstance(result, Accepted)
            response = {"accepted": accepted, "session_id": session_id}
            if accepted:
                response["turn_id"] = result.living_message.turn_id
                response["message_id"] = result.living_message.message_id
            else:
                response["reason"] = getattr(result, "reason", "REJECTED")
            if accepted:
                self._remember_chat_receipt(
                    receipt_key, content, user_id, attachments_fingerprint, response,
                )
            else:
                cleanup_attachments(saved_paths)
            return build_response(req_id, result=response)
        else:
            # Fallback: Gateway not yet initialized
            msg = living.put_message(
                content, session_id=session_id, user_id=user_id,
                images=image_paths, attachments=prepared_attachments,
            )
            response = {
                "accepted": True,
                "session_id": session_id,
                "turn_id": msg.turn_id,
                "message_id": getattr(msg, "message_id", None),
            }
            self._remember_chat_receipt(
                receipt_key, content, user_id, attachments_fingerprint, response,
            )
            return build_response(req_id, result=response)

    def _handle_chat_retry(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatRetryParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")
        living = self._living
        db = getattr(getattr(living, "agent", None), "conversation_db", None) if living else None
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")
        source = db.get_user_message(p.message_id, p.session_id)
        if source is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试消息不属于该会话或不存在")
        try:
            metadata = json.loads(source.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        status = metadata.get("status") if isinstance(metadata, dict) else None
        if status not in {"failed", "interrupted"}:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "只有失败或已中断的消息可以重试")
        attachment_refs = [
            item.get("id") for item in metadata.get("attachments", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ] if isinstance(metadata, dict) else []
        return self._handle_chat_send(conn_id, req_id, {
            "content": source.get("content", ""),
            "client_request_id": p.client_request_id,
            "session_id": p.session_id,
            "user_id": source.get("user_id", "ws-user"),
            "attachment_refs": attachment_refs,
            "retry_of_message_id": p.message_id,
        })

    def _remember_chat_receipt(
        self,
        key: tuple[str, str],
        content: str,
        user_id: str,
        attachments_fingerprint: str,
        response: dict[str, Any],
    ) -> None:
        with self._chat_receipts_lock:
            self._chat_receipts[key] = (
                content, user_id, attachments_fingerprint, dict(response),
            )
            self._chat_receipts.move_to_end(key)
            while len(self._chat_receipts) > 2048:
                self._chat_receipts.popitem(last=False)

    def _handle_chat_abort(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            ChatAbortParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        try:
            # A clarification tool may currently be waiting rather than asking
            # the LLM for more tokens.  Wake only this connection's session so
            # abort never leaves the Agent blocked on an invisible question.
            from .connection import cm
            session_id = cm.get_session_id(conn_id)
            broker = getattr(living, "_interaction_broker", None)
            if broker is not None and session_id:
                broker.cancel_session(session_id)
            action_broker = getattr(living, "_action_broker", None)
            if action_broker is not None and session_id:
                action_broker.cancel_session(session_id)
            living.abort_chat()
            return build_response(req_id, result={"aborted": True})
        except Exception as e:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(e))

    def _handle_chat_history(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatHistoryParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")

        try:
            db = getattr(getattr(living, 'agent', None), 'conversation_db', None)
            if db is None:
                return build_response(req_id, result={
                    "messages": [], "has_more": False, "next_before_id": None,
                })

            session_id = p.session_id or None
            rows, has_more = db.get_history_page(
                limit=p.limit,
                session_id=session_id,
                before_id=p.before_id,
            )
            list_artifacts = getattr(db, "list_artifacts", None)
            get_cursor_time = getattr(db, "get_message_created_at", None)
            cursor_time = (
                get_cursor_time(p.before_id, session_id)
                if p.before_id is not None and callable(get_cursor_time)
                else None
            )
            artifact_rows = list_artifacts(
                session_id,
                since=float(rows[0].get("created_at", 0)) if rows else None,
                until=(
                    cursor_time if cursor_time is not None
                    else float(rows[-1].get("created_at", 0)) if rows and p.before_id is not None
                    else None
                ),
            ) if callable(list_artifacts) and (rows or p.before_id is None) else []
            timeline_rows = [*rows, *(
                {
                    "id": f"artifact:{artifact.get('id', '')}",
                    "role": "artifact",
                    "content": artifact.get("name", ""),
                    "created_at": artifact.get("created_at", 0),
                    "user_id": artifact.get("user_id", ""),
                    "artifact": artifact,
                }
                for artifact in artifact_rows
            )]
            timeline_rows.sort(key=lambda row: (float(row.get("created_at", 0)), str(row.get("id", ""))))
            messages = []
            for r in timeline_rows:
                message = {
                    "id": r.get("id"),
                    "role": r.get("role", "user"),
                    "content": r.get("content", ""),
                    "created_at": r.get("created_at", 0),
                    "user_id": r.get("user_id", ""),
                }
                if r.get("role") == "user":
                    try:
                        user_metadata = json.loads(r.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        user_metadata = {}
                    if isinstance(user_metadata, dict) and isinstance(user_metadata.get("attachments"), list):
                        message["attachments"] = user_metadata["attachments"]
                    if isinstance(user_metadata, dict):
                        for key in ("turn_id", "status", "error", "retry_of"):
                            if key in user_metadata:
                                message[key] = user_metadata[key]
                if r.get("role") == "interaction":
                    try:
                        interaction = json.loads(r.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        interaction = {}
                    if not isinstance(interaction, dict) or not interaction.get("id"):
                        continue
                    if interaction.get("kind") == "tool_approval":
                        message["action"] = interaction
                    else:
                        message["interaction"] = interaction
                elif r.get("role") == "tool":
                    message["tool_call_id"] = r.get("tool_call_id", "")
                    message["tool_name"] = r.get("tool_name", "")
                elif r.get("role") == "artifact":
                    artifact = dict(r.get("artifact") or {})
                    if not isinstance(artifact, dict) or not artifact.get("id"):
                        continue
                    artifact.pop("relative_path", None)
                    artifact.pop("storage_suffix", None)
                    artifact.pop("user_id", None)
                    artifact.pop("session_id", None)
                    artifact.pop("created_at", None)
                    message["artifact"] = artifact
                messages.append(message)
            return build_response(req_id, result={
                "messages": messages,
                "has_more": has_more,
                "next_before_id": rows[0].get("id") if has_more and rows else None,
            })
        except Exception as e:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(e))

    def _handle_attachment_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = AttachmentGetParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")

        attachment = db.get_attachment_metadata(p.session_id, p.attachment_id)
        if attachment is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "附件不属于该会话或不存在")
        try:
            result = read_stored_attachment(
                getattr(living, "_agent_id", "default"),
                p.session_id,
                attachment,
            )
        except AttachmentError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={"attachment": result})

    def _handle_chat_sessions(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSessionsParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")

        try:
            db = getattr(getattr(living, "agent", None), "conversation_db", None)
            if db is None:
                return build_response(req_id, result={
                    "sessions": [], "has_more": False, "next_offset": None,
                })
            rows = db.list_sessions(
                limit=p.limit + 1,
                offset=p.offset,
                query=p.query,
            )
            has_more = len(rows) > p.limit
            sessions = rows[:p.limit]
            return build_response(
                req_id,
                result={
                    "sessions": sessions,
                    "has_more": has_more,
                    "next_offset": p.offset + len(sessions) if has_more else None,
                },
            )
        except Exception as e:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(e))

    def _handle_session_resume(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = SessionResumeParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        from .connection import cm
        connection_session_id = cm.get_session_id(conn_id)
        if not connection_session_id or connection_session_id != p.session_id:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "只能恢复当前连接绑定的会话")

        history_response = self._handle_chat_history(conn_id, req_id, {
            "session_id": p.session_id,
            "limit": p.history_limit,
        })
        if history_response.get("error"):
            return history_response

        registry = getattr(self._living, "_turn_registry", None)
        inflight = registry.snapshot(p.session_id) if registry is not None else None
        result = dict(history_response.get("result", {}))
        result.update({
            "session_id": p.session_id,
            "state": inflight.get("status", "idle") if inflight else "idle",
            "inflight": inflight,
        })
        return build_response(req_id, result=result)

    def _handle_identity_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        """返回 agent 配置的可登录身份列表（来自 contacts/identities.yaml）。"""
        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")

        agent_core = living.agent._get_agent() if hasattr(living, 'agent') else None
        mgr = getattr(agent_core, 'identity_mgr', None)

        identities = []
        if mgr:
            for id_ in mgr.list_ids():
                identities.append({
                    "id": id_,
                    "name": mgr.get_display_name(id_),
                    "relation": mgr.get_relation(id_),
                })

        return build_response(req_id, result={"identities": identities})

    def _handle_interaction_respond(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = InteractionRespondParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        broker = getattr(living, "_interaction_broker", None) if living is not None else None
        if broker is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "交互服务未就绪")

        from .connection import cm
        session_id = cm.get_session_id(conn_id)
        if not session_id:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接没有会话")
        if not broker.respond(p.request_id, p.response, session_id, p.turn_id):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "交互请求不存在、已结束或不属于当前会话轮次")
        return build_response(req_id, result={
            "accepted": True,
            "request_id": p.request_id,
            "turn_id": p.turn_id,
        })

    def _handle_action_respond(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ActionRespondParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        living = self._living
        broker = getattr(living, "_action_broker", None) if living is not None else None
        if broker is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "操作审批服务未就绪")

        from .connection import cm
        session_id = cm.get_session_id(conn_id)
        if not session_id:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接没有会话")
        if not broker.respond(p.action_id, p.decision, session_id, p.turn_id):
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                "操作请求不存在、已结束或不属于当前会话轮次",
            )
        return build_response(req_id, result={
            "accepted": True,
            "action_id": p.action_id,
            "turn_id": p.turn_id,
            "decision": p.decision,
        })

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._auth_sessions.discard(conn_id)
