"""Authenticated observation methods for Agent-owned activities."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.activity import ActivityCategory, ActivityStatus

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import ActivityGetParams, ActivityListParams, format_error


class ActivityMethods:
    """Expose global and authenticated-Person Activity projections."""

    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "activity.current": self.handle_current,
            "activity.list": self.handle_list,
            "activity.get": self.handle_get,
        }

    def handle_current(self, conn_id: str, req_id: str, params: dict) -> dict:
        values = dict(params)
        values["status"] = "active"
        values["offset"] = 0
        return self._list(conn_id, req_id, values)

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        return self._list(conn_id, req_id, params)

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ActivityGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        activity = self._service().store.get(parsed.activity_id)
        if activity is None or not self._visible(activity, person_id):
            return build_error(
                req_id,
                ErrorCode.INVALID_REQUEST,
                "Activity does not exist or is not visible",
            )
        return build_response(
            req_id,
            result={"activity": self._service().snapshot(activity)},
        )

    def _list(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ActivityListParams.model_validate(params)
            statuses = self._statuses(parsed.status)
            categories = self._categories(parsed.category)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        candidates = self._service().store.list(
            statuses=statuses,
            categories=categories,
            limit=500,
        )
        visible = [
            item for item in candidates if self._visible(item, person_id)
        ]
        page = visible[parsed.offset:parsed.offset + parsed.limit]
        return build_response(req_id, result={
            "activities": [
                self._service().snapshot(item) for item in page
            ],
            "has_more": len(visible) > parsed.offset + len(page),
        })

    def _person_id(
        self,
        conn_id: str,
        req_id: str,
    ) -> tuple[str | None, dict | None]:
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return None, build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        return str(context.person_id), None

    def _service(self):
        service = getattr(self._living, "_activity_service", None)
        if service is None:
            raise RuntimeError("Activity service is not ready")
        return service

    @staticmethod
    def _visible(activity, person_id: str) -> bool:
        return (
            activity.scope_type == "agent"
            or activity.scope_id == "global"
            or activity.person_id == person_id
            or (
                activity.scope_type == "person"
                and activity.scope_id == person_id
            )
        )

    @staticmethod
    def _statuses(value: str):
        normalized = value.strip().lower()
        if normalized == "all":
            return None
        if normalized == "active":
            return [
                ActivityStatus.QUEUED,
                ActivityStatus.RUNNING,
                ActivityStatus.PAUSED,
            ]
        return [ActivityStatus(normalized)]

    @staticmethod
    def _categories(value: str):
        normalized = value.strip().lower()
        if normalized == "all":
            return None
        return [ActivityCategory(normalized)]
