from __future__ import annotations

from types import SimpleNamespace

import pytest

from xiaomei_brain.workspaces import (
    WorkspaceConflictError,
    WorkspacePermissionError,
    WorkspaceService,
    WorkspaceStore,
    create_workspace_tools,
)


def _spec(value: int = 12):
    return {
        "components": [
            {"id": "sales", "type": "metric", "title": "销售额", "value": value},
            {
                "id": "regions",
                "type": "bar_chart",
                "title": "区域对比",
                "data": [{"label": "华东", "value": value}],
            },
        ],
    }


def test_workspace_persists_updates_and_checks_revision(tmp_path):
    store = WorkspaceStore(tmp_path / "brain.db")
    events = []
    service = WorkspaceService(
        store,
        publish=lambda name, payload, **metadata: events.append((name, payload, metadata)),
        clock=lambda: 10.0,
    )
    created = service.create(
        name="销售工作台",
        description="季度销售",
        scope_type="person",
        scope_id="person-1",
        spec=_spec(),
        session_id="session-1",
        turn_id="turn-1",
    )
    assert created.revision == 1
    assert store.get(created.id).spec["components"][0]["value"] == 12
    assert events[0][0] == "workspace.created"
    assert events[0][1]["_target_person_id"] == "person-1"

    changed = service.update(
        created.id,
        person_id="person-1",
        spec=_spec(20),
        expected_revision=1,
    )
    assert changed.revision == 2
    assert changed.spec["components"][0]["value"] == 20
    with pytest.raises(WorkspaceConflictError):
        service.update(
            created.id,
            person_id="person-1",
            spec=_spec(30),
            expected_revision=1,
        )
    with pytest.raises(WorkspacePermissionError):
        service.require(created.id, person_id="person-2")


def test_workspace_rejects_unknown_or_empty_components(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "brain.db"))
    with pytest.raises(ValueError, match="at least one"):
        service.create(
            name="Empty", description="", scope_type="person", scope_id="person-1",
            spec={"components": []},
        )
    with pytest.raises(ValueError, match="Unsupported"):
        service.create(
            name="Code", description="", scope_type="person", scope_id="person-1",
            spec={"components": [{"type": "arbitrary_html"}]},
        )


def test_workspace_tools_use_current_verified_person(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "brain.db"))
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(
        workspace_service=service,
        _get_agent=lambda: core,
    )
    tools = {item.name: item for item in create_workspace_tools(agent)}
    created = tools["create_workspace"].execute(
        name="经营工作台", description="经营概览", spec=_spec(),
    )
    listed = tools["list_workspaces"].execute()
    assert listed["workspaces"][0]["id"] == created["id"]
    inspected = tools["get_workspace"].execute(workspace_id=created["id"])
    assert inspected["scope_id"] == "person-1"
    updated = tools["update_workspace"].execute(
        workspace_id=created["id"], spec=_spec(99), expected_revision=1,
    )
    assert updated["revision"] == 2
    assert updated["spec"]["components"][0]["value"] == 99
