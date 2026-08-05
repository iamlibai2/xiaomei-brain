"""Gateway RPC methods for one Agent's execution environment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaomei_brain.execution import ExecutionEnvironmentManager
from xiaomei_brain.execution.configuration import ExecutionConfigurationService

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ExecutionEnvironmentSaveParams, ExecutionEnvironmentTestParams, format_error


class ExecutionEnvironmentMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "execution.environment.get": self.handle_get,
            "execution.environment.status": self.handle_status,
            "execution.environment.test": self.handle_test,
            "execution.environment.save": self.handle_save,
        }

    def handle_get(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        try:
            return build_response(req_id, result={
                "configuration": self._configuration().get(),
                "runtime": self._runtime_status(),
            })
        except (OSError, ValueError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))

    def handle_status(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        return build_response(req_id, result={"runtime": self._runtime_status()})

    def handle_test(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ExecutionEnvironmentTestParams, params, req_id)
        if error:
            return error
        manager = ExecutionEnvironmentManager(
            agent_id=self._agent_id(),
            workspace_root=self._workspace_root(),
            config=parsed.model_dump(),
        )
        try:
            return build_response(req_id, result={"runtime": manager.describe()})
        finally:
            manager.close()

    def handle_save(self, _conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(ExecutionEnvironmentSaveParams, params, req_id)
        if error:
            return error
        try:
            previous = self._configuration().get()
            configuration = self._configuration().save(parsed.model_dump())
        except (OSError, ValueError) as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "configuration": configuration,
            "restart_required": configuration != previous,
            "runtime": self._runtime_status(),
        })

    def _agent_id(self) -> str:
        return str(getattr(self._living, "_agent_id", ""))

    def _agent_dir(self) -> Path:
        agent = getattr(self._living, "agent", None)
        getter = getattr(agent, "agent_dir", None)
        if callable(getter):
            value = str(getter() or "")
            if value:
                return Path(value)
        return Path.home() / ".xiaomei-brain" / self._agent_id()

    def _workspace_root(self) -> Path:
        manager = self._manager()
        if manager is not None:
            return Path(manager.workspace_root)
        return self._agent_dir() / "workspace"

    def _configuration(self) -> ExecutionConfigurationService:
        service = getattr(self._living, "_execution_environment_configuration", None)
        if service is None:
            service = ExecutionConfigurationService(self._agent_dir() / "config.json")
            self._living._execution_environment_configuration = service
        return service

    def _manager(self) -> ExecutionEnvironmentManager | None:
        agent = getattr(self._living, "agent", None)
        return getattr(agent, "_execution_environment_manager", None)

    def _runtime_status(self) -> dict[str, Any]:
        manager = self._manager()
        if manager is None:
            return {
                "backend": "unknown",
                "display_name": "Unavailable",
                "strong_isolation": False,
                "state": "unavailable",
                "error": "Execution environment is not initialized",
            }
        return manager.describe()

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
