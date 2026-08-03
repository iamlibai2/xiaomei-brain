"""Authenticated observation methods for Agent-owned Projects."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.projects import (
    ProjectActor,
    ProjectActorType,
    ProjectPermissionError,
    ProjectStatus,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ProjectCurrentParams,
    ProjectGetParams,
    ProjectListParams,
    format_error,
)


class ProjectMethods:
    """Expose Person-scoped Project state without filesystem authority."""

    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "project.list": self.handle_list,
            "project.get": self.handle_get,
            "project.current": self.handle_current,
        }

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ProjectListParams.model_validate(params)
            status = self._status(parsed.status)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        projects = self._service().list_for_actor(
            actor=actor, status=status, limit=parsed.limit,
        )
        return build_response(req_id, result={
            "projects": [
                self._service().public_snapshot(project) for project in projects
            ],
        })

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ProjectGetParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            project = self._service().require_project(
                parsed.project_id, actor=actor,
            )
        except (KeyError, ValueError, ProjectPermissionError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(
            req_id,
            result=self._details(project, event_limit=parsed.event_limit),
        )

    def handle_current(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ProjectCurrentParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, format_error(exc))
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        binding = self._service().store.get_session_binding(parsed.session_id)
        if binding is None:
            return build_response(req_id, result={"project": None})
        try:
            project = self._service().require_project(
                binding.project_id, actor=actor,
            )
        except (KeyError, ValueError, ProjectPermissionError):
            return build_response(req_id, result={"project": None})
        return build_response(req_id, result=self._details(project, event_limit=50))

    def _details(self, project: Any, *, event_limit: int) -> dict[str, Any]:
        store = self._service().store
        events = store.list_events(project.id)[-event_limit:]
        assignments = []
        assignment_service = getattr(self._living, "_assignment_service", None)
        if assignment_service is not None:
            assignments = [
                assignment_service.public_snapshot(item)
                for item in assignment_service.store.list_assignments(limit=500)
                if item.scope_type == "project" and item.scope_id == project.id
            ]
        activities = []
        activity_service = getattr(self._living, "_activity_service", None)
        if activity_service is not None:
            activities = [
                activity_service.snapshot(item)
                for item in activity_service.store.list(
                    scope_type="project", scope_id=project.id, limit=200,
                )
            ]
        process = None
        process_service = getattr(self._living, "_process_service", None)
        if process_service is not None:
            current_process = process_service.store.get_for_project(project.id)
            if current_process is not None:
                process = process_service.snapshot(current_process)
        return {
            "project": self._service().public_snapshot(project),
            "process": process,
            "steps": [self._step(item) for item in store.list_steps(project.id)],
            "assets": [self._asset(item) for item in store.list_assets(project.id)],
            "resources": [
                self._resource(item) for item in store.list_resources(project.id)
            ],
            "events": [self._event(item) for item in events],
            "assignments": assignments,
            "activities": activities,
        }

    def _person_actor(self, conn_id: str, req_id: str):
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return None, build_error(
                req_id, ErrorCode.UNAUTHORIZED,
                "Current connection has no verified Person identity",
            )
        return ProjectActor(ProjectActorType.PERSON, str(context.person_id)), None

    def _service(self):
        service = getattr(self._living, "_project_service", None)
        if service is None:
            raise RuntimeError("Project service is not ready")
        return service

    @staticmethod
    def _status(value: str) -> ProjectStatus | None:
        normalized = value.strip().lower()
        return None if normalized == "all" else ProjectStatus(normalized)

    @staticmethod
    def _step(step) -> dict[str, Any]:
        return {
            "step_id": step.step_id,
            "parent_step_id": step.parent_step_id,
            "title": step.title,
            "position": step.position,
            "status": step.status.value,
            "summary": step.summary,
            "completed_units": step.completed_units,
            "total_units": step.total_units,
            "updated_at": step.updated_at,
        }

    @staticmethod
    def _asset(asset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "role": asset.role.value,
            "kind": asset.kind,
            "name": asset.name,
            "mime_type": asset.mime_type,
            "size": asset.size,
            "status": asset.status.value,
            "source_type": asset.source_type,
            "source_id": asset.source_id,
            "parent_asset_id": asset.parent_asset_id,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }

    @staticmethod
    def _resource(resource) -> dict[str, Any]:
        return {
            "type": resource.resource_type,
            "key": resource.resource_key,
            "relation": resource.relation,
            "metadata": {
                key: value for key, value in resource.metadata.items()
                if key not in {"path", "absolute_path", "internal_path"}
            },
            "created_at": resource.created_at,
        }

    @staticmethod
    def _event(event) -> dict[str, Any]:
        return {
            "id": event.id,
            "type": event.event_type,
            "actor_type": event.actor_type.value,
            "payload": dict(event.payload),
            "created_at": event.created_at,
        }
