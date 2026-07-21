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
    ChatAbortParams,
    ChatHistoryParams,
    ChatSessionsParams,
    SessionResumeParams,
    InteractionRespondParams,
    format_error,
)
from .auth import check_token

logger = logging.getLogger(__name__)


class MethodRouter:
    """将 RPC method 名路由到处理函数。"""

    def __init__(self, living: Any = None, config: Any = None) -> None:
        self._living = living
        self._config = config
        self._handlers: dict[str, callable] = {
            "connect": self._handle_connect,
            "chat.send": self._handle_chat_send,
            "chat.abort": self._handle_chat_abort,
            "chat.history": self._handle_chat_history,
            "chat.sessions": self._handle_chat_sessions,
            "session.resume": self._handle_session_resume,
            "interaction.respond": self._handle_interaction_respond,
            "identity.list": self._handle_identity_list,
        }
        # 已认证的 session
        self._auth_sessions: set[str] = set()
        self._chat_receipts_lock = threading.Lock()
        self._chat_receipts: OrderedDict[
            tuple[str, str], tuple[str, str, dict[str, Any]]
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
            ],
        })

    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSendParams.model_validate(params)
        except Exception as e:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(e)}")

        content = p.content.strip()
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        user_id = p.user_id or "ws-user"
        receipt_key = (session_id, p.client_request_id)
        with self._chat_receipts_lock:
            receipt = self._chat_receipts.get(receipt_key)
            if receipt is not None:
                original_content, original_user_id, original_response = receipt
                if original_content != content or original_user_id != user_id:
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

        gw = getattr(living, '_gateway_inbound', None)
        if gw:
            from .inbound import RawMessage, Accepted
            result = gw.accept(RawMessage(
                content=content, source="human", channel="ws",
                peer_id=user_id, peer_type="human",
                session_id=session_id,
            ))
            accepted = isinstance(result, Accepted)
            response = {"accepted": accepted, "session_id": session_id}
            if accepted:
                response["turn_id"] = result.living_message.turn_id
            else:
                response["reason"] = getattr(result, "reason", "REJECTED")
            if accepted:
                self._remember_chat_receipt(receipt_key, content, user_id, response)
            return build_response(req_id, result=response)
        else:
            # Fallback: Gateway not yet initialized
            msg = living.put_message(content, session_id=session_id, user_id=user_id)
            response = {
                "accepted": True,
                "session_id": session_id,
                "turn_id": msg.turn_id,
            }
            self._remember_chat_receipt(receipt_key, content, user_id, response)
            return build_response(req_id, result=response)

    def _remember_chat_receipt(
        self,
        key: tuple[str, str],
        content: str,
        user_id: str,
        response: dict[str, Any],
    ) -> None:
        with self._chat_receipts_lock:
            self._chat_receipts[key] = (content, user_id, dict(response))
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
            messages = []
            for r in rows:
                message = {
                    "id": r.get("id"),
                    "role": r.get("role", "user"),
                    "content": r.get("content", ""),
                    "created_at": r.get("created_at", 0),
                    "user_id": r.get("user_id", ""),
                }
                if r.get("role") == "interaction":
                    try:
                        interaction = json.loads(r.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        interaction = {}
                    if not isinstance(interaction, dict) or not interaction.get("id"):
                        continue
                    message["interaction"] = interaction
                elif r.get("role") == "tool":
                    message["tool_call_id"] = r.get("tool_call_id", "")
                    message["tool_name"] = r.get("tool_name", "")
                messages.append(message)
            return build_response(req_id, result={
                "messages": messages,
                "has_more": has_more,
                "next_before_id": rows[0].get("id") if has_more and rows else None,
            })
        except Exception as e:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(e))

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

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._auth_sessions.discard(conn_id)
