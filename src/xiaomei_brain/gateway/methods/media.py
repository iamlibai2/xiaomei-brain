"""Gateway RPC methods for per-Agent media service configuration."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.media import (
    MediaServiceConfigurationError,
    MediaServiceConfigurationService,
    inspect_media_runtime,
)

from ..artifacts import ArtifactError, stored_artifact_path
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    MediaLibraryListParams,
    MediaServiceConfigureParams,
    MediaServiceListParams,
    MediaServiceParams,
    MediaServiceTestParams,
    MediaTrackAuthorizeParams,
    format_error,
)


class MediaServiceMethods:
    def __init__(
        self,
        living: Any,
        identity_contexts: dict[str, Any] | None = None,
    ) -> None:
        self._living = living
        self._identity_contexts = identity_contexts if identity_contexts is not None else {}

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "media.service.list": self.handle_list,
            "media.service.get": self.handle_get,
            "media.service.configure": self.handle_configure,
            "media.service.test": self.handle_test,
            "media.service.remove": self.handle_remove,
            "media.runtime.status": self.handle_runtime_status,
            "media.library.list": self.handle_library_list,
            "media.track.authorize": self.handle_track_authorize,
        }

    def handle_library_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaLibraryListParams, params, req_id)
        if error:
            return error
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        db, error = self._conversation_db(req_id)
        if error:
            return error
        rows = db.list_audio_artifacts_for_person(
            person_id,
            limit=parsed.limit + 1,
            offset=parsed.offset,
        )
        tracks = [self._public_track(artifact) for artifact in rows[:parsed.limit]]
        has_more = len(rows) > parsed.limit
        return build_response(req_id, result={
            "tracks": tracks,
            "has_more": has_more,
            "next_offset": parsed.offset + parsed.limit if has_more else None,
        })

    def handle_track_authorize(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaTrackAuthorizeParams, params, req_id)
        if error:
            return error
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        db, error = self._conversation_db(req_id)
        if error:
            return error
        artifact = db.get_artifact_metadata(parsed.session_id, parsed.source_id)
        if artifact is None or str(artifact.get("user_id") or "") not in {person_id, "global"}:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                "Media track does not exist or is not visible",
            )
        mime_type = str(artifact.get("mime_type") or "")
        if not mime_type.startswith("audio/"):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "Media track is not audio")
        try:
            from ..media_access import media_access_registry

            grant = media_access_registry.issue(
                stored_artifact_path(
                    getattr(self._living, "_agent_id", "default"),
                    parsed.session_id,
                    artifact,
                ),
                session_id=parsed.session_id,
                person_id=str(person_id),
                mime_type=mime_type,
            )
        except (ArtifactError, ValueError) as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            **self._public_track(artifact),
            "playback_id": f"artifact-{parsed.source_id}",
            "person_id": str(person_id),
            "media_path": f"/media/{grant.token}",
            "expires_at": round(grant.expires_at),
        })

    @staticmethod
    def _public_track(artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_type": "artifact",
            "source_id": str(artifact.get("id") or ""),
            "session_id": str(artifact.get("session_id") or ""),
            "title": str(artifact.get("name") or ""),
            "mime_type": str(artifact.get("mime_type") or ""),
            "size": max(0, int(artifact.get("size") or 0)),
            "updated_at": float(artifact.get("updated_at") or 0),
        }

    def _person_id(self, conn_id: str, req_id: str) -> tuple[str | None, dict | None]:
        identity = self._identity_contexts.get(conn_id)
        person_id = str(getattr(identity, "person_id", "") or "").strip()
        if not person_id:
            return None, build_error(req_id, ErrorCode.UNAUTHORIZED, "Identity is unavailable")
        return person_id, None

    def _conversation_db(self, req_id: str) -> tuple[Any | None, dict | None]:
        agent = getattr(self._living, "agent", None)
        db = getattr(agent, "conversation_db", None)
        if db is None:
            return None, build_error(req_id, ErrorCode.INTERNAL_ERROR, "Artifact store is unavailable")
        return db, None

    def handle_runtime_status(
        self,
        _conn_id: str,
        req_id: str,
        _params: dict,
    ) -> dict:
        return build_response(req_id, result=inspect_media_runtime())

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaServiceListParams, params, req_id)
        if error:
            return error
        return build_response(
            req_id,
            result=self._service().list(parsed.capability),
        )

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaServiceParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().get(parsed.service_id)
        except MediaServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result)

    def handle_configure(
        self,
        _conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        parsed, error = self._parse(MediaServiceConfigureParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().configure(
                parsed.service_id,
                config=parsed.config,
                enabled=parsed.enabled,
            )
        except MediaServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "service": result,
            "restart_required": True,
        })

    def handle_test(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaServiceTestParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().test(
                parsed.service_id,
                config=parsed.config,
            )
        except MediaServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result=result)

    def handle_remove(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(MediaServiceParams, params, req_id)
        if error:
            return error
        try:
            removed = self._service().remove(parsed.service_id)
        except MediaServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "removed": removed,
            "restart_required": True,
        })

    def _service(self) -> MediaServiceConfigurationService:
        service = getattr(self._living, "_media_service_configuration", None)
        if service is None:
            service = MediaServiceConfigurationService(
                getattr(self._living, "_agent_id", ""),
            )
            self._living._media_service_configuration = service
        return service

    @staticmethod
    def _parse(model: Any, params: dict, req_id: str):
        try:
            return model.model_validate(params), None
        except Exception as exc:
            return None, build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                format_error(exc),
            )
