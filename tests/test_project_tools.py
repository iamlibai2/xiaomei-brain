from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xiaomei_brain.processes import ProcessService, ProcessStore

from xiaomei_brain.projects import (
    InvalidProjectTransition,
    ProjectActor,
    ProjectActorType,
    ProjectAssetRole,
    ProjectService,
    ProjectStore,
    ProjectWorkspaceManager,
    create_project_tools,
    render_project_context,
)


class FakeAgentInstance:
    def __init__(self, service: ProjectService) -> None:
        self.id = "test"
        self.project_service = service
        self.core = SimpleNamespace(
            user_id="person_1",
            session_id="session_1",
            turn_id="turn_1",
            active_project_id="",
            project_context=None,
            project_service=service,
        )

    def _get_agent(self):
        return self.core


def _tools(agent):
    return {item.name: item for item in create_project_tools(agent)}


def test_create_project_schema_exposes_workspace_enum(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    tool = _tools(FakeAgentInstance(service))["create_project"]
    assert tool.parameters["properties"]["workspace_kind"] == {
        "enum": ["managed", "linked", "virtual"],
        "type": "string",
    }
    service.store.close()


def test_project_step_schema_exposes_only_supported_statuses(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    tool = _tools(FakeAgentInstance(service))["set_project_step"]
    assert tool.parameters["properties"]["status"] == {
        "enum": [
            "pending", "running", "waiting_review", "completed",
            "needs_revision", "skipped",
        ],
        "type": "string",
    }
    service.store.close()


def test_explicit_delivery_standard_requires_real_process_before_steps(tmp_path):
    database = tmp_path / "brain.db"
    projects = ProjectService(
        ProjectStore(database),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    processes = ProcessService(ProcessStore(database), projects)
    projects.set_completion_guard(processes.completion_blocker)
    agent = FakeAgentInstance(projects)
    agent.process_service = processes
    agent.core.process_service = processes
    activated: list[str] = []
    agent.core._dynamic_loader = SimpleNamespace(
        activate_required_tools=lambda names: activated.extend(names),
    )
    agent.core._last_all_messages = [{
        "role": "user",
        "content": "做一个五阶段交付标准的 10 秒 Canvas 视频",
    }]
    tools = _tools(agent)

    created = json.loads(tools["create_project"].execute(
        name="Particle film",
        project_type="video.production",
        summary="10 second particle animation",
    ))

    assert created["process_requirement"] == {
        "required": True,
        "requested_stage_count": 5,
        "status": "must_define_before_project_steps",
    }
    assert set(activated) == {
        "list_project_process_templates",
        "apply_project_process_template",
        "define_project_process",
        "inspect_project_process",
        "submit_process_stage",
    }
    with pytest.raises(ValueError, match="不能代替 Process"):
        tools["set_project_step"].execute(
            project_id=created["id"],
            step_id="brief",
            title="Brief",
        )
    with pytest.raises(InvalidProjectTransition, match="尚未建立 Process"):
        tools["update_project"].execute(
            project_id=created["id"],
            status="completed",
        )

    processes.define(
        created["id"],
        {
            "id": "custom-five",
            "name": "Five-stage delivery",
            "ordered": False,
            "stages": [
                {"id": f"stage-{index}", "title": f"Stage {index}"}
                for index in range(1, 6)
            ],
        },
        actor=ProjectActor(ProjectActorType.AGENT, "test"),
    )
    step = json.loads(tools["set_project_step"].execute(
        project_id=created["id"],
        step_id="brief",
        title="Brief",
    ))
    assert step["step_id"] == "brief"
    processes.store.close()
    projects.store.close()


def test_project_conversation_tools_create_restore_and_update(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    tools = _tools(agent)

    created = json.loads(tools["create_project"].execute(
        name="Launch film",
        project_type="video.production",
        summary="Product launch video",
    ))
    assert agent.core.active_project_id == created["id"]
    assert agent.core.project_context.project_id == created["id"]
    assert service.store.get_session_binding("session_1").project_id == created["id"]

    step = json.loads(tools["set_project_step"].execute(
        project_id=created["id"],
        step_id="storyboard",
        title="Storyboard",
        status="running",
        completed_units=2,
        total_units=8,
    ))
    assert step["status"] == "running"
    completed = json.loads(tools["set_project_step"].execute(
        project_id=created["id"],
        step_id="storyboard",
        status="completed",
    ))
    assert completed["title"] == "Storyboard"
    assert completed["status"] == "completed"
    assert completed["completed_units"] == 2
    listed = json.loads(tools["list_projects"].execute(status="active"))
    assert [item["id"] for item in listed] == [created["id"]]
    inspected = json.loads(tools["inspect_project"].execute(
        project_id=created["id"],
    ))
    assert inspected["steps"][0]["completed_units"] == 2
    rendered = render_project_context(agent.core)
    assert "Launch film" in rendered
    assert "Storyboard" in rendered
    assert str(tmp_path) not in rendered
    service.store.close()


def test_project_review_reconciles_reality_without_enforcing_step_order(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    tools = _tools(agent)
    created = json.loads(tools["create_project"].execute(
        name="Sci-fi film", project_type="video.production",
    ))
    project_id = created["id"]
    service.update(
        project_id,
        actor=ProjectActor(ProjectActorType.AGENT, "test"),
        metadata={"video": {"target_duration": 20, "aspect_ratio": "16:9"}},
    )
    for position, step_id in enumerate((
        "brief", "director", "storyboard", "visual",
        "motion", "audio", "composition", "acceptance",
    ), start=1):
        tools["set_project_step"].execute(
            project_id=project_id,
            step_id=step_id,
            title=step_id,
            status="running" if step_id == "brief" else "pending",
            position=position,
        )
    tools["set_project_step"].execute(
        project_id=project_id, step_id="storyboard", status="waiting_review",
    )
    tools["set_project_step"].execute(
        project_id=project_id, step_id="composition", status="waiting_review",
    )

    result = json.loads(tools["review_project"].execute(
        project_id=project_id,
        review_json=json.dumps({
            "assessment": "The candidate is 17 seconds and intentionally omits audio.",
            "progress_summary": "Candidate needs one missing scene or an agreed scope change.",
            "current_step_id": "motion",
            "waiting_reason": "Waiting for a decision about shot 04.",
            "next_action": "Ask whether to add shot 04 or accept a 17-second cut.",
            "plan_changes": ["Audio is no longer required."],
            "deviations": ["Three of four storyboard scenes are present."],
            "metadata_updates": {"video": {"target_duration": 17}},
            "steps": [
                {"step_id": "brief", "status": "completed", "summary": "Brief confirmed."},
                {"step_id": "director", "status": "completed", "summary": "Direction established."},
                {"step_id": "storyboard", "status": "completed", "summary": "Storyboard approved."},
                {"step_id": "motion", "status": "needs_revision", "reason": "Shot 04 is absent."},
                {"step_id": "audio", "status": "skipped", "reason": "Silent cut accepted."},
                {"step_id": "composition", "status": "needs_revision", "reason": "Duration is 17s, not 20s."},
            ],
        }),
    ))

    assert result["review"]["next_action"].startswith("Ask whether")
    inspected = json.loads(tools["inspect_project"].execute(project_id=project_id))
    statuses = {step["step_id"]: step["status"] for step in inspected["steps"]}
    assert statuses == {
        "brief": "completed",
        "director": "completed",
        "storyboard": "completed",
        "visual": "pending",
        "motion": "needs_revision",
        "audio": "skipped",
        "composition": "needs_revision",
        "acceptance": "pending",
    }
    stored = service.store.get_project(project_id)
    assert stored is not None
    assert stored.current_step_id == "motion"
    assert stored.metadata["last_review"]["deviations"] == [
        "Three of four storyboard scenes are present.",
    ]
    assert stored.metadata["video"] == {
        "target_duration": 17,
        "aspect_ratio": "16:9",
    }

    final_review = json.loads(tools["review_project"].execute(
        project_id=project_id,
        review_json=json.dumps({"assessment": "The user accepted the final cut."}),
    ))
    assert final_review["review"]["plan_changes"] == [
        "Audio is no longer required.",
    ]
    assert final_review["review"]["deviations"] == [
        "Three of four storyboard scenes are present.",
    ]
    step_event_count = sum(
        event.event_type == "step.updated"
        for event in service.store.list_events(project_id)
    )
    tools["review_project"].execute(
        project_id=project_id,
        review_json=json.dumps({
            "assessment": "The completed brief remains valid.",
            "steps": [{"step_id": "brief", "status": "completed"}],
        }),
    )
    assert sum(
        event.event_type == "step.updated"
        for event in service.store.list_events(project_id)
    ) == step_event_count
    assert service.get_step(
        project_id, "brief", actor=ProjectActor(ProjectActorType.AGENT, "test"),
    ).status.value == "completed"
    assert service.store.list_events(project_id)[-1].event_type == "reviewed"
    rendered = render_project_context(agent.core)
    assert "最近复盘" in rendered
    assert "The completed brief remains valid" in rendered
    assert "Three of four storyboard scenes are present" in rendered
    service.store.close()


def test_project_tool_allows_agent_to_complete_with_an_adjustable_map(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    tools = _tools(agent)
    created = json.loads(tools["create_project"].execute(
        name="Launch film", project_type="video.production",
    ))
    tools["set_project_step"].execute(
        project_id=created["id"], step_id="motion", title="Motion",
    )

    tools["update_project"].execute(
        project_id=created["id"],
        status="completed",
        progress_summary="The requested result has been delivered",
    )

    stored = service.store.get_project(created["id"])
    assert stored is not None
    assert stored.status.value == "completed"
    assert stored.progress_summary == "The requested result has been delivered"
    service.store.close()


def test_project_review_does_not_turn_video_facts_into_core_policy(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    tools = _tools(agent)
    created = json.loads(tools["create_project"].execute(
        name="Short film", project_type="video.production",
    ))
    project = service.store.get_project(created["id"])
    output = Path(project.state_root) / "deliverables" / "cut.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"video")
    service.register_asset(
        project.id,
        actor=ProjectActor(ProjectActorType.AGENT, "test"),
        relative_uri="deliverables/cut.mp4",
        role=ProjectAssetRole.DELIVERABLE,
        kind="video",
        metadata={
            "storyboard_duration": 5.0,
            "actual_duration": 3.0,
            "audio_required": True,
            "has_audio": False,
        },
    )

    reviewed = json.loads(tools["review_project"].execute(
        project_id=project.id,
        review_json=json.dumps({"assessment": "Candidate ready for review."}),
    ))

    assert reviewed["review"]["deviations"] == []
    service.store.close()


def test_project_stage_map_can_be_rewritten_without_fake_transitions(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    tools = _tools(agent)
    created = json.loads(tools["create_project"].execute(
        name="Silent cut", project_type="video.production",
    ))
    project_id = created["id"]
    tools["set_project_step"].execute(
        project_id=project_id,
        step_id="audio",
        title="Sound",
        status="completed",
    )
    before = len(service.store.list_events(project_id))
    tools["set_project_step"].execute(
        project_id=project_id,
        step_id="audio",
        status="pending",
        title="Optional sound",
        position=4,
    )
    assert len(service.store.list_events(project_id)) == before + 1
    removed = json.loads(tools["remove_project_step"].execute(
        project_id=project_id,
        step_id="audio",
        reason="The user requested a silent film.",
    ))
    assert removed["removed"] is True
    assert service.store.list_steps(project_id) == []
    assert service.store.list_events(project_id)[-1].event_type == "step.removed"
    service.store.close()


def test_project_tool_does_not_expose_other_person_project(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    first = FakeAgentInstance(service)
    created = json.loads(_tools(first)["create_project"].execute(
        name="Private", project_type="document",
    ))
    second = FakeAgentInstance(service)
    second.core.user_id = "person_2"
    assert json.loads(_tools(second)["list_projects"].execute()) == []
    try:
        _tools(second)["inspect_project"].execute(project_id=created["id"])
    except PermissionError:
        pass
    else:
        raise AssertionError("Another Person must not inspect this Project")
    service.store.close()


def test_create_project_normalizes_model_generated_workspace_alias(tmp_path):
    service = ProjectService(
        ProjectStore(tmp_path / "brain.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    agent = FakeAgentInstance(service)
    created = json.loads(_tools(agent)["create_project"].execute(
        name="Video campaign",
        project_type="video.production",
        workspace_kind="video",
    ))
    assert created["workspace_kind"] == "managed"
    service.store.close()
