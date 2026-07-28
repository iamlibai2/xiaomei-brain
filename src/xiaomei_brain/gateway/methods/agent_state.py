"""Authenticated observation of one Agent's current living state."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response


class AgentStateMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {"agent.state.get": self.handle_get}

    def handle_get(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        getter = getattr(self._living, "get_state_snapshot", None)
        if getter is None:
            return build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Agent state is not ready",
            )
        return build_response(req_id, result={"state": getter()})
