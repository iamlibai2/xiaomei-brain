"""Gateway RPC methods for per-Agent external tool service configuration."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.tool_services import (
    ToolServiceConfigurationError,
    ToolServiceConfigurationService,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ToolServiceConfigureParams,
    ToolServiceListParams,
    ToolServiceParams,
    ToolServiceTestParams,
    format_error,
)


class ToolServiceMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "tool.service.list": self.handle_list,
            "tool.service.get": self.handle_get,
            "tool.service.configure": self.handle_configure,
            "tool.service.test": self.handle_test,
            "tool.service.remove": self.handle_remove,
        }

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ToolServiceListParams, params, req_id)
        if error:
            return error
        return build_response(
            req_id,
            result=self._service().list(parsed.capability),
        )

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ToolServiceParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().get(parsed.service_id)
        except ToolServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result)

    def handle_configure(
        self,
        _conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        parsed, error = self._parse(ToolServiceConfigureParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().configure(
                parsed.service_id,
                config=parsed.config,
                enabled=parsed.enabled,
            )
        except ToolServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "service": result,
            "restart_required": True,
        })

    def handle_test(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ToolServiceTestParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().test(
                parsed.service_id,
                config=parsed.config,
            )
        except ToolServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result=result)

    def handle_remove(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ToolServiceParams, params, req_id)
        if error:
            return error
        try:
            removed = self._service().remove(parsed.service_id)
        except ToolServiceConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "removed": removed,
            "restart_required": True,
        })

    def _service(self) -> ToolServiceConfigurationService:
        service = getattr(self._living, "_tool_service_configuration", None)
        if service is None:
            service = ToolServiceConfigurationService(
                getattr(self._living, "_agent_id", ""),
            )
            self._living._tool_service_configuration = service
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
