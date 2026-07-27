"""Person-scoped Gateway methods for Agent-owned Assignments."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentConflictError,
    AssignmentPermissionError,
    AssignmentStatus,
)

from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    AssignmentCancelParams,
    AssignmentArtifactGetParams,
    AssignmentGetParams,
    AssignmentListParams,
    AssignmentResumeParams,
    format_error,
)


class AssignmentMethods:
    """Expose observation and Person requests, never lifecycle ownership."""

    def __init__(self, living: Any, identity_contexts: dict[str, Any]) -> None:
        self._living = living
        self._identity_contexts = identity_contexts

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "assignment.list": self.handle_list,
            "assignment.get": self.handle_get,
            "assignment.artifact.get": self.handle_artifact_get,
            "assignment.request_cancel": self.handle_request_cancel,
            "assignment.request_resume": self.handle_request_resume,
        }

    def handle_list(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(AssignmentListParams, params, req_id)
        if error:
            return error
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            statuses = self._statuses(parsed.status)
            assignments = self._service().list_for_actor(
                actor,
                statuses=statuses,
                limit=parsed.limit,
            )
        except ValueError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={
            "assignments": [
                self._service().public_snapshot(item) for item in assignments
            ],
        })

    def handle_get(self, conn_id: str, req_id: str, params: dict) -> dict:
        parsed, error = self._parse(AssignmentGetParams, params, req_id)
        if error:
            return error
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            assignment = self._service().require_assignment(
                parsed.assignment_id,
                actor=actor,
            )
        except (ValueError, AssignmentPermissionError) as exc:
            # Do not reveal whether an ID exists but belongs to another Person.
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        events = self._service().store.list_events(
            assignment.id,
            limit=parsed.event_limit,
        )
        resources = self._service().store.list_resources(assignment.id)
        runs = self._service().store.list_runs(assignment.id)
        return build_response(req_id, result={
            "assignment": self._service().public_snapshot(assignment),
            "events": [self._public_event(item) for item in events],
            "resources": [self._public_resource(item) for item in resources],
            "pending": self._public_pending(runs),
            "execution_plan": self._public_execution_plan(runs),
            "acceptance_verification": self._public_acceptance_verification(
                runs,
                assignment.acceptance_criteria,
            ),
        })

    def handle_artifact_get(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        parsed, error = self._parse(AssignmentArtifactGetParams, params, req_id)
        if error:
            return error
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            assignment = self._service().require_assignment(
                parsed.assignment_id,
                actor=actor,
            )
        except (ValueError, AssignmentPermissionError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        linked = self._service().store.get_resource(
            assignment.id,
            "artifact",
            parsed.artifact_id,
            "deliverable",
        ) or self._service().store.get_resource(
            assignment.id,
            "artifact",
            parsed.artifact_id,
            "output",
        )
        if linked is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "产物不属于这项委托")
        living = self._living
        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")
        session_id = f"assignment:{assignment.id}"
        artifact = db.get_artifact_metadata(session_id, parsed.artifact_id)
        if artifact is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "委托产物不存在")
        from ..artifacts import ArtifactError, read_stored_artifact
        try:
            value = read_stored_artifact(
                getattr(living, "_agent_id", "default"),
                session_id,
                artifact,
            )
        except ArtifactError as exc:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        return build_response(req_id, result={"artifact": value})

    def handle_request_cancel(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        parsed, error = self._parse(AssignmentCancelParams, params, req_id)
        if error:
            return error
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            assignment = self._service().request_cancel(
                parsed.assignment_id,
                actor=actor,
                reason=parsed.reason,
                expected_revision=parsed.expected_revision,
                idempotency_key=f"gateway:{req_id}:cancel",
            )
            scheduler = self._scheduler()
            stopping = bool(
                scheduler and scheduler.request_cancel(assignment.id)
            )
            latest = self._service().require_assignment(assignment.id, actor=actor)
        except AssignmentConflictError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        except (ValueError, AssignmentPermissionError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={
            "requested": True,
            "stopping": stopping,
            "assignment": self._service().public_snapshot(latest),
        })

    def handle_request_resume(
        self,
        conn_id: str,
        req_id: str,
        params: dict,
    ) -> dict:
        parsed, error = self._parse(AssignmentResumeParams, params, req_id)
        if error:
            return error
        actor, error = self._person_actor(conn_id, req_id)
        if error:
            return error
        try:
            requested = self._service().request_resume(
                parsed.assignment_id,
                actor=actor,
                response=parsed.response,
                decision=parsed.decision or "",
                expected_revision=parsed.expected_revision,
                idempotency_key=f"gateway:{req_id}:resume",
            )
            scheduler = self._scheduler()
            queued = bool(scheduler and scheduler.request_resume(
                requested.id,
                trigger_actor_id=actor.actor_id,
                response=parsed.response,
                decision=parsed.decision or "",
            ))
            latest = self._service().require_assignment(requested.id, actor=actor)
        except AssignmentConflictError as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        except (ValueError, AssignmentPermissionError) as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, str(exc))
        return build_response(req_id, result={
            "requested": True,
            "queued": queued,
            "assignment": self._service().public_snapshot(latest),
        })

    def _person_actor(
        self,
        conn_id: str,
        req_id: str,
    ) -> tuple[AssignmentActor | None, dict | None]:
        context = self._identity_contexts.get(conn_id)
        if context is None:
            return None, build_error(
                req_id,
                ErrorCode.UNAUTHORIZED,
                "当前连接没有已验证的人物身份",
            )
        return AssignmentActor(ActorType.PERSON, context.person_id), None

    def _service(self):
        service = getattr(self._living, "_assignment_service", None)
        if service is None:
            raise RuntimeError("委托服务未就绪")
        return service

    def _scheduler(self):
        return getattr(self._living, "_assignment_scheduler", None)

    @staticmethod
    def _statuses(value: str):
        normalized = value.strip().lower()
        if normalized == "all":
            return None
        if normalized == "active":
            terminal = {
                AssignmentStatus.COMPLETED,
                AssignmentStatus.DECLINED,
                AssignmentStatus.CANCELLED,
                AssignmentStatus.FAILED,
            }
            return [status for status in AssignmentStatus if status not in terminal]
        try:
            return [AssignmentStatus(normalized)]
        except ValueError as exc:
            raise ValueError("status 必须是 active、all 或有效的委托状态") from exc

    @staticmethod
    def _public_event(event) -> dict[str, Any]:
        return {
            "id": event.id,
            "type": event.event_type,
            "actor_type": event.actor_type.value,
            "payload": dict(event.payload),
            "created_at": event.created_at,
        }

    @staticmethod
    def _public_resource(resource) -> dict[str, Any]:
        metadata = {
            key: value
            for key, value in resource.metadata.items()
            if key not in {"internal_path", "path", "absolute_path"}
        }
        return {
            "type": resource.resource_type,
            "key": resource.resource_key,
            "relation": resource.relation,
            "metadata": metadata,
            "created_at": resource.created_at,
        }

    @staticmethod
    def _public_pending(runs) -> dict[str, Any] | None:
        for run in runs:
            if not run.safe_to_resume or not run.checkpoint:
                continue
            interaction = run.checkpoint.get("pending_interaction")
            if isinstance(interaction, dict):
                return {
                    "kind": "interaction",
                    "question": str(interaction.get("question") or interaction.get("reason") or ""),
                    "choices": [
                        value for value in interaction.get("choices", [])
                        if isinstance(value, str)
                    ],
                }
            action = run.checkpoint.get("pending_action")
            if isinstance(action, dict):
                arguments = action.get("arguments")
                return {
                    "kind": "action",
                    "tool_name": str(action.get("tool_name") or ""),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                    "summary": str(action.get("summary") or ""),
                    "reason": str(action.get("reason") or ""),
                    "risk_level": str(action.get("risk_level") or "medium"),
                }
        return None

    @staticmethod
    def _public_execution_plan(runs) -> dict[str, Any] | None:
        """Expose factual step status, never the private execution checkpoint."""
        for run in runs:
            checkpoint = run.checkpoint or {}
            raw = checkpoint.get("execution_plan")
            if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
                continue
            steps = []
            for item in raw["steps"][:8]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                steps.append({
                    "title": title[:200],
                    "status": (
                        "completed" if item.get("status") == "completed" else "pending"
                    ),
                    "summary": str(item.get("summary") or "")[:500],
                })
            if steps:
                return {
                    "steps": steps,
                    "completed_steps": sum(
                        item["status"] == "completed" for item in steps
                    ),
                    "total_steps": len(steps),
                }
        return None

    @staticmethod
    def _public_acceptance_verification(
        runs,
        acceptance_criteria,
    ) -> dict[str, Any] | None:
        """Expose factual criterion checks from only the latest execution run."""
        if not runs:
            return None
        raw = (runs[0].checkpoint or {}).get("acceptance_verification")
        checks = raw.get("criteria") if isinstance(raw, dict) else None
        criteria = list(acceptance_criteria)
        if not isinstance(checks, list) or len(checks) != len(criteria):
            return None
        public = []
        by_index = {
            item.get("criterion_index"): item
            for item in checks
            if isinstance(item, dict)
        }
        for index, criterion in enumerate(criteria, start=1):
            item = by_index.get(index)
            if not isinstance(item, dict) or item.get("criterion") != criterion:
                return None
            evidence = str(item.get("evidence") or "").strip()
            if not evidence:
                return None
            public.append({
                "criterion_index": index,
                "criterion": criterion,
                "satisfied": item.get("satisfied") is True,
                "evidence": evidence[:1000],
            })
        return {
            "criteria": public,
            "checked_at": raw.get("checked_at"),
        }

    @staticmethod
    def _parse(model, params: dict, req_id: str):
        try:
            return model.model_validate(params), None
        except Exception as exc:
            return None, build_error(
                req_id,
                ErrorCode.INVALID_PARAMS,
                f"参数无效: {format_error(exc)}",
            )
