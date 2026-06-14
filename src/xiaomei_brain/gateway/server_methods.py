"""Gateway RPC 方法处理 — req → handler → res/event。"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import build_res, build_event, error_shape, ErrorCodes
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
        token = params.get("token", "")
        client = params.get("client", "unknown")

        if not check_token(token, self._config):
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.UNAUTHORIZED, "Token 无效"))

        self._auth_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已认证: conn=%s client=%s", conn_id[:8], client)

        session_id = f"ws-{conn_id[:8]}"
        return build_res(req_id, ok=True, payload={
            "session_id": session_id,
            "protocol_version": 1,
        })

    def _handle_chat_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        content = params.get("content", "").strip()
        if not content:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.EMPTY_MESSAGE, "空消息"))

        session_id = params.get("session_id") or f"ws-{conn_id[:8]}"
        user_id = params.get("user_id", "") or "ws-user"

        living = self._living
        if living is None:
            return build_res(req_id, ok=False,
                             error=error_shape(ErrorCodes.GATEWAY_NOT_READY, "Gateway 未就绪"))

        living.put_message(content, session_id=session_id, user_id=user_id)
        return build_res(req_id, ok=True, payload={"accepted": True, "session_id": session_id})

    def _handle_chat_abort(self, conn_id: str, req_id: str, params: dict) -> dict:
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

    def drop_session(self, conn_id: str) -> None:
        """断开连接时清除认证状态。"""
        self._auth_sessions.discard(conn_id)
