"""Authenticated, read-only observation of Person-visible long-term memory."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.memory.observability import list_person_memory_views

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import MemoryListParams, format_error


class MemoryMethods:
    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {"memory.list": self.handle_list}

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = MemoryListParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                format_error(exc),
            )
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        memory = self._longterm_memory()
        if memory is None:
            return build_error(
                req_id,
                ErrorCode.GATEWAY_NOT_READY,
                "Long-term memory is not ready",
            )
        memories, has_more = list_person_memory_views(
            memory,
            str(context.person_id),
            limit=parsed.limit,
            offset=parsed.offset,
        )
        return build_response(req_id, result={
            "memories": memories,
            "has_more": has_more,
            "next_offset": (
                parsed.offset + len(memories) if has_more else None
            ),
        })

    def _longterm_memory(self):
        agent = getattr(self._living, "agent", None)
        memory = getattr(agent, "longterm_memory", None)
        if memory is not None:
            return memory
        get_agent = getattr(agent, "_get_agent", None)
        core = get_agent() if callable(get_agent) else None
        return getattr(core, "longterm_memory", None)
