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

    def _snapshot(
        value: Assignment,
        *,
        handoff: bool = False,
        handoff_message: str = "",
    ) -> str:
        snapshot = _service().public_snapshot(value)
        if handoff:
            snapshot[TOOL_CONTROL_KEY] = {
                "type": "handoff",
                "message": handoff_message.strip() or (
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
        name="revise_assignment",
        description=(
            "当人物要求修改一项已经完成或失败的既有委托时调用。先用 list_assignments(status='all') "
            "核对准确 assignment_id；revision_request 必须完整记录本次修改要求。"
            "继续原委托，不要为同一交付物重复创建新委托。"
        ),
    )
    def revise_assignment(assignment_id: str, revision_request: str) -> str:
        """Reopen an existing agreement and hand a fresh run to the Scheduler."""
        request = revision_request.strip()
        if not request:
            raise ValueError("修改要求不能为空")
        service = _service()
        scheduler = _scheduler()
        if scheduler is None:
            raise RuntimeError("委托后台调度器尚未初始化，不能继续修改")

        # Verify ownership with the current Person before the Agent changes
        # lifecycle state. This prevents a guessed ID from crossing identity.
        current = service.require_assignment(assignment_id, actor=_person_actor())
        if current.status not in {
            AssignmentStatus.COMPLETED,
            AssignmentStatus.FAILED,
        }:
            raise ValueError("只有已经完成或失败的委托才能作为修订重新开始")
        current = service.queue(
            current.id,
            actor=_agent_actor(),
            reason=request,
        )

        core = _core()
        session_id = str(getattr(core, "session_id", "")).strip()
        turn_id = str(getattr(core, "turn_id", "")).strip()
        for resource_type, resource_key, relation in (
            ("session", session_id, "revision_origin"),
            ("turn", turn_id, "revision_request"),
        ):
            if resource_key:
                service.link_resource(
                    current.id,
                    actor=_agent_actor(),
                    resource_type=resource_type,
                    resource_key=resource_key,
                    relation=relation,
                    metadata={"request": request} if resource_type == "turn" else None,
                )
        for attachment in getattr(core, "current_attachments", []) or []:
            attachment_id = str(attachment.get("id", "")).strip()
            if attachment_id:
                service.link_resource(
                    current.id,
                    actor=_agent_actor(),
                    resource_type="attachment",
                    resource_key=attachment_id,
                    relation="input",
                    metadata={
                        key: attachment[key]
                        for key in ("name", "mime_type", "size", "kind")
                        if key in attachment
                    } | {"session_id": session_id},
                )

        scheduler.submit(
            current.id,
            trigger_type="revision",
            trigger_actor_id=_agent_actor().actor_id,
            priority=100,
            checkpoint={"revision_request": request},
        )
        _activate_for_current_turn(current.id)
        current = service.require_assignment(current.id, actor=_agent_actor())
        return _snapshot(
            current,
            handoff=True,
            handoff_message=(
                "我会继续修改原来的委托，旧交付物和本次要求已经交给后台执行。"
                "你可以继续和我聊天。"
            ),
        )

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
        revise_assignment,
        list_assignments,
    ]
