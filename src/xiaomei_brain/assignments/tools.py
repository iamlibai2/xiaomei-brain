"""Conversation tools for Agent-owned Assignment decisions.

These tools do not expose a client-side CRUD surface.  They let the Agent turn
an authenticated conversation into a durable agreement and then report facts
about its own work state.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from xiaomei_brain.tools.base import Tool, tool
from xiaomei_brain.tools.registry import TOOL_CONTROL_KEY

from .models import ActorType, Assignment, AssignmentActor, AssignmentStatus


def create_assignment_tools(agent: Any = None) -> list[Tool]:
    """Create tools that resolve turn-local identity and services lazily."""

    def _core() -> Any:
        if agent is None:
            raise RuntimeError("Agent 尚未初始化")
        return agent._get_agent()

    def _service() -> Any:
        service = getattr(agent, "assignment_service", None)
        if service is None:
            service = getattr(_core(), "assignment_service", None)
        if service is None:
            raise RuntimeError("委托服务尚未初始化")
        return service

    def _purpose() -> Any:
        purpose_ref = getattr(agent, "_purpose_ref", None)
        return purpose_ref[0] if purpose_ref and purpose_ref[0] else None

    def _scheduler() -> Any:
        scheduler = getattr(agent, "assignment_scheduler", None)
        if scheduler is None:
            scheduler = getattr(_core(), "assignment_scheduler", None)
        return scheduler

    def _person_actor() -> AssignmentActor:
        person_id = str(getattr(_core(), "user_id", "")).strip()
        if not person_id or person_id in {"global", "system"}:
            raise ValueError("当前对话尚未识别到人物，不能建立持久委托")
        return AssignmentActor(ActorType.PERSON, person_id)

    def _agent_actor() -> AssignmentActor:
        agent_id = str(getattr(agent, "id", "")).strip()
        if not agent_id:
            raise RuntimeError("Agent 身份不可用")
        return AssignmentActor(ActorType.AGENT, agent_id)

    def _snapshot(value: Assignment, *, handoff: bool = False) -> str:
        snapshot = _service().public_snapshot(value)
        if handoff:
            snapshot[TOOL_CONTROL_KEY] = {
                "type": "handoff",
                "message": (
                    "我已接受这项委托，正在后台执行。你可以继续和我聊天，"
                    "我会持续更新进展。"
                ),
            }
        return json.dumps(snapshot, ensure_ascii=False)

    def _activate_for_current_turn(assignment_id: str) -> None:
        # This field is deliberately turn-local.  ConversationDriver clears it
        # after delivery so a later unrelated turn cannot inherit ownership.
        _core().active_assignment_id = assignment_id

    @tool(
        name="accept_assignment",
        description=(
            "在你已经理解并愿意承担一项需要持续跟踪、交付物或明确完成标准的工作时调用。"
            "它把当前已验证人物提出的工作记录为委托，并由你本人接受。信息不足时先用 clarify，"
            "若接受后仍必须等待人物补充信息，把一个完整问题放入 clarification_question，"
            "后台会持久等待该回复。不要为随手问答或几分钟内即可答完的小请求创建委托。"
        ),
    )
    def accept_assignment(
        title: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str] | None = None,
        requested_due_at: float = 0.0,
        clarification_question: str = "",
        clarification_choices: list[str] | None = None,
    ) -> str:
        """接受当前人物提出的一项持久工作委托。"""
        constraints = constraints or []
        clarification_choices = clarification_choices or []
        person = _person_actor()
        agent_actor = _agent_actor()
        scheduler = _scheduler()
        if scheduler is None:
            raise RuntimeError("委托后台调度器尚未初始化，不能接受持续工作")
        core = _core()
        service = _service()
        session_id = str(getattr(core, "session_id", "")).strip()
        turn_id = str(getattr(core, "turn_id", "")).strip()
        digest = hashlib.sha256(
            f"{person.actor_id}\0{turn_id}\0{title.strip()}".encode("utf-8"),
        ).hexdigest()[:24]
        offered = service.offer(
            title=title,
            objective=objective,
            actor=person,
            requester_person_id=person.actor_id,
            scope_type="person",
            scope_id=person.actor_id,
            origin_channel=str(getattr(core, "current_source", "conversation")),
            origin_session_id=session_id,
            origin_turn_id=turn_id,
            acceptance_criteria=acceptance_criteria,
            constraints={"items": [item.strip() for item in constraints if item.strip()]},
            requested_due_at=requested_due_at or None,
            idempotency_key=(f"assignment-offer:{digest}" if turn_id else None),
        )
        current = offered
        if current.status in {AssignmentStatus.OFFERED, AssignmentStatus.CLARIFYING}:
            current = service.accept(current.id, actor=agent_actor)

        purpose = _purpose()
        if purpose is not None and not current.root_goal_id:
            from xiaomei_brain.purpose.goal import GoalType

            goal = purpose.add_goal(
                description=objective.strip(),
                # Assignment owns external execution. The linked root Goal is
                # strategic context and must not activate shared PACE in the
                # live conversation thread.
                goal_type=GoalType.STRATEGIC,
                deadline=requested_due_at or None,
            )
            goal.metadata.update({
                "assignment_id": current.id,
                "assignment_title": title.strip(),
                "acceptance_criteria": [
                    item.strip() for item in acceptance_criteria if item.strip()
                ],
                "constraints": [item.strip() for item in constraints if item.strip()],
            })
            purpose.save()
            current = service.link_root_goal(
                current.id,
                actor=agent_actor,
                goal_id=goal.id,
            )

        for resource_type, resource_key, relation in (
            ("session", session_id, "origin"),
            ("turn", turn_id, "origin"),
        ):
            if resource_key:
                service.link_resource(
                    current.id,
                    actor=agent_actor,
                    resource_type=resource_type,
                    resource_key=resource_key,
                    relation=relation,
                )
        for attachment in getattr(core, "current_attachments", []) or []:
            attachment_id = str(attachment.get("id", "")).strip()
            if attachment_id:
                service.link_resource(
                    current.id,
                    actor=agent_actor,
                    resource_type="attachment",
                    resource_key=attachment_id,
                    relation="input",
                    metadata={
                        key: attachment[key]
                        for key in ("name", "mime_type", "size", "kind")
                        if key in attachment
                    } | {"session_id": session_id},
                )
        current = service.require_assignment(current.id, actor=agent_actor)
        if current.status == AssignmentStatus.ACCEPTED:
            current = service.queue(current.id, actor=agent_actor)
        if current.status == AssignmentStatus.QUEUED:
            checkpoint: dict[str, Any] = {}
            question = clarification_question.strip()
            if question:
                checkpoint["pending_interaction"] = {
                    "reason": "接受委托前仍缺少必要信息",
                    "question": question,
                    "choices": [
                        item.strip()
                        for item in clarification_choices
                        if item.strip()
                    ],
                }
            scheduler.submit(
                current.id,
                trigger_type="accepted",
                trigger_actor_id=agent_actor.actor_id,
                priority=100,
                checkpoint=checkpoint,
            )
        _activate_for_current_turn(current.id)
        snapshot = _service().public_snapshot(current)
        snapshot[TOOL_CONTROL_KEY] = {
            "type": "handoff",
            "message": (
                f"我已接受这项委托。在继续前需要你确认：{clarification_question.strip()}"
                if clarification_question.strip()
                else "我已接受这项委托，正在后台执行。你可以继续和我聊天，我会持续更新进展。"
            ),
        }
        return json.dumps(snapshot, ensure_ascii=False)

    @tool(
        name="start_assignment",
        description=(
            "当你真正开始或恢复一个已经接受的委托时调用。若委托正在等待人物回答，"
            "把对方的原始回复放入 resume_context；若等待风险操作决定，resume_decision "
            "必须明确填 approve 或 deny，不能根据含糊回复猜测。进入后台队列后不要在当前 Turn 重复执行。"
        ),
    )
    def start_assignment(
        assignment_id: str,
        resume_context: str = "",
        resume_decision: str = "",
    ) -> str:
        current = _service().require_assignment(assignment_id, actor=_agent_actor())
        scheduler = _scheduler()
        if scheduler is None:
            raise RuntimeError("委托后台调度器尚未初始化，不能开始持续工作")
        if current.status in {
            AssignmentStatus.ACCEPTED,
            AssignmentStatus.WAITING_PERSON,
            AssignmentStatus.PAUSED,
        }:
            current = _service().queue(current.id, actor=_agent_actor())
        if current.status != AssignmentStatus.QUEUED:
            raise ValueError(
                f"委托状态 {current.status.value} 不能进入后台队列",
            )
        checkpoint: dict[str, Any] = {}
        for run in _service().store.list_runs(current.id):
            if run.safe_to_resume and run.checkpoint:
                checkpoint = dict(run.checkpoint)
                break
        pending_action = checkpoint.get("pending_action")
        decision = resume_decision.strip().lower()
        if pending_action:
            if decision not in {"approve", "deny"}:
                raise ValueError("该委托正在等待操作决定，resume_decision 必须是 approve 或 deny")
            sealed_action = checkpoint.pop("pending_action")
            if decision == "approve":
                checkpoint["approved_action"] = sealed_action
            else:
                checkpoint["denied_action"] = sealed_action
        if resume_context.strip():
            checkpoint["person_response"] = resume_context.strip()
            checkpoint.pop("pending_interaction", None)
        scheduler.submit(
            current.id,
            trigger_type="conversation",
            trigger_actor_id=_agent_actor().actor_id,
            priority=100,
            checkpoint=checkpoint,
        )
        _activate_for_current_turn(current.id)
        return _snapshot(current, handoff=True)

    @tool(
        name="update_assignment_progress",
        description="当委托取得有意义的新进展时记录简短、可验证的进展；不要记录思维碎片。",
    )
    def update_assignment_progress(
        assignment_id: str,
        summary: str,
        completed_steps: int = -1,
        total_steps: int = -1,
    ) -> str:
        current = _service().update_progress(
            assignment_id,
            actor=_agent_actor(),
            summary=summary,
            completed_steps=None if completed_steps < 0 else completed_steps,
            total_steps=None if total_steps < 0 else total_steps,
        )
        _activate_for_current_turn(current.id)
        return _snapshot(current)

    @tool(
        name="wait_assignment",
        description="委托因缺少人物提供的信息、确认或材料而无法继续时调用，并明确说明等待什么。",
    )
    def wait_assignment(assignment_id: str, reason: str) -> str:
        current = _service().require_assignment(assignment_id, actor=_agent_actor())
        if current.status != AssignmentStatus.IN_PROGRESS:
            raise ValueError("只有正在后台执行的委托才能进入等待状态")
        current = _service().wait_for_person(
            current.id,
            actor=_agent_actor(),
            reason=reason,
        )
        _activate_for_current_turn(current.id)
        return _snapshot(current)

    @tool(
        name="complete_assignment",
        description=(
            "只有完成标准已满足并且交付结果已经给出时才将委托标记完成；summary 必须说明交付了什么。"
        ),
    )
    def complete_assignment(assignment_id: str, summary: str) -> str:
        current = _service().require_assignment(assignment_id, actor=_agent_actor())
        if current.status == AssignmentStatus.COMPLETED:
            _activate_for_current_turn(current.id)
            return _snapshot(current)
        if current.status != AssignmentStatus.IN_PROGRESS:
            raise ValueError("只有正在后台执行的委托才能标记完成")
        current = _service().complete(
            current.id,
            actor=_agent_actor(),
            summary=summary,
        )
        _activate_for_current_turn(current.id)
        return _snapshot(current)

    @tool(
        name="list_assignments",
        description="查看当前已验证人物交给你的委托及状态，用于继续此前工作或回答进度问题。",
    )
    def list_assignments(status: str = "active") -> str:
        person = _person_actor()
        statuses = None
        if status == "active":
            statuses = [
                value for value in AssignmentStatus
                if value not in {
                    AssignmentStatus.COMPLETED,
                    AssignmentStatus.DECLINED,
                    AssignmentStatus.CANCELLED,
                    AssignmentStatus.FAILED,
                }
            ]
        elif status != "all":
            try:
                statuses = [AssignmentStatus(status)]
            except ValueError:
                return "status 必须是 active、all 或有效的委托状态"
        values = _service().list_for_actor(person, statuses=statuses, limit=50)
        return json.dumps(
            [_service().public_snapshot(value) for value in values],
            ensure_ascii=False,
        )

    return [
        accept_assignment,
        start_assignment,
        update_assignment_progress,
        wait_assignment,
        complete_assignment,
        list_assignments,
    ]
