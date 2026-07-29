"""Gateway RPC methods for Agent-owned model configuration."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.base.config_provider import ConflictError
from xiaomei_brain.llm.configuration import (
    ModelConfigurationBusy,
    ModelConfigurationError,
    ModelConfigurationService,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ModelCatalogParams,
    ModelProviderConfigureParams,
    ModelProviderRemoveParams,
    ModelProviderTestParams,
    ModelSelectionSetParams,
    format_error,
)


class ModelMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "model.config.get": self.handle_get,
            "model.catalog": self.handle_catalog,
            "model.provider.test": self.handle_test,
            "model.provider.configure": self.handle_configure,
            "model.provider.remove": self.handle_remove,
            "model.selection.set": self.handle_set_selection,
        }

    def handle_get(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        return build_response(req_id, result=self._service().get())

    def handle_catalog(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ModelCatalogParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().catalog(parsed.provider_id)
        except ModelConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result)

    def handle_test(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ModelProviderTestParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().test_provider(**parsed.model_dump())
        except ModelConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result=result)

    def handle_configure(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ModelProviderConfigureParams, params, req_id)
        if error:
            return error
        values = parsed.model_dump()
        values["models"] = [model.model_dump() for model in parsed.models]
        try:
            result = self._service().configure_provider(**values)
        except ConflictError:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                "模型配置已被其他操作更新，请刷新后重试",
            )
        except ModelConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result=result)

    def handle_remove(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ModelProviderRemoveParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().remove_provider(**parsed.model_dump())
        except ConflictError:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                "模型配置已被其他操作更新，请刷新后重试",
            )
        except ModelConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result)

    def handle_set_selection(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ModelSelectionSetParams, params, req_id)
        if error:
            return error
        try:
            result = self._service().set_selection(**parsed.model_dump())
        except ConflictError:
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                "模型配置已被其他操作更新，请刷新后重试",
            )
        except ModelConfigurationBusy as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        except ModelConfigurationError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result=result)

    def _service(self) -> ModelConfigurationService:
        service = getattr(self._living, "_model_configuration", None)
        if service is None:
            service = ModelConfigurationService(
                getattr(self._living, "_agent_id", ""),
                living=self._living,
            )
            self._living._model_configuration = service
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
