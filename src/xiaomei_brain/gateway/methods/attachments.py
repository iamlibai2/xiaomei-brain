"""Gateway methods for Agent-owned conversation attachments."""

from __future__ import annotations

from typing import Any

from ..attachments import AttachmentError, read_stored_attachment
from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import AttachmentGetParams, format_error


class AttachmentMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {"attachment.get": self.handle_get}

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = AttachmentGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        session_id = cm.resolve_session(conn_id, parsed.session_id)
        if session_id is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能读取当前连接之外的会话附件")

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")
        attachment = db.get_attachment_metadata(session_id, parsed.attachment_id)
        if attachment is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "附件不属于该会话或不存在")
        try:
            result = read_stored_attachment(
                getattr(living, "_agent_id", "default"),
                session_id,
                attachment,
            )
        except AttachmentError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={"attachment": result})
