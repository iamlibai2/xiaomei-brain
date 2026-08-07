"""Gateway RPC methods for Agent capabilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from xiaomei_brain.capability_packages import (
    CapabilityPackageError,
    CapabilityPackageInspector,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    CapabilityChangeParams,
    CapabilityGetParams,
    CapabilityPackageActivateParams,
    CapabilityPackageDeactivateParams,
    CapabilityPackageInspectParams,
    CapabilityPackageUninstallParams,
    CapabilitySetupStartParams,
    CapabilitySetupStatusParams,
    format_error,
)


class CapabilityMethods:
    """Expose the Agent's computed, user-facing capability view."""

    def __init__(self, living: Any) -> None:
        self._living = living
        self._package_inspector = CapabilityPackageInspector()

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "capability.list": self.handle_list,
            "capability.get": self.handle_get,
            "capability.enable": self.handle_enable,
            "capability.disable": self.handle_disable,
            "capability.setup.status": self.handle_setup_status,
            "capability.setup.start": self.handle_setup_start,
            "capability.setup.cancel": self.handle_setup_cancel,
            "capability.package.inspect": self.handle_package_inspect,
            "capability.package.list": self.handle_package_list,
            "capability.package.install": self.handle_package_install,
            "capability.package.activate": self.handle_package_activate,
            "capability.package.deactivate": self.handle_package_deactivate,
            "capability.package.uninstall": self.handle_package_uninstall,
        }

    def handle_list(self, conn_id: str, req_id: str, _params: dict) -> dict:
        agent, error = self._agent(req_id)
        if error:
            return error
        return build_response(
            req_id,
            result={"capabilities": agent.list_capabilities(person_id=self._person_id(conn_id))},
        )

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilityGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))

        agent, error = self._agent(req_id)
        if error:
            return error
        capability = agent.get_capability(parsed.capability_id, person_id=self._person_id(conn_id))
        if capability is None:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"未知能力: {parsed.capability_id}",
            )
        return build_response(req_id, result={"capability": capability})

    def handle_setup_status(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilitySetupStatusParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        runtime, person_id, error = self._runtime(conn_id, req_id, parsed.capability_id)
        if error:
            return error
        state = runtime.inspect(person_id)
        job = runtime.job_status(person_id, parsed.job_id)
        return build_response(req_id, result={
            "runtime": {
                "available": state.available,
                "code": state.code,
                "message": state.message,
                "details": state.details,
                "actions": list(state.actions),
            },
            "job": job,
        })

    def handle_setup_start(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilitySetupStartParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        runtime, person_id, error = self._runtime(conn_id, req_id, parsed.capability_id)
        if error:
            return error
        try:
            job = runtime.start(parsed.action, person_id)
        except (ValueError, RuntimeError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={"job": job})

    def handle_setup_cancel(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilitySetupStatusParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        runtime, person_id, error = self._runtime(conn_id, req_id, parsed.capability_id)
        if error:
            return error
        job = runtime.cancel(person_id, parsed.job_id)
        if job is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "未找到配置任务")
        return build_response(req_id, result={"job": job})

    def handle_enable(self, conn_id: str, req_id: str, params: dict) -> dict:
        return self._change(conn_id, req_id, params, enabled=True)

    def handle_disable(self, conn_id: str, req_id: str, params: dict) -> dict:
        return self._change(conn_id, req_id, params, enabled=False)

    def handle_package_inspect(self, _conn_id: str, req_id: str, params: dict) -> dict:
        """Inspect a package without extracting, installing, or executing it."""
        try:
            parsed = CapabilityPackageInspectParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        try:
            data = base64.b64decode(parsed.data_base64, validate=True)
        except (binascii.Error, ValueError):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "data_base64 不是有效 Base64")
        if parsed.sha256:
            calculated = hashlib.sha256(data).hexdigest()
            if calculated.lower() != parsed.sha256.lower():
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "能力包传输校验失败")
        inspection = self._package_inspector.inspect(data, file_name=parsed.file_name)
        return build_response(req_id, result={"inspection": inspection})

    def handle_package_list(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        service, error = self._package_service(req_id)
        if error:
            return error
        try:
            return build_response(req_id, result={"packages": service.list_packages()})
        except CapabilityPackageError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))

    def handle_package_install(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, data, error = self._parse_package_data(req_id, params)
        if error:
            return error
        service, error = self._package_service(req_id)
        if error:
            return error
        try:
            result = service.install(
                data,
                file_name=parsed.file_name,
                expected_sha256=parsed.sha256,
            )
            return build_response(req_id, result={**result, "restart_required": False})
        except CapabilityPackageError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))

    def handle_package_activate(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilityPackageActivateParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        service, error = self._package_service(req_id)
        if error:
            return error
        try:
            package = service.activate(parsed.package_id, parsed.version, parsed.sha256)
            return build_response(req_id, result={"package": package, "restart_required": True})
        except CapabilityPackageError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))

    def handle_package_deactivate(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilityPackageDeactivateParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        service, error = self._package_service(req_id)
        if error:
            return error
        try:
            package = service.deactivate(parsed.package_id)
            return build_response(req_id, result={"package": package, "restart_required": True})
        except CapabilityPackageError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))

    def handle_package_uninstall(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilityPackageUninstallParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        service, error = self._package_service(req_id)
        if error:
            return error
        try:
            result = service.uninstall(parsed.package_id)
            return build_response(req_id, result={**result, "restart_required": True})
        except CapabilityPackageError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))

    def _parse_package_data(self, req_id: str, params: dict):
        try:
            parsed = CapabilityPackageInspectParams.model_validate(params)
        except Exception as exc:
            return None, None, build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        try:
            data = base64.b64decode(parsed.data_base64, validate=True)
        except (binascii.Error, ValueError):
            return None, None, build_error(req_id, ErrorCode.INVALID_PARAMS, "data_base64 不是有效 Base64")
        if parsed.sha256 and hashlib.sha256(data).hexdigest().lower() != parsed.sha256.lower():
            return None, None, build_error(req_id, ErrorCode.INVALID_PARAMS, "能力包传输校验失败")
        return parsed, data, None

    def _change(self, conn_id: str, req_id: str, params: dict, *, enabled: bool) -> dict:
        try:
            parsed = CapabilityChangeParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        agent, error = self._agent(req_id)
        if error:
            return error
        capability = agent.set_capability_enabled(
            parsed.capability_id,
            enabled,
            person_id=self._person_id(conn_id),
        )
        if capability is None:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"未知能力: {parsed.capability_id}",
            )
        return build_response(req_id, result={"capability": capability})

    def _agent(self, req_id: str):
        agent = getattr(self._living, "agent", None)
        registry = getattr(agent, "_capability_registry", None)
        if agent is None or registry is None:
            return None, build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Agent 能力尚未初始化",
            )
        return agent, None

    def _package_service(self, req_id: str):
        agent = getattr(self._living, "agent", None)
        service = getattr(agent, "_capability_package_service", None)
        if service is None:
            return None, build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Agent 能力包服务尚未初始化",
            )
        return service, None

    @staticmethod
    def _person_id(conn_id: str) -> str:
        from ..connection import cm
        return str(cm.get_person_id(conn_id) or "")

    def _runtime(self, conn_id: str, req_id: str, capability_id: str):
        agent = getattr(self._living, "agent", None)
        runtimes = getattr(agent, "_capability_runtimes", {}) if agent is not None else {}
        runtime = runtimes.get(capability_id)
        if runtime is None:
            return None, "", build_error(req_id, ErrorCode.INVALID_PARAMS, f"该能力没有可配置运行组件: {capability_id}")
        person_id = self._person_id(conn_id)
        if not person_id:
            return None, "", build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有经过验证的人物身份")
        return runtime, person_id, None
