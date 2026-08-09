"""Authenticated LLM usage analysis for one Agent."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response


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
        return build_response(
            req_id,
            result={
                "usage": store.summary(
                    session_id=str(params.get("session_id", "") or ""),
                    turn_limit=int(params.get("turn_limit", 100) or 100),
                )
            },
        )

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
