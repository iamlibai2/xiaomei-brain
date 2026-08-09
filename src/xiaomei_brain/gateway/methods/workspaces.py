"""Authenticated workspace observation methods."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.workspaces import WorkspacePermissionError

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    WorkspaceFocusParams,
    WorkspaceGetParams,
    WorkspaceListParams,
    format_error,
)


class WorkspaceMethods:
    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "workspace.list": self.handle_list,
            "workspace.get": self.handle_get,
            "workspace.focus": self.handle_focus,
        }

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = WorkspaceListParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        rows = self._service().list_for_person(person_id, limit=parsed.limit)
        return build_response(req_id, result={
            "workspaces": [self._service().snapshot(item) for item in rows],
        })

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = WorkspaceGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        try:
            workspace = self._service().require_for_person(
                parsed.workspace_id, person_id=person_id,
            )
        except (KeyError, WorkspacePermissionError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={
            "workspace": self._service().snapshot(
                workspace,
                include_surfaces=True,
                include_business=True,
                include_records=True,
            ),
        })

    def handle_focus(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = WorkspaceFocusParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        person_id, error = self._person_id(conn_id, req_id)
        if error:
            return error
        try:
            workspace = self._service().focus_session(
                parsed.workspace_id,
                session_id=parsed.session_id,
                person_id=person_id,
            )
        except (KeyError, WorkspacePermissionError, ValueError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={
            "focused": True,
            "session_id": parsed.session_id,
            "workspace": self._service().snapshot(workspace),
        })

    def _person_id(self, conn_id: str, req_id: str):
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return "", build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        return str(context.person_id), None

    def _service(self):
        service = getattr(self._living, "_workspace_service", None)
        if service is None:
            raise RuntimeError("Workspace service is not ready")
        return service
