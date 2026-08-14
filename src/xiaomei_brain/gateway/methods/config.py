"""Generic, allowlisted Agent configuration RPC methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.base.config_service import (
    ConfigConflictError,
    ConfigError,
    ConfigService,
)
from xiaomei_brain.consciousness.context_configuration import (
    ContextConfigurationSection,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ConfigGetParams, ConfigResetParams, ConfigUpdateParams, format_error


class ConfigMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "config.get": self.handle_get,
            "config.update": self.handle_update,
            "config.reset": self.handle_reset,
        }

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ConfigGetParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().get(parsed.section)
        except ConfigError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result.to_dict())

    def handle_update(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ConfigUpdateParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().update(
                parsed.section,
                parsed.values,
                base_hash=parsed.revision,
            )
        except ConfigConflictError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        except ConfigError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result.to_dict())

    def handle_reset(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ConfigResetParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().reset(
                parsed.section,
                base_hash=parsed.revision,
            )
        except ConfigConflictError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        except ConfigError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result.to_dict())

    def _service(self) -> ConfigService:
        service = getattr(self._living, "_gateway_config_service", None)
        if service is None:
            service = ConfigService()
            service.register(
                ContextConfigurationSection(
                    self._living,
                    self._agent_dir() / "brain.yaml",
                )
            )
            self._living._gateway_config_service = service
        return service

    def _agent_dir(self) -> Path:
        agent = getattr(self._living, "agent", None)
        getter = getattr(agent, "agent_dir", None)
        if callable(getter):
            value = str(getter() or "")
            if value:
                return Path(value)
        agent_id = str(getattr(self._living, "_agent_id", "") or "")
        return Path.home() / ".xiaomei-brain" / agent_id

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
