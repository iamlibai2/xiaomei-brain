"""RPC handlers for Agent-owned output artifacts."""

from __future__ import annotations

from typing import Any

from .artifacts import ArtifactError, read_stored_artifact
from .protocol import ErrorCode, build_error, build_response
from .schemas import ArtifactGetParams, format_error


class ArtifactMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {"artifact.get": self.handle_get}

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ArtifactGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        living = self._living
        db = getattr(getattr(living, "agent", None), "conversation_db", None) if living else None
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")
        artifact = db.get_artifact_metadata(parsed.session_id, parsed.artifact_id)
        if artifact is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "产物不属于该会话或不存在")
        try:
            value = read_stored_artifact(
                getattr(living, "_agent_id", "default"), parsed.session_id, artifact,
            )
        except ArtifactError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={"artifact": value})
