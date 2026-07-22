"""Gateway identity discovery methods."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response


class IdentityMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {"identity.list": self.handle_list}

    def handle_list(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        agent_core = living.agent._get_agent() if hasattr(living, "agent") else None
        manager = getattr(agent_core, "identity_mgr", None)
        identities = []
        if manager:
            for identity_id in manager.list_ids():
                identities.append({
                    "id": identity_id,
                    "name": manager.get_display_name(identity_id),
                    "relation": manager.get_relation(identity_id),
                })
        return build_response(req_id, result={"identities": identities})

