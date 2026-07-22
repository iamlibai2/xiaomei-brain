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
        auth_sessions: set[str],
        capability_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        self._living = living
        self._config = config
        self._auth_sessions = auth_sessions
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

        self._auth_sessions.add(conn_id)
        logger.info("[Gateway] 客户端已认证: conn=%s client=%s", conn_id[:8], parsed.client)
        session_id = parsed.session_id or f"ws-{conn_id[:8]}"
        turn_registry = getattr(self._living, "_turn_registry", None) if self._living else None
        active_turn = turn_registry.snapshot(session_id) if turn_registry is not None else None

        if parsed.user_id and self._living:
            self._living.user_id = parsed.user_id
            agent_core = self._living.agent._get_agent()
            if agent_core:
                agent_core.user_id = parsed.user_id
            if active_turn is None:
                self._living.load_fresh_tail()
                if hasattr(self._living, "_attention") and self._living._attention:
                    ws_sid = f"ws-{session_id}"
                    self._living._attention.save_session(ws_sid)
                    self._living._attention._current_session = ws_sid
                logger.info(
                    "[Gateway] fresh_tail 已加载: user_id=%s session=%s",
                    parsed.user_id,
                    session_id,
                )
            else:
                logger.info(
                    "[Gateway] 活动 Turn 重连，保持现有上下文: session=%s turn=%s",
                    session_id,
                    active_turn.get("turn_id", ""),
                )

        return build_response(req_id, result={
            "session_id": session_id,
            "agent_name": getattr(self._living, "_agent_id", ""),
            "reconnect": bool(parsed.session_id),
            "protocol_version": 3,
            "capabilities": self._capability_provider(),
        })
