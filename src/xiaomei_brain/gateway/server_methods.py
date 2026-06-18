"""Gateway RPC 方法处理 — req → handler → res/event。"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import build_res, build_event, error_shape, ErrorCodes
from .schemas import ConnectParams, ChatSendParams, ChatAbortParams, ChatHistoryParams, format_error
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
            "identity.list": self._handle_identity_list,
        }
        # 已认证的 session
        self._auth_sessions: set[str] = set()

    def dispatch(self, conn_id: str, req_id: str, method: str, params: dict) -> dict:
        """分发 RPC 请求到对应 handler。

        Returns:
            res 帧 dict。
        """
        # 非 connect 方法需要先认证
        if method != "connect" and conn_id not in self._auth_sessions:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.UNAUTHORIZED, "请先 connect"))

        handler = self._handlers.get(method)
        if handler is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.METHOD_NOT_FOUND,
                                               f"未知方法: {method}"))

        try:
            return handler(conn_id, req_id, params)
        except Exception as e:
            logger.error("[MethodRouter] %s 处理失败: %s", method, e)
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INTERNAL_ERROR, str(e)))

    # ── Handlers ──────────────────────────────

    def _handle_connect(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ConnectParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        if not check_token(p.token, self._config):
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.UNAUTHORIZED, "Token 无效"))

        self._auth_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已认证: conn=%s client=%s", conn_id[:8], p.client)

        # 重连：客户端带了之前的 session_id → 复用
        session_id = p.session_id or f"ws-{conn_id[:8]}"

        # 设置 user_id 并加载 fresh_tail（WS 连接也需要"带着记忆醒来"）
        if p.user_id and self._living:
            self._living.user_id = p.user_id
            agent_core = self._living.agent._get_agent()
            if agent_core:
                agent_core.user_id = p.user_id
            self._living.load_fresh_tail()
            # 保存 attention 会话，防止后续 switch_to 覆盖 fresh_tail
            if hasattr(self._living, '_attention') and self._living._attention:
                ws_sid = f"ws-{session_id}"
                self._living._attention.save_session(ws_sid)
                self._living._attention._current_session = ws_sid
            logger.info("[Gateway] fresh_tail 已加载: user_id=%s session=%s", p.user_id, session_id)

        return build_res(req_id, ok=True, payload={
            "session_id": session_id,
            "agent_name": getattr(self._living, "_agent_id", ""),
            "reconnect": bool(p.session_id),
            "protocol_version": 1,
        })

    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatSendParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        content = p.content.strip()
        session_id = p.session_id or f"ws-{conn_id[:8]}"
        user_id = p.user_id or "ws-user"

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        gw = getattr(living, '_gateway_inbound', None)
        if gw:
            from .inbound import RawMessage, Accepted
            result = gw.accept(RawMessage(
                content=content, source="human", channel="ws",
                peer_id=user_id, peer_type="human",
                session_id=session_id,
            ))
            accepted = isinstance(result, Accepted)
            return build_res(req_id, ok=accepted, payload={"accepted": accepted, "session_id": session_id})
        else:
            # Fallback: Gateway not yet initialized
            living.put_message(content, session_id=session_id, user_id=user_id)
            return build_res(req_id, ok=True, payload={"accepted": True, "session_id": session_id})

    def _handle_chat_abort(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            ChatAbortParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))
        try:
            living.abort_chat()
            return build_res(req_id, ok=True, payload={"aborted": True})
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INTERNAL_ERROR, str(e)))

    def _handle_chat_history(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            p = ChatHistoryParams.model_validate(params)
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INVALID_REQUEST, f"参数无效: {format_error(e)}"))

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        try:
            db = getattr(getattr(living, 'agent', None), 'conversation_db', None)
            if db is None:
                return build_res(req_id, ok=True, payload={"messages": []})

            session_id = p.session_id or None
            rows = db.get_recent(n=min(p.limit, 200), session_id=session_id)
            messages = [
                {
                    "role": r.get("role", "user"),
                    "content": r.get("content", ""),
                    "created_at": r.get("created_at", 0),
                    "user_id": r.get("user_id", ""),
                }
                for r in rows
            ]
            return build_res(req_id, ok=True, payload={"messages": messages})
        except Exception as e:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.INTERNAL_ERROR, str(e)))

    def _handle_identity_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        """返回 agent 配置的可登录身份列表（来自 contacts/identities.yaml）。"""
        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

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

        return build_res(req_id, ok=True, payload={"identities": identities})

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._auth_sessions.discard(conn_id)
