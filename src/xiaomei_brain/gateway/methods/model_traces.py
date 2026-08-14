"""Read-only inspection of the exact requests sent to model providers."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.llm.prompt_analysis import analyze_prompt_trace

from ..protocol import ErrorCode, build_error, build_response


class ModelTraceMethods:
    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "model.trace.list": self.handle_list,
            "model.trace.get": self.handle_get,
            "model.trace.clear": self.handle_clear,
        }

    def _store(self):
        return getattr(self._living, "model_trace_store", None)

    def handle_list(self, _conn_id: str, req_id: str, params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Model trace store is not ready")
        return build_response(req_id, result=store.list_records(
            session_id=str(params.get("session_id") or ""),
            category=str(params.get("category") or ""),
            limit=int(params.get("limit") or 100),
            offset=int(params.get("offset") or 0),
        ))

    def handle_get(self, _conn_id: str, req_id: str, params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Model trace store is not ready")
        trace_id = str(params.get("trace_id") or "")
        record = store.get(trace_id)
        if record is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "Model trace not found")
        record["prompt_analysis"] = analyze_prompt_trace(
            record,
            store.get_previous(record),
        )
        return build_response(req_id, result={"trace": record})

    def handle_clear(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        store = self._store()
        if store is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Model trace store is not ready")
        return build_response(req_id, result={"removed": store.clear()})
