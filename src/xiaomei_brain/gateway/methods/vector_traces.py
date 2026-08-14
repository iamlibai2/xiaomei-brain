"""Read and clear per-Agent vector retrieval diagnostics."""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, build_error, build_response


class VectorTraceMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "vector.trace.list": self.handle_list,
            "vector.trace.clear": self.handle_clear,
        }

    def _store(self):
        return getattr(self._living, "vector_trace_store", None)

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Vector trace store is not ready")
        return build_response(req_id, result=store.list_records(
            session_id=str(params.get("session_id") or ""),
            source=str(params.get("source") or ""),
            phase=str(params.get("phase") or ""),
            limit=int(params.get("limit") or 200),
            offset=int(params.get("offset") or 0),
        ))

    def handle_clear(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Vector trace store is not ready")
        return build_response(req_id, result={"removed": store.clear()})
