"""Gateway connection and capability negotiation methods."""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..auth import check_token
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ConnectParams, format_error

logger = logging.getLogger(__name__)


class ConnectionMethods:
    def __init__(
        self,
        living: Any,
        config: Any,
        connected_sessions: set[str],
        capability_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        self._living = living
        self._config = config
        self._connected_sessions = connected_sessions
        self._capability_provider = capability_provider or (lambda: [])

    @property
    def handlers(self) -> dict[str, Any]:
        return {"connect": self.handle_connect}

    def handle_connect(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ConnectParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")

        if not check_token(parsed.token, self._config):
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "Token 无效")
        if conn_id in self._connected_sessions:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接已经 connect")

        # Token 只证明客户端可以连接 Gateway，不代表任何自然人身份。
        self._connected_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已连接: conn=%s client=%s", conn_id[:8], parsed.client)
        session_id = parsed.session_id or f"ws-{conn_id[:8]}"

        return build_response(req_id, result={
            "session_id": session_id,
            "agent_name": getattr(self._living, "_agent_id", ""),
            "reconnect": bool(parsed.session_id),
            "protocol_version": 3,
            "capabilities": self._capability_provider(),
            "identity_status": "required",
        })
