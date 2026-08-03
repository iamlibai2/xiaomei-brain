from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from xiaomei_brain.processes import (
    ProcessService,
    ProcessStatus,
    ProcessStore,
    ProcessTemplateRegistry,
    create_process_tools,
    render_process_context,
)
from xiaomei_brain.projects import (
    InvalidProjectTransition,
    ProjectActor,
    ProjectActorType,
    ProjectAssetRole,
    ProjectService,
    ProjectStatus,
    ProjectStore,
    ProjectWorkspaceManager,
)


def _services(tmp_path):
    db_path = tmp_path / "brain.db"
    projects = ProjectService(
        ProjectStore(db_path),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    processes = ProcessService(ProcessStore(db_path), projects)
    projects.set_completion_guard(processes.completion_blocker)
    return projects, processes


def _project(projects):
    actor = ProjectActor(ProjectActorType.AGENT, "test")
    project = projects.create(
        name="Silent film",
        project_type="video.production",
        actor=actor,
        scope_type="person",
        scope_id="person_1",
    )
    return actor, project


def _definition(*, ordered=False):
    return {
        "id": "silent-fast",
        "name": "默片交付标准",
        "ordered": ordered,
        "stages": [
            {
                "id": "brief",
                "title": "作品定义",
                "requirements": [
                    {"type": "asset", "kind": "brief", "label": "需求简报"},
                ],
            },
            {
                "id": "delivery",
                "title": "成片交付",
                "requirements": [
                    {
                        "type": "asset",
                        "kind": "video",
                        "role": "deliverable",
                        "label": "最终视频",
                    },
                    {
                        "type": "evidence",
                        "key": "has_video",
                        "from_asset": True,
                        "equals": True,
                        "label": "有效视频流",
                    },
                    {
                        "type": "evidence",
                        "key": "has_audio",
                        "from_asset": True,
                        "equals": False,
                        "label": "默片无音轨",
                    },
                ],
            },
        ],
    }


def _asset(projects, project, actor, name, kind, role, metadata=None):
    path = project.state_root + "/" + name
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"data")
    return projects.register_asset(
        project.id,
        actor=actor,
        relative_uri=name,
        name=target.name,
        kind=kind,
        role=role,
        metadata=metadata,
    )


def test_process_requires_declared_submissions_but_not_work_order(tmp_path):
    projects, processes = _services(tmp_path)
    actor, project = _project(projects)
    process = processes.define(project.id, _definition(), actor=actor)
    brief = _asset(
        projects, project, actor, "work/script/brief.json", "brief",
        ProjectAssetRole.WORKING,
    )
    wrong_video = _asset(
        projects, project, actor, "deliverables/with-audio.mp4", "video",
        ProjectAssetRole.DELIVERABLE,
        {"has_video": True, "has_audio": True},
    )

    incomplete = processes.submit(
        project.id,
        "delivery",
        actor=actor,
        asset_ids=[wrong_video.id],
        # Self-reported evidence cannot override facts registered on the asset.
        evidence={"has_video": True, "has_audio": False},
    )
    assert incomplete.complete is False
    assert any("默片无音轨" in item for item in incomplete.missing)
    assert processes.store.get_for_project(project.id).status is ProcessStatus.ACTIVE

    video = _asset(
        projects, project, actor, "deliverables/silent.mp4", "video",
        ProjectAssetRole.DELIVERABLE,
        {"has_video": True, "has_audio": False},
    )
    delivery = processes.submit(
        project.id,
        "delivery",
        actor=actor,
        asset_ids=[video.id],
        evidence={"has_video": True, "has_audio": False},
    )
    assert delivery.complete is True
    assert processes.store.get_for_project(project.id).status is ProcessStatus.ACTIVE

    submitted_brief = processes.submit(
        project.id,
        "brief",
        actor=actor,
        asset_ids=[brief.id],
    )
    assert submitted_brief.complete is True
    satisfied = processes.store.get_for_project(project.id)
    assert satisfied.status is ProcessStatus.SATISFIED
    assert satisfied.satisfied_at is not None
    processes.store.close()
    projects.store.close()


def test_ordered_process_blocks_formal_submission_not_agent_work(tmp_path):
    projects, processes = _services(tmp_path)
    actor, project = _project(projects)
    processes.define(project.id, _definition(ordered=True), actor=actor)
    video = _asset(
        projects, project, actor, "deliverables/final.mp4", "video",
        ProjectAssetRole.DELIVERABLE,
        {"has_video": True, "has_audio": False},
    )
    with pytest.raises(ValueError, match="作品定义"):
        processes.submit(
            project.id,
            "delivery",
            actor=actor,
            asset_ids=[video.id],
            evidence={"has_video": True, "has_audio": False},
        )
    # The Process service did not prevent creating or inspecting the video;
    # it only rejected the out-of-order formal submission.
    assert video.id
    processes.store.close()
    projects.store.close()


def test_active_process_blocks_project_completion_until_submissions_satisfy_it(tmp_path):
    projects, processes = _services(tmp_path)
    actor, project = _project(projects)
    processes.define(project.id, _definition(), actor=actor)

    with pytest.raises(InvalidProjectTransition, match="Process 尚未满足"):
        projects.transition(
            project.id,
            ProjectStatus.COMPLETED,
            actor=actor,
        )

    brief = _asset(
        projects, project, actor, "work/script/brief.json", "brief",
        ProjectAssetRole.WORKING,
    )
    video = _asset(
        projects, project, actor, "deliverables/silent.mp4", "video",
        ProjectAssetRole.DELIVERABLE,
        {"has_video": True, "has_audio": False},
    )
    processes.submit(project.id, "brief", actor=actor, asset_ids=[brief.id])
    processes.submit(project.id, "delivery", actor=actor, asset_ids=[video.id])

    completed = projects.transition(
        project.id,
        ProjectStatus.COMPLETED,
        actor=actor,
    )
    assert completed.status is ProjectStatus.COMPLETED
    processes.store.close()
    projects.store.close()


class _FakeAgent:
    def __init__(self, processes):
        self.id = "test"
        self.process_service = processes
        self.core = SimpleNamespace(
            user_id="person_1",
            active_project_id="",
            process_service=processes,
        )

    def _get_agent(self):
        return self.core


def _write_template(root, definition):
    import yaml

    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{definition['id']}.yaml"
    path.write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "description": "test template",
            "project_types": ["video.production"],
            **definition,
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_process_tools_and_context_keep_contract_separate_from_plan(tmp_path):
    projects, processes = _services(tmp_path)
    _actor, project = _project(projects)
    agent = _FakeAgent(processes)
    agent.core.active_project_id = project.id
    tools = {item.name: item for item in create_process_tools(agent)}
    defined = json.loads(tools["define_project_process"].execute(
        project_id=project.id,
        process_json=json.dumps(_definition(), ensure_ascii=False),
    ))
    assert defined["name"] == "默片交付标准"
    assert defined["stages"][0]["status"] == "pending"
    context = render_process_context(agent.core)
    assert "约束必须提交的结果，不规定你如何思考或执行" in context
    assert "作品定义" in context
    processes.store.close()
    projects.store.close()


def test_process_template_is_listed_and_applied_without_model_rewriting(tmp_path):
    projects, processes = _services(tmp_path)
    _actor, project = _project(projects)
    template_root = tmp_path / "processes"
    _write_template(template_root, _definition(ordered=True))
    agent = _FakeAgent(processes)
    agent._process_template_registry = ProcessTemplateRegistry([template_root])
    tools = {item.name: item for item in create_process_tools(agent)}

    templates = json.loads(tools["list_project_process_templates"].execute(
        project_id=project.id,
    ))
    applied = json.loads(tools["apply_project_process_template"].execute(
        project_id=project.id,
        template_id="silent-fast",
    ))

    assert templates["templates"] == [{
        "id": "silent-fast",
        "name": _definition()["name"],
        "description": "test template",
        "project_types": ["video.production"],
        "tags": [],
        "stage_count": 2,
    }]
    assert applied["definition_id"] == "silent-fast"
    assert applied["ordered"] is True
    assert [stage["id"] for stage in applied["stages"]] == ["brief", "delivery"]
    processes.store.close()
    projects.store.close()
