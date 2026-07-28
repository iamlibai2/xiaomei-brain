"""Authenticated observation of one Agent's current living state."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response


class AgentStateMethods:
    def __init__(
        self,
        living: Any,
        identity_contexts: dict[str, Any],
    ) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {"agent.state.get": self.handle_get}

    def handle_get(self, conn_id: str, req_id: str, _params: dict) -> dict:
        getter = getattr(self._living, "get_state_snapshot", None)
        if getter is None:
            return build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Agent state is not ready",
            )
        state = dict(getter())
        context = self._identity_contexts.get(conn_id)
        relationship_getter = getattr(
            self._living,
            "get_relationship_projection",
            None,
        )
        state["relationship"] = (
            relationship_getter(str(context.person_id))
            if context is not None and relationship_getter is not None
            else None
        )
        return build_response(req_id, result={"state": state})
