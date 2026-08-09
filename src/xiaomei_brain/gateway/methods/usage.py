"""Authenticated LLM usage analysis for one Agent."""

from __future__ import annotations

import logging
from typing import Any

from ..protocol import ErrorCode, build_error, build_response


logger = logging.getLogger(__name__)


class UsageMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "usage.summary": self.handle_summary,
            "usage.list": self.handle_list,
        }

    def _store(self):
        return getattr(self._living, "usage_store", None)

    def handle_summary(self, _conn_id: str, req_id: str, params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Usage ledger is not ready")
        session_id = str(params.get("session_id", "") or "")
        summary = store.summary(
            session_id=session_id,
            turn_limit=int(params.get("turn_limit", 100) or 100),
        )
        summary["context_pressure"] = self._context_pressure(session_id)
        return build_response(
            req_id,
            result={"usage": summary},
        )

    def _context_pressure(self, session_id: str) -> dict[str, Any] | None:
        """Read context pressure without creating another Agent Core."""
        if not session_id:
            return None
        agent_provider = getattr(self._living, "agent", None)
        core = getattr(agent_provider, "_agent", None)
        if core is None and hasattr(agent_provider, "get_context_compaction_status"):
            core = agent_provider
        getter = getattr(core, "get_context_compaction_status", None)
        if not callable(getter):
            return None
        try:
            return getter(session_id)
        except Exception:
            logger.debug(
                "Unable to read context pressure for session %s",
                session_id,
                exc_info=True,
            )
            return None

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Usage ledger is not ready")
        return build_response(
            req_id,
            result=store.list_records(
                session_id=str(params.get("session_id", "") or ""),
                category=str(params.get("category", "") or ""),
                model=str(params.get("model", "") or ""),
                since=(float(params["since"]) if params.get("since") is not None else None),
                limit=int(params.get("limit", 100) or 100),
                offset=int(params.get("offset", 0) or 0),
            ),
        )
