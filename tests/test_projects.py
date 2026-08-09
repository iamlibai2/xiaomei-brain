from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xiaomei_brain.projects import (
    InvalidProjectTransition,
    ProjectActor,
    ProjectActorType,
    ProjectAssetRole,
    ProjectConflictError,
    ProjectPermissionError,
    ProjectService,
    ProjectStatus,
    ProjectStepStatus,
    ProjectStore,
    ProjectWorkspaceManager,
    WorkspaceKind,
)
from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentExecutor,
    AssignmentService,
    AssignmentStore,
    ExecutionResult,
)
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _service(tmp_path, *, clock=lambda: 100.0, publish=None):
    store = ProjectStore(tmp_path / "brain.db")
    workspace = ProjectWorkspaceManager(tmp_path / "agent" / "projects")
    return ProjectService(store, workspace, clock=clock, publish=publish)


def test_project_store_adds_only_its_own_tables(tmp_path):
    path = tmp_path / "brain.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
    connection.execute("INSERT INTO messages (content) VALUES ('existing')")
    connection.commit()
    connection.close()

    store = ProjectStore(path)
    assert store._get_schema_version("project_storage") == 1
    assert store._get_conn().execute(
        "SELECT content FROM messages",
    ).fetchone()["content"] == "existing"
    tables = {
        row["name"]
        for row in store._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        ).fetchall()
    }
    assert {
        "projects",
        "project_events",
        "project_steps",
        "project_assets",
        "project_resources",
        "project_sessions",
    }.issubset(tables)
    store.close()


def test_project_lifecycle_revision_and_idempotency(tmp_path):
    service = _service(tmp_path)
    agent = ProjectActor(ProjectActorType.AGENT, "test")
    created = service.create(
        name="Launch film",
        project_type="video-production",
        actor=agent,
        scope_type="person",
        scope_id="person_1",
        idempotency_key="create-1",
    )
    duplicate = service.create(
        name="Ignored duplicate",
        project_type="video-production",
        actor=agent,
        scope_type="person",
        scope_id="person_1",
        idempotency_key="create-1",
    )
    assert duplicate == created
    changed = service.update(
        created.id,
        actor=agent,
        expected_revision=1,
        progress_summary="Storyboard drafted",
        metadata={"execution": {"assignment_required": True}},
    )
    assert changed.revision == 2
    merged = service.update(
        created.id,
        actor=agent,
        expected_revision=2,
        metadata={"video": {"target_duration": 10}},
    )
    assert merged.metadata == {
        "execution": {"assignment_required": True},
        "video": {"target_duration": 10},
    }
    with pytest.raises(ProjectConflictError):
        service.update(
            created.id,
            actor=agent,
            expected_revision=1,
            summary="stale",
        )

    completed = service.transition(
        created.id, ProjectStatus.COMPLETED,
        actor=agent, expected_revision=3,
    )
    assert completed.completed_at == 100.0
    with pytest.raises(InvalidProjectTransition):
        service.transition(completed.id, ProjectStatus.DISCONTINUED, actor=agent)
    service.store.close()


def test_project_steps_recover_creation_order_when_positions_are_corrupted(tmp_path):
    now = [0.0]

    def clock():
        now[0] += 1.0
        return now[0]

    service = _service(tmp_path, clock=clock)
    agent = ProjectActor(ProjectActorType.AGENT, "test")
    project = service.create(
        name="Video",
        project_type="video.production",
        actor=agent,
        scope_type="person",
        scope_id="person_1",
    )
    step_ids = [
        "brief", "director", "storyboard", "visual",
        "motion", "audio", "composition", "acceptance",
    ]
    for position, step_id in enumerate(step_ids, start=1):
        service.put_step(
            project.id,
            actor=agent,
            step_id=step_id,
            title=step_id,
            position=position,
        )

    # Simulate the historical bug where status-only updates reset positions.
    for step_id in ("brief", "director", "storyboard", "visual", "composition", "acceptance"):
        service.put_step(
            project.id,
            actor=agent,
            step_id=step_id,
            title=step_id,
            position=0,
        )

    assert [step.step_id for step in service.store.list_steps(project.id)] == step_ids
    service.store.close()


def test_project_can_complete_when_agent_judges_goal_is_done(tmp_path):
    service = _service(tmp_path)
    agent = ProjectActor(ProjectActorType.AGENT, "test")
    project = service.create(
        name="Launch film",
        project_type="video.production",
        actor=agent,
        scope_type="person",
        scope_id="person_1",
    )
    service.put_step(
        project.id, actor=agent, step_id="motion", title="Motion",
    )
    service.put_step(
        project.id, actor=agent, step_id="audio", title="Audio",
        status=ProjectStepStatus.SKIPPED,
    )

    service.update(
        project.id, actor=agent, current_step_id="motion",
    )
    completed = service.transition(
        project.id, ProjectStatus.COMPLETED, actor=agent,
    )
    assert completed.status is ProjectStatus.COMPLETED
    assert completed.current_step_id == ""
    assert service.get_step(
        project.id, "motion", actor=agent,
    ).status is ProjectStepStatus.PENDING
    service.store.close()


def test_project_person_scope_is_enforced(tmp_path):
    service = _service(tmp_path)
    owner = ProjectActor(ProjectActorType.PERSON, "person_1")
    stranger = ProjectActor(ProjectActorType.PERSON, "person_2")
    project = service.create(
        name="Quarterly report", project_type="document",
        actor=owner, scope_type="person", scope_id="person_1",
    )
    assert service.require_project(project.id, actor=owner) == project
    with pytest.raises(ProjectPermissionError):
        service.require_project(project.id, actor=stranger)
    with pytest.raises(ProjectPermissionError):
        service.create(
            name="Spoofed", project_type="document", actor=stranger,
            scope_type="person", scope_id="person_1",
        )
    service.store.close()


def test_workspace_kinds_do_not_delete_or_take_over_linked_directory(tmp_path):
    manager = ProjectWorkspaceManager(tmp_path / "agent" / "projects")
    managed = manager.prepare("project_managed", kind=WorkspaceKind.MANAGED)
    assert managed.work_root == managed.state_root / "work"
    assert (managed.state_root / "deliverables").is_dir()

    external = tmp_path / "customer-repo"
    external.mkdir()
    marker = external / "owned.txt"
    marker.write_text("customer", encoding="utf-8")
    linked = manager.prepare(
        "project_linked", kind=WorkspaceKind.LINKED,
        workspace_uri=str(external),
    )
    assert linked.work_root == external.resolve()
    assert linked.state_root != external.resolve()
    assert marker.read_text(encoding="utf-8") == "customer"

    virtual = manager.prepare("project_virtual", kind=WorkspaceKind.VIRTUAL)
    assert virtual.work_root is None


def test_project_steps_assets_resources_sessions_and_runtime_context(tmp_path):
    published = []
    service = _service(tmp_path, publish=lambda event, payload: published.append((event, payload)))
    agent = ProjectActor(ProjectActorType.AGENT, "test")
    project = service.create(
        name="Campaign", project_type="video-production", actor=agent,
        scope_type="person", scope_id="person_1",
    )
    step = service.put_step(
        project.id, actor=agent, step_id="storyboard", title="Storyboard",
    )
    assert step.status is ProjectStepStatus.PENDING
    running = service.put_step(
        project.id, actor=agent, step_id="storyboard", title="Storyboard",
        status=ProjectStepStatus.RUNNING,
    )
    assert running.status is ProjectStepStatus.RUNNING

    source = project.state_root + "/source/brief.txt"
    with open(source, "w", encoding="utf-8") as file:
        file.write("brief")
    asset = service.register_asset(
        project.id, actor=agent, relative_uri="source/brief.txt",
        role=ProjectAssetRole.SOURCE, kind="text",
    )
    assert asset.sha256 and asset.size == 5
    resource = service.link_resource(
        project.id, actor=agent, resource_type="assignment",
        resource_key="assignment_1", relation="execution",
    )
    assert resource.resource_key == "assignment_1"
    binding = service.bind_session("session_1", project.id, actor=agent)
    assert service.store.get_session_binding("session_1") == binding

    context = service.runtime_context(
        project.id, actor=agent, active_assignment_id="assignment_1",
    )
    assert context.project_id == project.id
    assert context.allowed_asset_ids == (asset.id,)
    assert published[0][0] == "project.created"
    service.store.close()


def test_project_asset_registration_adds_objective_media_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.projects.service.probe_media_facts",
        lambda _path, _mime: {
            "has_video": True,
            "has_audio": False,
            "duration": 6.0,
            "width": 1280,
            "height": 720,
            "fps": 25.0,
            "video_codec": "h264",
            "media_probe": "ffprobe",
        },
    )
    service = _service(tmp_path)
    actor = ProjectActor(ProjectActorType.AGENT, "test")
    project = service.create(
        name="Silent film", project_type="video.production", actor=actor,
        scope_type="person", scope_id="person_1",
    )
    target = Path(project.state_root) / "deliverables" / "final.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"video")

    asset = service.register_asset(
        project.id,
        actor=actor,
        relative_uri="deliverables/final.mp4",
        role=ProjectAssetRole.DELIVERABLE,
        kind="video",
        metadata={"presented": True, "has_audio": True},
    )

    assert asset.metadata == {
        "presented": True,
        "has_video": True,
        "has_audio": False,
        "duration": 6.0,
        "width": 1280,
        "height": 720,
        "fps": 25.0,
        "video_codec": "h264",
        "media_probe": "ffprobe",
    }
    service.store.close()


def test_delivered_asset_update_preserves_identity_and_filename(tmp_path):
    service = _service(tmp_path)
    actor = ProjectActor(ProjectActorType.AGENT, "test")
    project = service.create(
        name="Interactive demo", project_type="video.production", actor=actor,
        scope_type="person", scope_id="person_1",
    )
    source = tmp_path / "workspace" / "demo.html"
    source.parent.mkdir()
    source.write_text("first", encoding="utf-8")

    first = service.import_delivered_asset(
        project.id, actor=actor, source_path=source, kind="text",
        source_id="artifact_first",
        unified_asset_id="asset_stable",
    )
    source.write_text("second revision", encoding="utf-8")
    second = service.import_delivered_asset(
        project.id, actor=actor, source_path=source, kind="text",
        source_id="artifact_second",
        unified_asset_id="asset_stable",
    )

    assert second.id == first.id
    assert second.name == "demo.html"
    assert second.sha256 != first.sha256
    assert second.source_id == "artifact_second"
    assert second.metadata["logical_name"] == "demo.html"
    assert second.metadata["asset_id"] == "asset_stable"
    assert len(service.store.list_assets(project.id)) == 1
    delivered = Path(project.state_root) / second.relative_uri
    assert delivered.read_text(encoding="utf-8") == "second revision"
    assert service.store.list_events(project.id)[-1].event_type == "asset.updated"
    service.store.close()


def test_project_context_reaches_assignment_runner_and_tool_boundary(tmp_path):
    project_service = _service(tmp_path)
    project_actor = ProjectActor(ProjectActorType.AGENT, "test")
    project = project_service.create(
        name="Campaign", project_type="video.production",
        actor=project_actor, scope_type="person", scope_id="person_1",
    )
    assignment_service = AssignmentService(AssignmentStore(tmp_path / "brain.db"))
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent = AssignmentActor(ActorType.AGENT, "test")
    assignment = assignment_service.offer(
        title="Render sample", objective="Create one review sample",
        actor=person, requester_person_id="person_1",
        scope_type="project", scope_id=project.id,
    )
    assignment = assignment_service.accept(assignment.id, actor=agent)
    assignment_service.queue(assignment.id, actor=agent)

    captured = []

    def runner(context, _control):
        captured.append(context)
        with bind_tool_execution(
            tool_call_id="call_1", tool_name="write", arguments={},
            artifact_callback=None, project_context=context.project_context,
        ) as tool_context:
            assert tool_context.project_context.project_id == project.id
        return ExecutionResult(status="completed", summary="done")

    executor = AssignmentExecutor(
        assignment_service,
        agent_id="test",
        runner=runner,
        project_service=project_service,
    )
    executor.execute(
        assignment.id, trigger_type="test", trigger_actor_id="person_1",
    )
    assert captured[0].project_context.project_id == project.id
    assert captured[0].project_context.active_assignment_id == assignment.id
    assignment_service.store.close()
    project_service.store.close()
