"""Gateway RPC methods for Agent capabilities."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import CapabilityChangeParams, CapabilityGetParams, format_error


class CapabilityMethods:
    """Expose the Agent's computed, user-facing capability view."""

    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "capability.list": self.handle_list,
            "capability.get": self.handle_get,
            "capability.enable": self.handle_enable,
            "capability.disable": self.handle_disable,
        }

    def handle_list(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        agent, error = self._agent(req_id)
        if error:
            return error
        return build_response(
            req_id,
            result={"capabilities": agent.list_capabilities()},
        )

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = CapabilityGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))

        agent, error = self._agent(req_id)
        if error:
            return error
        capability = agent.get_capability(parsed.capability_id)
        if capability is None:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"未知能力: {parsed.capability_id}",
            )
        return build_response(req_id, result={"capability": capability})

    def handle_enable(self, _conn_id: str, req_id: str, params: dict) -> dict:
        return self._change(req_id, params, enabled=True)

    def handle_disable(self, _conn_id: str, req_id: str, params: dict) -> dict:
        return self._change(req_id, params, enabled=False)

    def _change(self, req_id: str, params: dict, *, enabled: bool) -> dict:
        try:
            parsed = CapabilityChangeParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        agent, error = self._agent(req_id)
        if error:
            return error
        capability = agent.set_capability_enabled(parsed.capability_id, enabled)
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
