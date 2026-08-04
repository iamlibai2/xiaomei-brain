from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentService,
    AssignmentStatus,
    AssignmentStore,
    AssignmentRun,
    AssignmentExecutor,
    AssignmentScheduler,
    ExecutionResult,
    create_assignment_tools,
)
from xiaomei_brain.processes import ProcessService, ProcessStore
from xiaomei_brain.projects import (
    ProjectActor,
    ProjectActorType,
    ProjectService,
    ProjectStore,
    ProjectWorkspaceManager,
)


class FakePurpose:
    def __init__(self) -> None:
        self.goals = []
        self.saved = 0

    def add_goal(self, description, goal_type, deadline=None):
        goal = SimpleNamespace(
            id=f"goal_{len(self.goals) + 1}",
            description=description,
            metadata={},
        )
        self.goals.append(goal)
        return goal

    def save(self) -> None:
        self.saved += 1


class FakeScheduler:
    def __init__(self) -> None:
        self.submissions = []
        self._submitted_ids = set()

    def submit(self, assignment_id, **kwargs):
        if assignment_id in self._submitted_ids:
            return False
        self._submitted_ids.add(assignment_id)
        self.submissions.append((assignment_id, kwargs))
        return True


class FakeAgentInstance:
    def __init__(
        self,
        service,
        purpose,
        *,
        person_id="person_1",
        scheduler=None,
    ) -> None:
        self.id = "xiaomei"
        self.assignment_service = service
        self.assignment_scheduler = scheduler or FakeScheduler()
        self._purpose_ref = [purpose]
        self.core = SimpleNamespace(
            user_id=person_id,
            session_id="session_1",
            turn_id="turn_1",
            current_source="ws",
            current_attachments=[{
                "id": "attachment_1",
                "name": "requirements.docx",
                "mime_type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "size": 123,
                "kind": "document",
            }],
            active_assignment_id="",
        )

    def _get_agent(self):
        return self.core


def _tools(agent):
    return {value.name: value for value in create_assignment_tools(agent)}


def test_assignment_tool_schemas_expose_list_parameters(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    agent = FakeAgentInstance(AssignmentService(store), FakePurpose())
    tool = _tools(agent)["accept_assignment"]

    assert tool.parameters["properties"]["acceptance_criteria"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert tool.parameters["properties"]["constraints"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    store.close()


def test_accept_assignment_records_both_actors_and_turn_resources_without_goal(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    purpose = FakePurpose()
    agent = FakeAgentInstance(service, purpose)
    tools = _tools(agent)

    result = json.loads(tools["accept_assignment"].execute(
        title="研究三家竞品",
        objective="比较三家竞品并交付包含建议的研究报告",
        acceptance_criteria=["三家产品对比", "给出明确建议"],
        constraints=["使用中文"],
        requested_due_at=0.0,
    ))

    assignment = store.get_assignment(result["id"])
    assert assignment.status == AssignmentStatus.QUEUED
    assert result["_xiaomei_control"]["type"] == "handoff"
    assert assignment.requester_person_id == "person_1"
    assert assignment.root_goal_id is None
    assert purpose.goals == []
    assert purpose.saved == 0
    assert agent.core.active_assignment_id == assignment.id
    assert [(event.event_type, event.actor_type) for event in store.list_events(
        assignment.id,
    )][:2] == [
        ("offered", ActorType.PERSON),
        ("accepted", ActorType.AGENT),
    ]
    resources = {
        (item.resource_type, item.resource_key, item.relation)
        for item in store.list_resources(assignment.id)
    }
    assert ("session", "session_1", "origin") in resources
    assert ("turn", "turn_1", "origin") in resources
    assert ("attachment", "attachment_1", "input") in resources
    assert agent.assignment_scheduler.submissions == [(
        assignment.id,
        {
            "trigger_type": "accepted",
            "trigger_actor_id": "xiaomei",
            "priority": 100,
            "checkpoint": {},
        },
    )]
    store.close()


def test_repeated_accept_in_same_turn_is_idempotent(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    purpose = FakePurpose()
    agent = FakeAgentInstance(service, purpose)
    tools = _tools(agent)
    arguments = {
        "title": "整理访谈",
        "objective": "整理访谈并形成结论清单",
        "acceptance_criteria": ["结论清单"],
    }

    first = json.loads(tools["accept_assignment"].execute(**arguments))
    second = json.loads(tools["accept_assignment"].execute(**arguments))

    assert first["id"] == second["id"]
    assert len(store.list_assignments()) == 1
    assert purpose.goals == []
    assert len(agent.assignment_scheduler.submissions) == 1
    store.close()


def test_project_assignment_requires_declared_process_first(tmp_path):
    database = tmp_path / "brain.db"
    assignment_store = AssignmentStore(database)
    assignments = AssignmentService(
        assignment_store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    projects = ProjectService(
        ProjectStore(database),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    processes = ProcessService(ProcessStore(database), projects)
    project = projects.create(
        name="Delivery film",
        project_type="video.production",
        actor=ProjectActor(ProjectActorType.AGENT, "xiaomei"),
        scope_type="person",
        scope_id="person_1",
        metadata={
            "delivery_process": {"required": True, "requested_stage_count": 5},
            "execution": {"assignment_required": True},
        },
    )
    agent = FakeAgentInstance(assignments, FakePurpose())
    agent.project_service = projects
    agent.process_service = processes
    agent.core.project_service = projects
    agent.core.process_service = processes
    agent.core.active_project_id = project.id
    tool = _tools(agent)["accept_assignment"]

    with pytest.raises(ValueError, match="必须先建立 Process"):
        tool.execute(
            title="Produce film",
            objective="Deliver the film",
            acceptance_criteria=["Final film"],
        )

    processes.define(
        project.id,
        {
            "id": "five-stage",
            "name": "Five stages",
            "stages": [
                {"id": f"stage-{index}", "title": f"Stage {index}"}
                for index in range(1, 6)
            ],
        },
        actor=ProjectActor(ProjectActorType.AGENT, "xiaomei"),
    )
    accepted = json.loads(tool.execute(
        title="Produce film",
        objective="Deliver the film",
        acceptance_criteria=["Final film"],
    ))
    assert accepted["scope_type"] == "project"
    assert accepted["scope_id"] == project.id

    processes.store.close()
    projects.store.close()
    assignment_store.close()


def test_assignment_tools_reject_unidentified_conversation(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(store)
    tools = _tools(FakeAgentInstance(service, FakePurpose(), person_id="global"))

    try:
        tools["accept_assignment"].execute(
            title="不能创建",
            objective="没有真实人物身份时不能建立外部委托",
            acceptance_criteria=["不会落库"],
        )
    except ValueError as exc:
        assert "尚未识别到人物" in str(exc)
    else:
        raise AssertionError("unidentified conversation created an Assignment")
    assert store.list_assignments() == []
    store.close()


def test_live_conversation_cannot_mutate_runner_owned_progress_or_completion(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    tools = _tools(FakeAgentInstance(service, FakePurpose()))
    accepted = json.loads(tools["accept_assignment"].execute(
        title="形成报告",
        objective="形成一份可交付的分析报告",
        acceptance_criteria=["报告文件"],
    ))

    assert "update_assignment_progress" not in tools
    assert "wait_assignment" not in tools
    assert "complete_assignment" not in tools
    assert store.list_runs(accepted["id"]) == []
    assert store.get_assignment(accepted["id"]).status == AssignmentStatus.QUEUED
    store.close()


def test_accept_assignment_queues_isolated_scheduler_immediately(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    agent = FakeAgentInstance(service, FakePurpose())
    scheduler = FakeScheduler()
    agent.assignment_scheduler = scheduler
    tools = _tools(agent)
    accepted = json.loads(tools["accept_assignment"].execute(
        title="后台研究",
        objective="持续研究并形成一份结果报告",
        acceptance_criteria=["结果报告"],
    ))

    assert accepted["status"] == "queued"
    assert accepted["_xiaomei_control"]["type"] == "handoff"
    assert scheduler.submissions == [(
        accepted["id"],
        {
            "trigger_type": "accepted",
            "trigger_actor_id": "xiaomei",
            "priority": 100,
            "checkpoint": {},
        },
    )]
    store.close()


def test_accept_assignment_can_start_in_durable_clarification(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    scheduler = FakeScheduler()
    agent = FakeAgentInstance(service, FakePurpose(), scheduler=scheduler)

    accepted = json.loads(_tools(agent)["accept_assignment"].execute(
        title="制作自我介绍 PPT",
        objective="制作适合具体场景的 PPT",
        acceptance_criteria=["交付 PPTX"],
        clarification_question="这份 PPT 的受众是谁？",
        clarification_choices=["投资人", "客户"],
    ))

    checkpoint = scheduler.submissions[0][1]["checkpoint"]
    assert checkpoint["pending_interaction"] == {
        "reason": "接受委托前仍缺少必要信息",
        "question": "这份 PPT 的受众是谁？",
        "choices": ["投资人", "客户"],
    }
    assert "这份 PPT 的受众是谁" in accepted["_xiaomei_control"]["message"]
    store.close()


def test_accept_assignment_creates_a_real_background_run(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    scheduler = AssignmentScheduler(AssignmentExecutor(
        service,
        agent_id="xiaomei",
        runner=lambda context, control: ExecutionResult(
            status="completed",
            summary="后台交付完成",
        ),
    ))
    agent = FakeAgentInstance(service, FakePurpose(), scheduler=scheduler)
    scheduler.start(recover=False)
    try:
        accepted = json.loads(_tools(agent)["accept_assignment"].execute(
            title="后台生成报告",
            objective="在隔离运行器中生成报告",
            acceptance_criteria=["报告完成"],
        ))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not store.list_runs(accepted["id"]):
            time.sleep(0.01)

        runs = store.list_runs(accepted["id"])
        assert len(runs) == 1
        assert runs[0].trigger_type == "accepted"
        assert runs[0].status == "completed"
        assert store.get_assignment(accepted["id"]).status == AssignmentStatus.COMPLETED
    finally:
        scheduler.stop()
        store.close()


def test_revise_assignment_reopens_same_work_with_fresh_request(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    scheduler = FakeScheduler()
    agent = FakeAgentInstance(
        service,
        FakePurpose(),
        scheduler=scheduler,
    )
    tools = _tools(agent)
    accepted = json.loads(tools["accept_assignment"].execute(
        title="公司介绍 PPT",
        objective="制作公司介绍 PPT",
        acceptance_criteria=["交付 PPTX"],
    ))
    actor = AssignmentActor(ActorType.AGENT, "xiaomei")
    running = service.start(accepted["id"], actor=actor)
    service.update_progress(
        running.id,
        actor=actor,
        summary="旧版本已完成",
        completed_steps=3,
        total_steps=3,
    )
    service.complete(running.id, actor=actor, summary="已交付第一版")

    scheduler.submissions.clear()
    scheduler._submitted_ids.clear()
    agent.core.session_id = "session_revision"
    agent.core.turn_id = "turn_revision"
    agent.core.current_attachments = [{
        "id": "attachment_revision",
        "name": "新Logo.png",
        "mime_type": "image/png",
        "size": 456,
        "kind": "image",
    }]
    revised = json.loads(tools["revise_assignment"].execute(
        assignment_id=accepted["id"],
        revision_request="把封面换成新 Logo，并统一为蓝色主题",
    ))

    current = store.get_assignment(accepted["id"])
    assert revised["id"] == accepted["id"]
    assert "继续修改原来的委托" in revised["_xiaomei_control"]["message"]
    assert current.status == AssignmentStatus.QUEUED
    assert current.completed_steps is None
    assert current.total_steps is None
    assert current.progress_summary == "把封面换成新 Logo，并统一为蓝色主题"
    assert store.list_events(current.id)[-4].event_type == "reopened"
    resources = {
        (item.resource_type, item.resource_key, item.relation)
        for item in store.list_resources(current.id)
    }
    assert ("session", "session_revision", "revision_origin") in resources
    assert ("turn", "turn_revision", "revision_request") in resources
    assert ("attachment", "attachment_revision", "input") in resources
    assert scheduler.submissions == [(
        current.id,
        {
            "trigger_type": "revision",
            "trigger_actor_id": "xiaomei",
            "priority": 100,
            "checkpoint": {
                "revision_request": "把封面换成新 Logo，并统一为蓝色主题",
            },
        },
    )]
    store.close()


def test_resume_waiting_action_requires_and_seals_explicit_decision(tmp_path):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    agent_instance = FakeAgentInstance(service, FakePurpose())
    scheduler = FakeScheduler()
    agent_instance.assignment_scheduler = scheduler
    tools = _tools(agent_instance)
    accepted = json.loads(tools["accept_assignment"].execute(
        title="执行受控命令",
        objective="经明确批准后执行受控命令",
        acceptance_criteria=["命令执行完成"],
    ))
    actor = AssignmentActor(ActorType.AGENT, "xiaomei")
    running = service.start(accepted["id"], actor=actor)
    waiting = service.wait_for_person(
        running.id,
        actor=actor,
        reason="需要批准命令",
    )
    pending = {
        "kind": "action",
        "tool_name": "shell",
        "arguments": {"command": "echo change"},
    }
    store.create_run(AssignmentRun(
        run_id="run_waiting",
        assignment_id=waiting.id,
        status="waiting_person",
        trigger_type="conversation",
        trigger_actor_id="xiaomei",
        checkpoint={"pending_action": pending},
        safe_to_resume=True,
        started_at=1.0,
        updated_at=2.0,
        ended_at=2.0,
    ))
    # Simulate the original queued item having been consumed by the worker.
    scheduler.submissions.clear()
    scheduler._submitted_ids.clear()

    try:
        tools["start_assignment"].execute(
            assignment_id=waiting.id,
            resume_context="可以",
        )
    except ValueError as exc:
        assert "resume_decision" in str(exc)
    else:
        raise AssertionError("ambiguous action response was treated as approval")

    tools["start_assignment"].execute(
        assignment_id=waiting.id,
        resume_context="可以执行这个命令",
        resume_decision="approve",
    )
    submitted = scheduler.submissions[-1][1]["checkpoint"]
    assert submitted["approved_action"] == pending
    assert "pending_action" not in submitted
    store.close()
