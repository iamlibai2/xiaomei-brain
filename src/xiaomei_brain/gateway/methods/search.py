"""Person-scoped unified Desktop search."""

from __future__ import annotations

import re
from typing import Any

from xiaomei_brain.assignments import ActorType, AssignmentActor

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import SearchQueryParams, format_error


class SearchMethods:
    """Search Agent-owned conversation and work data through one RPC."""

    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {"search.query": self.handle_query}

    def handle_query(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = SearchQueryParams.model_validate(params)
        except Exception as exc:
            return build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接没有已验证的人物身份")
        db = getattr(getattr(self._living, "agent", None), "conversation_db", None)
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储尚未就绪")

        person_id = str(context.person_id)
        query = parsed.query.strip()
        sessions = db.list_sessions(
            limit=parsed.limit,
            query=query,
            scope_type="person",
            scope_id=person_id,
        )
        messages = db.search_messages_for_person(
            query,
            person_id,
            limit=parsed.limit,
        )
        artifacts = db.search_artifacts_for_person(
            person_id,
            query,
            limit=parsed.limit,
        )
        assignments = self._search_assignments(person_id, query, parsed.limit)

        return build_response(req_id, result={
            "query": query,
            "sessions": [
                {
                    "id": row.get("session_id", ""),
                    "session_id": row.get("session_id", ""),
                    "title": row.get("first_user_message", "") or "未命名会话",
                    "snippet": row.get("first_user_message", ""),
                    "created_at": row.get("created_at", 0),
                    "updated_at": row.get("updated_at", 0),
                    "message_count": row.get("message_count", 0),
                }
                for row in sessions
            ],
            "messages": [
                {
                    "id": str(row.get("id", "")),
                    "message_id": row.get("id"),
                    "session_id": row.get("session_id", ""),
                    "role": row.get("role", ""),
                    "snippet": self._snippet(str(row.get("content") or ""), query),
                    "created_at": row.get("created_at", 0),
                }
                for row in messages
            ],
            "artifacts": [
                {
                    "id": row.get("artifact_id", ""),
                    "artifact_id": row.get("artifact_id", ""),
                    "session_id": row.get("session_id", ""),
                    "title": row.get("name", "") or "未命名产物",
                    "snippet": row.get("description", ""),
                    "kind": row.get("kind", "file"),
                    "mime_type": row.get("mime_type", "application/octet-stream"),
                    "created_at": row.get("created_at", 0),
                }
                for row in artifacts
            ],
            "assignments": assignments,
        })

    def _search_assignments(self, person_id: str, query: str, limit: int) -> list[dict]:
        service = getattr(self._living, "_assignment_service", None)
        if service is None:
            return []
        actor = AssignmentActor(ActorType.PERSON, person_id)
        normalized = query.casefold()
        matches: list[dict] = []
        for assignment in service.list_for_actor(actor, statuses=None, limit=500):
            searchable = "\n".join((
                assignment.title,
                assignment.objective,
                assignment.progress_summary,
                assignment.waiting_reason,
                assignment.terminal_reason,
                *assignment.acceptance_criteria,
            )).casefold()
            if normalized not in searchable:
                continue
            snapshot = service.public_snapshot(assignment)
            matches.append({
                "id": snapshot["id"],
                "assignment_id": snapshot["id"],
                "session_id": snapshot.get("origin_session_id", ""),
                "title": snapshot.get("title", "") or "未命名委托",
                "snippet": self._snippet(
                    snapshot.get("objective", "")
                    or snapshot.get("progress_summary", ""),
                    query,
                ),
                "status": snapshot.get("status", ""),
                "updated_at": snapshot.get("updated_at", 0),
            })
            if len(matches) >= limit:
                break
        return matches

    @staticmethod
    def _snippet(content: str, query: str, width: int = 180) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) <= width:
            return normalized
        index = normalized.casefold().find(query.casefold())
        start = max(0, index - width // 3) if index >= 0 else 0
        value = normalized[start:start + width]
        return f"{'…' if start else ''}{value}{'…' if start + width < len(normalized) else ''}"
