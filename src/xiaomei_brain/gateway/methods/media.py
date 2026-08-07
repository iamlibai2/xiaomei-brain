"""Gateway RPC methods for per-Agent media service configuration."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.media import (
    MediaServiceConfigurationError,
    MediaServiceConfigurationService,
    inspect_media_runtime,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    MediaServiceConfigureParams,
    MediaServiceListParams,
    MediaServiceParams,
    MediaServiceTestParams,
    format_error,
)


class MediaServiceMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "media.service.list": self.handle_list,
            "media.service.get": self.handle_get,
            "media.service.configure": self.handle_configure,
            "media.service.test": self.handle_test,
            "media.service.remove": self.handle_remove,
            "media.runtime.status": self.handle_runtime_status,
        }

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
