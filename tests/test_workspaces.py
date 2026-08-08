from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from xiaomei_brain.workspaces import (
    WorkspaceConflictError,
    WorkspacePermissionError,
    WorkspaceService,
    WorkspaceStore,
    create_workspace_tools,
)


def _surface(value: int = 12):
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


def test_workspace_and_surface_are_independent_and_revisioned(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    events = []
    service = WorkspaceService(
        store,
        publish=lambda name, payload, **metadata: events.append((name, payload, metadata)),
        clock=lambda: 10.0,
    )
    created = service.create(
        name="销售业务",
        purpose="持续管理客户、报价和回款",
        description="从第一位客户开始",
        created_by_person_id="person-1",
        default_surface_definition=_surface(),
        session_id="session-1",
        turn_id="turn-1",
    )
    surfaces = store.list_surfaces(created.id)
    assert created.revision == 1
    assert surfaces[0].definition["components"][0]["value"] == 12
    assert events[0][0] == "workspace.created"
    assert events[0][1]["_target_person_id"] == "person-1"

    changed = service.update(
        created.id,
        purpose="管理客户经营全周期",
        expected_revision=1,
    )
    assert changed.revision == 2
    assert store.get_surface(surfaces[0].id).revision == 1
    changed_surface = service.surfaces.update(
        surfaces[0].id,
        definition=_surface(20),
        expected_revision=1,
    )
    assert changed_surface.revision == 2
    assert service.require(created.id).purpose == "管理客户经营全周期"
    with pytest.raises(WorkspaceConflictError):
        service.update(created.id, name="冲突", expected_revision=1)
    with pytest.raises(WorkspacePermissionError):
        service.require_for_person(created.id, person_id="person-2")


def test_workspace_can_start_without_surface_but_surface_is_validated(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    workspace = service.create(
        name="新业务", purpose="观察一项刚开始的业务",
        created_by_person_id="person-1",
    )
    assert service.store.list_surfaces(workspace.id) == []
    with pytest.raises(ValueError, match="at least one"):
        service.surfaces.create(
            workspace.id, name="空界面", purpose="", definition={"components": []},
        )
    with pytest.raises(ValueError, match="Unsupported"):
        service.surfaces.create(
            workspace.id,
            name="代码",
            purpose="",
            definition={"components": [{"type": "arbitrary_html"}]},
        )


def test_workspace_tools_use_person_as_provenance_not_agent_ownership(tmp_path):
    service = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    core = SimpleNamespace(user_id="person-1", session_id="session-1", turn_id="turn-1")
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}

    created = tools["create_workspace"].execute(
        name="经营业务",
        purpose="管理持续经营信息",
        initial_surface=_surface(),
    )
    surface_id = created["surfaces"][0]["id"]
    updated = tools["update_surface"].execute(
        surface_id=surface_id,
        definition=_surface(99),
        expected_revision=1,
    )
    assert updated["revision"] == 2
    assert updated["definition"]["components"][0]["value"] == 99
    assert tools["list_workspaces"].execute()["workspaces"][0]["id"] == created["id"]


def test_conversation_workspace_focus_persists_and_is_person_scoped(tmp_path):
    db_path = tmp_path / "workspaces.db"
    service = WorkspaceService(WorkspaceStore(db_path))
    core = SimpleNamespace(
        user_id="person-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {item.name: item for item in create_workspace_tools(agent)}
    created = tools["create_workspace"].execute(
        name="客户经营",
        purpose="持续推进客户",
    )

    current = tools["get_current_workspace"].execute()
    assert current["focused"] is True
    assert current["workspace"]["id"] == created["id"]
    assert tools["list_workspaces"].execute()["focused_workspace_id"] == created["id"]

    reopened = WorkspaceService(WorkspaceStore(db_path))
    assert reopened.current_for_session(
        "session-1",
        person_id="person-1",
    ).id == created["id"]
    assert reopened.current_for_session(
        "session-1",
        person_id="person-2",
    ) is None


def test_workspace_schema_upgrade_calls_backup_before_adding_session_focus(tmp_path):
    db_path = tmp_path / "workspaces.db"
    store = WorkspaceStore(db_path)
    store.create(
        name="客户经营",
        purpose="持续推进客户",
        description="",
        created_reason="test",
        created_by_person_id="person-1",
    )
    store.close()
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE workspace_session_focus")
    conn.execute(
        "UPDATE schema_versions SET version = 2 WHERE component = 'workspaces'",
    )
    conn.commit()
    conn.close()
    backups = []

    WorkspaceStore(
        db_path,
        before_schema_migration=lambda: backups.append("backup"),
    )

    assert backups == ["backup"]
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workspace_session_focus'",
    ).fetchone() is not None
    conn.close()


def test_legacy_brain_workspace_is_imported_once_after_backup(tmp_path):
    brain_db = tmp_path / "brain.db"
    conn = sqlite3.connect(brain_db)
    conn.executescript("""
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
            spec_json TEXT NOT NULL, revision INTEGER NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "workspace_old", "旧经营看板", "旧说明", "person", "person-1",
            json.dumps(_surface(), ensure_ascii=False), 3, 1.0, 2.0,
        ),
    )
    conn.commit()
    conn.close()
    backups = []
    workspace_db = tmp_path / "workspaces" / "workspaces.db"

    store = WorkspaceStore(
        workspace_db,
        legacy_db_path=brain_db,
        before_legacy_migration=lambda: backups.append("backup"),
    )
    imported = store.get("workspace_old")
    assert backups == ["backup"]
    assert imported is not None
    assert imported.purpose == "旧说明"
    assert store.person_is_linked(imported.id, "person-1")
    assert store.default_surface(imported.id).definition["components"][0]["title"] == "销售额"

    WorkspaceStore(
        workspace_db,
        legacy_db_path=brain_db,
        before_legacy_migration=lambda: backups.append("again"),
    )
    assert backups == ["backup"]
