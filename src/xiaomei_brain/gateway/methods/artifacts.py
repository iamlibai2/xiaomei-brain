"""Gateway methods for Person-visible Agent output artifacts."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from ..artifacts import ArtifactError, read_stored_artifact
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ArtifactGetParams, ArtifactListParams, format_error


class ArtifactMethods:
    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "artifact.get": self.handle_get,
            "artifact.list": self.handle_list,
        }

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ArtifactGetParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                f"Invalid parameters: {format_error(exc)}",
            )
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        db, error = self._db(req_id)
        if error:
            return error
        artifact = db.get_artifact_metadata(
            parsed.session_id,
            parsed.artifact_id,
        )
        if artifact is None or str(artifact.get("user_id") or "") not in {
            person_id,
            "global",
        }:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                "Artifact does not exist or is not visible",
            )
        try:
            value = read_stored_artifact(
                getattr(self._living, "_agent_id", "default"),
                parsed.session_id,
                artifact,
            )
        except ArtifactError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={"artifact": value})

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ArtifactListParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        db, error = self._db(req_id)
        if error:
            return error
        rows = db.list_artifacts_for_person(
            person_id,
            limit=parsed.limit + 1,
            offset=parsed.offset,
        )
        has_more = len(rows) > parsed.limit
        public = []
        for row in rows[:parsed.limit]:
            item = {
                key: value
                for key, value in row.items()
                if key not in {"relative_path", "storage_suffix", "user_id"}
            }
            display_path = self._display_path(row.get("relative_path"))
            if display_path:
                item["display_path"] = display_path
            public.append(item)
        return build_response(req_id, result={
            "artifacts": public,
            "has_more": has_more,
        })

    @staticmethod
    def _display_path(value: Any) -> str:
        """Expose only a relative Agent-owned path, never a host filesystem path."""
        normalized = str(value or "").replace("\\", "/").strip("/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] not in {
                "workspace", "images", "music", "tts", "videos", "projects",
            }
        ):
            return ""
        return path.as_posix()

    def _person_id(
        self,
        conn_id: str,
        req_id: str,
    ) -> tuple[str | None, dict | None]:
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return None, build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        return str(context.person_id), None

    def _db(self, req_id: str):
        db = getattr(
            getattr(self._living, "agent", None),
            "conversation_db",
            None,
        )
        if db is None:
            return None, build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Conversation storage is not ready",
            )
        return db, None
