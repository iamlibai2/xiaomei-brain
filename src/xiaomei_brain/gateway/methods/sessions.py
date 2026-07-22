"""Gateway session listing and reconnect methods."""

from __future__ import annotations

from typing import Any, Callable

from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ChatSessionsParams, SessionResumeParams, format_error


HistoryHandler = Callable[[str, str, dict], dict]


class SessionMethods:
    def __init__(self, living: Any, history_handler: HistoryHandler) -> None:
        self._living = living
        self._history_handler = history_handler

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "chat.sessions": self.handle_list,
            "session.resume": self.handle_resume,
        }

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ChatSessionsParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
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
                limit=parsed.limit + 1,
                offset=parsed.offset,
                query=parsed.query,
            )
            has_more = len(rows) > parsed.limit
            sessions = rows[:parsed.limit]
            return build_response(req_id, result={
                "sessions": sessions,
                "has_more": has_more,
                "next_offset": parsed.offset + len(sessions) if has_more else None,
            })
        except Exception as exc:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(exc))

    def handle_resume(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = SessionResumeParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        connection_session_id = cm.get_session_id(conn_id)
        if not connection_session_id or connection_session_id != parsed.session_id:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "只能恢复当前连接绑定的会话")
        history_response = self._history_handler(conn_id, req_id, {
            "session_id": parsed.session_id,
            "limit": parsed.history_limit,
        })
        if history_response.get("error"):
            return history_response
        registry = getattr(self._living, "_turn_registry", None)
        inflight = registry.snapshot(parsed.session_id) if registry is not None else None
        result = dict(history_response.get("result", {}))
        result.update({
            "session_id": parsed.session_id,
            "state": inflight.get("status", "idle") if inflight else "idle",
            "inflight": inflight,
        })
        return build_response(req_id, result=result)

