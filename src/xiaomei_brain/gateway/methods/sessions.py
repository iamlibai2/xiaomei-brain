"""Gateway session listing and reconnect methods."""

from __future__ import annotations

from typing import Any, Callable

from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ChatSessionsParams,
    SessionResumeParams,
    SessionDeleteParams,
    SessionSwitchParams,
    format_error,
)


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
            "session.subscribe": self.handle_subscribe,
            "session.unsubscribe": self.handle_unsubscribe,
            "session.switch": self.handle_switch,
            "session.delete": self.handle_delete,
        }

    def _owned_session(self, conn_id: str, session_id: str):
        person_id = cm.get_person_id(conn_id)
        people_service = getattr(self._living, "_people_service", None)
        if not person_id or people_service is None:
            return None
        target = people_service.store.get_session(session_id)
        if (
            target is None
            or target.scope_type != "person"
            or target.scope_id != person_id
        ):
            return None
        return target

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
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
            person_id = cm.get_person_id(conn_id)
            people_service = getattr(living, "_people_service", None)
            if not person_id or people_service is None:
                return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
            rows = db.list_sessions(
                limit=parsed.limit + 1,
                offset=parsed.offset,
                query=parsed.query,
                scope_type="person",
                scope_id=person_id,
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
        if (
            not connection_session_id
            or (
                connection_session_id != parsed.session_id
                and not cm.is_subscribed(conn_id, parsed.session_id)
            )
        ):
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

    def handle_subscribe(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = SessionSwitchParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        if self._owned_session(conn_id, parsed.session_id) is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "目标会话不属于当前人物")
        cm.subscribe_session(parsed.session_id, conn_id)
        return build_response(req_id, result={
            "session_id": parsed.session_id,
            "subscribed": True,
        })

    def handle_unsubscribe(self, conn_id: str, req_id: str, params: dict) -> dict:
        """Release an inactive Desktop conversation subscription.

        A running or waiting Turn remains subscribed until it reaches a safe
        terminal state, so enforcing the cache limit can never drop its reply.
        """
        try:
            parsed = SessionSwitchParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        if cm.get_session_id(conn_id) == parsed.session_id:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能取消当前会话订阅")
        if not cm.is_subscribed(conn_id, parsed.session_id):
            return build_response(req_id, result={
                "session_id": parsed.session_id,
                "subscribed": False,
            })
        registry = getattr(self._living, "_turn_registry", None)
        inflight = registry.snapshot(parsed.session_id) if registry is not None else None
        if inflight and inflight.get("status") in {"queued", "running", "waiting_user"}:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "会话仍在工作，暂不取消订阅")
        cm.unsubscribe_session(parsed.session_id, conn_id)
        return build_response(req_id, result={
            "session_id": parsed.session_id,
            "subscribed": False,
        })

    def handle_switch(self, conn_id: str, req_id: str, params: dict) -> dict:
        """Move an authenticated connection to another session owned by its Person."""
        try:
            parsed = SessionSwitchParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        person_id = cm.get_person_id(conn_id)
        current_session_id = cm.get_session_id(conn_id)
        if not person_id or not current_session_id:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")

        if self._owned_session(conn_id, parsed.session_id) is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "目标会话不属于当前人物")

        if parsed.session_id != current_session_id:
            cm.set_session(parsed.session_id, conn_id, person_id)
        history_response = self._history_handler(conn_id, req_id, {
            "session_id": parsed.session_id,
            "limit": parsed.history_limit,
        })
        if history_response.get("error"):
            if parsed.session_id != current_session_id:
                cm.set_session(current_session_id, conn_id, person_id)
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

    def handle_delete(self, conn_id: str, req_id: str, params: dict) -> dict:
        """Remove a Person-owned conversation from active conversation views."""
        try:
            parsed = SessionDeleteParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"参数无效: {format_error(exc)}",
            )
        person_id = cm.get_person_id(conn_id)
        if not person_id:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有人物身份")
        if cm.get_session_id(conn_id) == parsed.session_id:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "请先切换到其他会话")
        if self._owned_session(conn_id, parsed.session_id) is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "目标会话不属于当前人物")

        registry = getattr(self._living, "_turn_registry", None)
        inflight = registry.snapshot(parsed.session_id) if registry is not None else None
        if inflight and inflight.get("status") in {"queued", "running", "waiting_user"}:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "会话仍在工作，暂时不能删除")

        people_service = getattr(self._living, "_people_service", None)
        if people_service is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "人物服务尚未就绪")
        deleted = people_service.store.delete_session(
            parsed.session_id,
            "person",
            person_id,
        )
        if not deleted:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "会话不存在或已经删除")
        cm.unsubscribe_session(parsed.session_id, conn_id)
        return build_response(req_id, result={
            "session_id": parsed.session_id,
            "deleted": True,
        })
