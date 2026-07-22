"""Gateway response methods for Clarify and Action requests."""

from __future__ import annotations

from typing import Any

from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ActionRespondParams, InteractionRespondParams, format_error


class InteractionMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "interaction.respond": self.handle_interaction_respond,
            "action.respond": self.handle_action_respond,
        }

    def handle_interaction_respond(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = InteractionRespondParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        broker = getattr(self._living, "_interaction_broker", None) if self._living else None
        if broker is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "交互服务未就绪")
        session_id = cm.get_session_id(conn_id)
        if not session_id:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接没有会话")
        user_id = cm.get_user_id(conn_id)
        if not broker.respond(
            parsed.request_id,
            parsed.response,
            session_id,
            parsed.turn_id,
            user_id,
        ):
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                "交互请求不存在、已结束或不属于当前会话轮次",
            )
        return build_response(req_id, result={
            "accepted": True,
            "request_id": parsed.request_id,
            "turn_id": parsed.turn_id,
        })

    def handle_action_respond(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ActionRespondParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        broker = getattr(self._living, "_action_broker", None) if self._living else None
        if broker is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "操作审批服务未就绪")
        session_id = cm.get_session_id(conn_id)
        if not session_id:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, "当前连接没有会话")
        user_id = cm.get_user_id(conn_id)
        if not broker.respond(
            parsed.action_id,
            parsed.decision,
            session_id,
            parsed.turn_id,
            user_id,
        ):
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                "操作请求不存在、已结束或不属于当前会话轮次",
            )
        return build_response(req_id, result={
            "accepted": True,
            "action_id": parsed.action_id,
            "turn_id": parsed.turn_id,
            "decision": parsed.decision,
        })
