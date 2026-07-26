"""Domain service and policy boundary for Agent-local Assignments."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from .models import (
    ActorType,
    Assignment,
    AssignmentActor,
    AssignmentResource,
    AssignmentStatus,
    TERMINAL_ASSIGNMENT_STATUSES,
    validate_transition,
)
from .store import AssignmentStore, new_assignment_id

PublishCallback = Callable[[str, dict[str, Any]], None]
PersonExists = Callable[[str], bool]


class AssignmentPermissionError(PermissionError):
    """The verified actor cannot inspect or change this Assignment."""


class AssignmentService:
    """The only write boundary for Assignment lifecycle changes.

    Gateway and channel adapters must pass a verified AssignmentActor created
    from IdentityContext.  They must never accept a requester Person ID from an
    untrusted message and use it as authority.
    """

    def __init__(
        self,
        store: AssignmentStore,
        *,
        person_exists: PersonExists | None = None,
        publish: PublishCallback | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._person_exists = person_exists
        self._publish = publish
        self._clock = clock

    def offer(
        self,
        *,
        title: str,
        objective: str,
        actor: AssignmentActor,
        requester_person_id: str | None,
        scope_type: str,
        scope_id: str,
        origin_channel: str = "",
        origin_session_id: str = "",
        origin_turn_id: str = "",
        acceptance_criteria: Iterable[str] = (),
        constraints: dict[str, Any] | None = None,
        requested_due_at: float | None = None,
        assignment_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Assignment:
        title = title.strip()
        objective = objective.strip()
        scope_type = scope_type.strip()
        scope_id = scope_id.strip()
        if not title or not objective:
            raise ValueError("委托标题和目标不能为空")
        if not scope_type or not scope_id:
            raise ValueError("委托作用域不能为空")
        self._validate_requester(
            actor,
            requester_person_id,
            scope_type,
            scope_id,
        )
        criteria = tuple(
            item.strip() for item in acceptance_criteria if item.strip()
        )
        if requested_due_at is not None and requested_due_at <= 0:
            raise ValueError("截止时间无效")

        now = self._clock()
        assignment = Assignment(
            id=(assignment_id or new_assignment_id()).strip(),
            title=title,
            objective=objective,
            status=AssignmentStatus.OFFERED,
            requester_person_id=requester_person_id,
            scope_type=scope_type,
            scope_id=scope_id,
            origin_channel=origin_channel.strip(),
            origin_session_id=origin_session_id.strip(),
            origin_turn_id=origin_turn_id.strip(),
            root_goal_id=None,
            acceptance_criteria=criteria,
            constraints=dict(constraints or {}),
            requested_due_at=requested_due_at,
            progress_summary="",
            completed_steps=None,
            total_steps=None,
            waiting_reason="",
            terminal_reason="",
            revision=1,
            created_at=now,
            accepted_at=None,
            started_at=None,
            updated_at=now,
            completed_at=None,
        )
        if not assignment.id:
            raise ValueError("assignment_id 不能为空")
        created = self.store.create_assignment(
            assignment,
            actor=actor,
            payload={"title": title, "objective": objective},
            idempotency_key=idempotency_key,
        )
        self._publish_snapshot("assignment.changed", created)
        return created

    def begin_clarification(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        question: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        question = question.strip()
        if not question:
            raise ValueError("澄清问题不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.CLARIFYING,
            actor=actor,
            expected_revision=expected_revision,
            event_type="clarification_requested",
            payload={"question": question},
        )

    def accept(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        return self._transition(
            assignment_id,
            AssignmentStatus.ACCEPTED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="accepted",
        )

    def decline(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        reason = reason.strip()
        if not reason:
            raise ValueError("拒绝原因不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.DECLINED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="declined",
            reason=reason,
        )

    def queue(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        expected_revision: int | None = None,
        reason: str = "",
    ) -> Assignment:
        self._require_agent_control(actor)
        current = self.require_assignment(assignment_id, actor=actor)
        event_type = (
            "reopened"
            if current.status in {
                AssignmentStatus.COMPLETED,
                AssignmentStatus.FAILED,
            }
            else "queued"
        )
        reopening = event_type == "reopened"
        return self._transition(
            assignment_id,
            AssignmentStatus.QUEUED,
            actor=actor,
            expected_revision=expected_revision,
            event_type=event_type,
            reason=reason.strip(),
            extra_updates=(
                {
                    "progress_summary": reason.strip() or "委托已重新开始",
                    "completed_steps": None,
                    "total_steps": None,
                }
                if reopening
                else None
            ),
            current=current,
        )

    def start(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        return self._transition(
            assignment_id,
            AssignmentStatus.IN_PROGRESS,
            actor=actor,
            expected_revision=expected_revision,
            event_type="started",
        )

    def wait_for_person(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        reason = reason.strip()
        if not reason:
            raise ValueError("等待原因不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.WAITING_PERSON,
            actor=actor,
            expected_revision=expected_revision,
            event_type="waiting",
            reason=reason,
        )

    def pause(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        reason = reason.strip()
        if not reason:
            raise ValueError("暂停原因不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.PAUSED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="paused",
            reason=reason,
        )

    def complete(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        summary: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        summary = summary.strip()
        if not summary:
            raise ValueError("完成摘要不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.COMPLETED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="completed",
            reason=summary,
            extra_updates={"progress_summary": summary},
        )

    def fail(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        reason = reason.strip()
        if not reason:
            raise ValueError("失败原因不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.FAILED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="failed",
            reason=reason,
        )

    def request_cancel(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str = "",
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Assignment:
        current = self.require_assignment(assignment_id, actor=actor)
        if current.is_terminal:
            raise ValueError("已结束的委托不能请求停止")
        # This event asks the Agent to stop at a safe boundary; it does not kill
        # a worker or prematurely claim that cancellation has completed.
        updated = self.store.mutate_assignment(
            assignment_id,
            expected_revision=(
                current.revision
                if expected_revision is None
                else expected_revision
            ),
            updates={},
            event_type="cancel_requested",
            actor=actor,
            payload={"reason": reason.strip()},
            idempotency_key=idempotency_key,
            now=self._clock(),
        )
        self._publish_snapshot("assignment.changed", updated)
        return updated

    def request_resume(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        response: str = "",
        decision: str = "",
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Assignment:
        """Record a Person's request to continue paused work.

        This does not let an external client claim an Agent lifecycle change.
        The scheduler still validates the checkpoint and performs the actual
        queue transition as the Agent.
        """
        current = self.require_assignment(assignment_id, actor=actor)
        if current.status not in {
            AssignmentStatus.WAITING_PERSON,
            AssignmentStatus.PAUSED,
        }:
            raise ValueError("只有等待人物或已暂停的委托可以请求恢复")
        normalized_decision = decision.strip().lower()
        if normalized_decision and normalized_decision not in {"approve", "deny"}:
            raise ValueError("decision 必须是 approve 或 deny")
        updated = self.store.mutate_assignment(
            assignment_id,
            expected_revision=(
                current.revision
                if expected_revision is None
                else expected_revision
            ),
            updates={},
            event_type="resume_requested",
            actor=actor,
            payload={
                "response": response.strip(),
                "decision": normalized_decision,
            },
            idempotency_key=idempotency_key,
            now=self._clock(),
        )
        self._publish_snapshot("assignment.changed", updated)
        return updated

    def cancel(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        reason: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        reason = reason.strip()
        if not reason:
            raise ValueError("取消原因不能为空")
        return self._transition(
            assignment_id,
            AssignmentStatus.CANCELLED,
            actor=actor,
            expected_revision=expected_revision,
            event_type="cancelled",
            reason=reason,
        )

    def update_progress(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        summary: str,
        completed_steps: int | None = None,
        total_steps: int | None = None,
        expected_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Assignment:
        self._require_agent_control(actor)
        summary = summary.strip()
        if not summary:
            raise ValueError("进展摘要不能为空")
        if completed_steps is not None and completed_steps < 0:
            raise ValueError("已完成步骤不能为负数")
        if total_steps is not None and total_steps <= 0:
            raise ValueError("总步骤必须大于零")
        if (
            completed_steps is not None
            and total_steps is not None
            and completed_steps > total_steps
        ):
            raise ValueError("已完成步骤不能超过总步骤")
        current = self.require_assignment(assignment_id, actor=actor)
        if current.status not in {
            AssignmentStatus.ACCEPTED,
            AssignmentStatus.QUEUED,
            AssignmentStatus.IN_PROGRESS,
            AssignmentStatus.WAITING_PERSON,
            AssignmentStatus.PAUSED,
        }:
            raise ValueError("当前委托状态不能更新进展")
        updates: dict[str, Any] = {"progress_summary": summary}
        if completed_steps is not None:
            updates["completed_steps"] = completed_steps
        if total_steps is not None:
            updates["total_steps"] = total_steps
        updated = self.store.mutate_assignment(
            assignment_id,
            expected_revision=(
                current.revision
                if expected_revision is None
                else expected_revision
            ),
            updates=updates,
            event_type="progressed",
            actor=actor,
            payload={
                "summary": summary,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            },
            idempotency_key=idempotency_key,
            now=self._clock(),
        )
        self._publish_snapshot("assignment.changed", updated)
        return updated

    def link_resource(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        resource_type: str,
        resource_key: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> AssignmentResource:
        self.require_assignment(assignment_id, actor=actor)
        resource_type = resource_type.strip()
        resource_key = resource_key.strip()
        relation = relation.strip()
        if not resource_type or not resource_key or not relation:
            raise ValueError("资源类型、标识和关系不能为空")
        resource = AssignmentResource(
            assignment_id=assignment_id,
            resource_type=resource_type,
            resource_key=resource_key,
            relation=relation,
            metadata=dict(metadata or {}),
            created_at=self._clock(),
        )
        linked, inserted = self.store.link_resource(
            resource,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        if inserted:
            current = self.store.get_assignment(assignment_id)
            if current is not None:
                self._publish_snapshot("assignment.changed", current)
        return linked

    def link_root_goal(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
        goal_id: str,
        expected_revision: int | None = None,
    ) -> Assignment:
        """Associate the Agent's private planning root with an Assignment.

        The relationship is intentionally written through the domain service:
        callers cannot silently replace an existing planning tree, and the
        association remains visible in the Assignment event timeline.
        """
        self._require_agent_control(actor)
        goal_id = goal_id.strip()
        if not goal_id:
            raise ValueError("goal_id 不能为空")
        current = self.require_assignment(assignment_id, actor=actor)
        if current.root_goal_id:
            if current.root_goal_id == goal_id:
                return current
            raise ValueError("委托已经关联了另一个根目标")
        updated = self.store.mutate_assignment(
            assignment_id,
            expected_revision=(
                current.revision
                if expected_revision is None
                else expected_revision
            ),
            updates={"root_goal_id": goal_id},
            event_type="goal_linked",
            actor=actor,
            payload={"goal_id": goal_id},
            now=self._clock(),
        )
        self._publish_snapshot("assignment.changed", updated)
        return updated

    def require_assignment(
        self,
        assignment_id: str,
        *,
        actor: AssignmentActor,
    ) -> Assignment:
        assignment = self.store.get_assignment(assignment_id)
        if assignment is None:
            raise ValueError(f"委托不存在: {assignment_id}")
        self._authorize(assignment, actor)
        return assignment

    def list_for_actor(
        self,
        actor: AssignmentActor,
        *,
        statuses: Iterable[AssignmentStatus | str] | None = None,
        limit: int = 100,
    ) -> list[Assignment]:
        if actor.actor_type in {ActorType.AGENT, ActorType.SYSTEM}:
            return self.store.list_assignments(statuses=statuses, limit=limit)
        return self.store.list_assignments(
            statuses=statuses,
            requester_person_id=actor.actor_id,
            limit=limit,
        )

    def pending_interaction_for_session(
        self,
        *,
        actor: AssignmentActor,
        session_id: str,
    ) -> Assignment | None:
        """Return the sole durable information request in this conversation.

        A normal message may answer a pending clarification, but it must never
        approve a pending Action. Ambiguous multiple waits are intentionally
        not guessed; the Person can then answer from a specific card.
        """
        session_id = session_id.strip()
        if not session_id or actor.actor_type != ActorType.PERSON:
            return None
        matches: list[Assignment] = []
        for assignment in self.list_for_actor(
            actor,
            statuses=[AssignmentStatus.WAITING_PERSON],
            limit=100,
        ):
            if assignment.origin_session_id != session_id:
                continue
            for run in self.store.list_runs(assignment.id):
                if not run.safe_to_resume or not run.checkpoint:
                    continue
                if isinstance(run.checkpoint.get("pending_interaction"), dict):
                    matches.append(assignment)
                break
        return matches[0] if len(matches) == 1 else None

    def _transition(
        self,
        assignment_id: str,
        target: AssignmentStatus,
        *,
        actor: AssignmentActor,
        expected_revision: int | None,
        event_type: str,
        reason: str = "",
        payload: dict[str, Any] | None = None,
        extra_updates: dict[str, Any] | None = None,
        current: Assignment | None = None,
    ) -> Assignment:
        current = current or self.require_assignment(assignment_id, actor=actor)
        self._authorize(current, actor)
        validate_transition(current.status, target)
        now = self._clock()
        updates: dict[str, Any] = {
            "status": target,
            "waiting_reason": "",
        }
        if target == AssignmentStatus.ACCEPTED:
            updates["accepted_at"] = now
        if target == AssignmentStatus.IN_PROGRESS and current.started_at is None:
            updates["started_at"] = now
        if target == AssignmentStatus.WAITING_PERSON:
            updates["waiting_reason"] = reason
        elif target == AssignmentStatus.PAUSED:
            updates["waiting_reason"] = reason
        if target in TERMINAL_ASSIGNMENT_STATUSES:
            updates["terminal_reason"] = reason
            updates["completed_at"] = now
        elif current.status in TERMINAL_ASSIGNMENT_STATUSES:
            # Reopening retains event history but clears terminal snapshot data.
            updates["terminal_reason"] = ""
            updates["completed_at"] = None
        if extra_updates:
            updates.update(extra_updates)
        event_payload = dict(payload or {})
        if reason:
            event_payload.setdefault("reason", reason)
        updated = self.store.mutate_assignment(
            assignment_id,
            expected_revision=(
                current.revision
                if expected_revision is None
                else expected_revision
            ),
            updates=updates,
            event_type=event_type,
            actor=actor,
            payload=event_payload,
            now=now,
        )
        self._publish_snapshot("assignment.changed", updated)
        return updated

    def _validate_requester(
        self,
        actor: AssignmentActor,
        requester_person_id: str | None,
        scope_type: str,
        scope_id: str,
    ) -> None:
        if scope_type == "internal":
            if requester_person_id is not None:
                raise ValueError("内部委托不能设置 requester_person_id")
            if actor.actor_type == ActorType.PERSON:
                raise AssignmentPermissionError("Person 不能创建内部委托")
            return
        if not requester_person_id:
            raise ValueError("外部委托必须关联 requester Person")
        if self._person_exists and not self._person_exists(requester_person_id):
            raise ValueError(f"人物不存在: {requester_person_id}")
        if actor.actor_type == ActorType.PERSON and actor.actor_id != requester_person_id:
            raise AssignmentPermissionError("不能代表其他 Person 提出委托")
        if scope_type == "person" and scope_id != requester_person_id:
            raise ValueError("人物委托的 scope_id 必须是 requester Person")

    @staticmethod
    def _authorize(assignment: Assignment, actor: AssignmentActor) -> None:
        if actor.actor_type in {ActorType.AGENT, ActorType.SYSTEM}:
            return
        if assignment.requester_person_id != actor.actor_id:
            raise AssignmentPermissionError("无权访问这项委托")

    @staticmethod
    def _require_agent_control(actor: AssignmentActor) -> None:
        """Only the Agent/system may claim changes to its own work state."""
        if actor.actor_type not in {ActorType.AGENT, ActorType.SYSTEM}:
            raise AssignmentPermissionError("只有 Agent 可以改变委托执行状态")

    def _publish_snapshot(self, event: str, assignment: Assignment) -> None:
        if self._publish is None:
            return
        try:
            payload = self.public_snapshot(assignment)
            if assignment.status == AssignmentStatus.COMPLETED:
                payload["deliverables"] = [
                    dict(resource.metadata)
                    for resource in self.store.list_resources(assignment.id)
                    if resource.resource_type == "artifact"
                    and resource.relation == "deliverable"
                ]
            # Projection-only routing data is deliberately outside the public
            # Assignment snapshot and is removed before Gateway delivery.
            payload["_target_person_id"] = assignment.requester_person_id or ""
            payload["session_id"] = assignment.origin_session_id
            self._publish(event, payload)
        except Exception:
            # Publishing is a projection.  A UI/channel failure must never roll
            # back a domain change that was already committed to brain.db.
            return

    @staticmethod
    def public_snapshot(assignment: Assignment) -> dict[str, Any]:
        """Return only stable, non-sensitive fields for future projections."""
        return {
            "id": assignment.id,
            "title": assignment.title,
            "objective": assignment.objective,
            "status": assignment.status.value,
            "scope_type": assignment.scope_type,
            "scope_id": assignment.scope_id,
            # The origin session is public routing context. Desktop uses it to
            # show an Assignment beside the conversation that created it,
            # while the Agent-level drawer can still show every Assignment.
            "origin_session_id": assignment.origin_session_id,
            "acceptance_criteria": list(assignment.acceptance_criteria),
            "requested_due_at": assignment.requested_due_at,
            "progress_summary": assignment.progress_summary,
            "completed_steps": assignment.completed_steps,
            "total_steps": assignment.total_steps,
            "waiting_reason": assignment.waiting_reason,
            "terminal_reason": assignment.terminal_reason,
            "revision": assignment.revision,
            "created_at": assignment.created_at,
            "updated_at": assignment.updated_at,
            "completed_at": assignment.completed_at,
        }
