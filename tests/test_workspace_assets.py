from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore, create_workspace_tools


def _service(tmp_path):
    events = []
    service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        publish=lambda name, payload, **metadata: events.append(
            (name, payload, metadata)
        ),
    )
    workspace = service.create(
        name="客户经营",
        purpose="持续经营客户",
        created_by_person_id="person-1",
    )
    service.focus_session(
        workspace.id,
        session_id="session-1",
        person_id="person-1",
        turn_id="turn-focus",
    )
    return service, workspace, events


def _artifact(
    *,
    artifact_id: str = "a" * 32,
    session_id: str = "session-1",
    turn_id: str = "turn-1",
    relative_path: str = "workspace/outputs/quote.docx",
    size: int = 7,
    updated: bool = False,
):
    return {
        "id": artifact_id,
        "session_id": session_id,
        "name": "报价方案.docx",
        "mime_type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "size": size,
        "kind": "document",
        "description": "Created by write_document",
        "tool_call_id": "tool-1",
        "turn_id": turn_id,
        "relative_path": relative_path,
        "presented": True,
        "updated": updated,
    }


def test_conversation_artifact_gets_stable_asset_identity_and_revision(tmp_path):
    service, workspace, events = _service(tmp_path)
    original_hash = hashlib.sha256(b"initial").hexdigest()
    first = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=original_hash,
    )
    duplicate = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=original_hash,
    )
    changed = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(
            artifact_id="b" * 32,
            session_id="session-2",
            turn_id="turn-2",
            size=8,
            updated=True,
        ),
        sha256=hashlib.sha256(b"revision").hexdigest(),
    )

    assert duplicate.id == first.id
    assert duplicate.revision == 1
    assert changed.id == first.id
    assert changed.revision == 2
    assert changed.source_type == "agent_working_file"
    assert changed.source_session_id == ""
    assert changed.metadata["latest_artifact_id"] == "b" * 32
    assert service.assets.store.is_linked(first.id, workspace.id)
    assert [name for name, _payload, _metadata in events].count(
        "workspace_asset.created"
    ) == 1
    assert [name for name, _payload, _metadata in events].count(
        "workspace_asset.updated"
    ) == 1

    reopened = WorkspaceService(WorkspaceStore(tmp_path / "workspaces.db"))
    restored = reopened.assets.store.get(first.id)
    assert restored is not None
    assert restored.revision == 2
    assert restored.sha256 == hashlib.sha256(b"revision").hexdigest()


def test_same_name_at_different_working_paths_creates_distinct_assets(tmp_path):
    service, workspace, _events = _service(tmp_path)
    first = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(relative_path="workspace/outputs/first/quote.docx"),
        sha256=hashlib.sha256(b"first").hexdigest(),
    )
    second = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(
            artifact_id="b" * 32,
            relative_path="workspace/outputs/second/quote.docx",
        ),
        sha256=hashlib.sha256(b"second").hexdigest(),
    )

    assert second.id != first.id


def test_evidence_freezes_one_working_revision_without_overwrite(tmp_path):
    service, workspace, _events = _service(tmp_path)
    working = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=hashlib.sha256(b"signed-v1").hexdigest(),
    )
    evidence = service.assets.preserve_as_evidence(
        workspace.id,
        working.id,
        person_id="person-1",
        reason="报价已发送给客户",
        session_id="session-1",
        turn_id="turn-evidence",
    )
    duplicate = service.assets.preserve_as_evidence(
        workspace.id,
        working.id,
        person_id="person-1",
        reason="重复请求不应改写原因",
        session_id="session-1",
        turn_id="turn-duplicate",
    )
    service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(
            artifact_id="b" * 32,
            turn_id="turn-2",
            size=9,
            updated=True,
        ),
        sha256=hashlib.sha256(b"working-v2").hexdigest(),
    )

    assert evidence.id == duplicate.id
    assert evidence.nature == "evidence"
    assert evidence.revision == 1
    assert evidence.sha256 == hashlib.sha256(b"signed-v1").hexdigest()
    assert evidence.metadata["reason"] == "报价已发送给客户"
    _item, source_kind, source_session, source_id = (
        service.assets.content_reference(
            evidence.id,
            workspace.id,
            person_id="person-1",
        )
    )
    assert source_kind == "artifact_snapshot"
    assert source_session == "session-1"
    assert source_id == "a" * 32
    assert service.assets.store.has_link(
        evidence.id,
        workspace.id,
        entity_type="asset",
        entity_id=working.id,
        relation="evidence_of",
    )


def test_workspace_asset_snapshot_and_tool_respect_person_boundary(tmp_path):
    service, workspace, _events = _service(tmp_path)
    asset = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=hashlib.sha256(b"initial").hexdigest(),
    )
    snapshot = service.snapshot(workspace, include_business=True)
    assert snapshot["business"]["assets"][0]["id"] == asset.id
    assert "relative_path" not in snapshot["business"]["assets"][0]

    core = SimpleNamespace(
        user_id="person-1", session_id="session-1", turn_id="turn-2",
    )
    agent = SimpleNamespace(workspace_service=service, _get_agent=lambda: core)
    tools = {tool.name: tool for tool in create_workspace_tools(agent)}
    listed = tools["list_workspace_assets"].execute()
    assert listed["assets"][0]["id"] == asset.id

    with pytest.raises(PermissionError, match="current Person"):
        service.assets.register_artifact(
            workspace.id,
            person_id="person-2",
            session_id="session-2",
            artifact={**_artifact(), "session_id": "session-2"},
            sha256=hashlib.sha256(b"other").hexdigest(),
        )


def test_asset_reference_requires_workspace_link_and_returns_latest_artifact(tmp_path):
    service, workspace, _events = _service(tmp_path)
    asset = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=hashlib.sha256(b"initial").hexdigest(),
    )

    item, source_kind, source_session_id, artifact_id = (
        service.assets.content_reference(
            asset.id,
            workspace.id,
            person_id="person-1",
        )
    )

    assert item.id == asset.id
    assert source_kind == "artifact"
    assert source_session_id == "session-1"
    assert artifact_id == "a" * 32
    with pytest.raises(PermissionError, match="current Person"):
        service.assets.content_reference(
            asset.id,
            workspace.id,
            person_id="person-2",
        )


def test_conversation_attachment_becomes_readable_asset_reference(tmp_path):
    service, workspace, _events = _service(tmp_path)
    asset = service.assets.register_attachment(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        attachment={
            "id": "attachment-1",
            "name": "customers.csv",
            "kind": "document",
            "mime_type": "text/csv",
            "size": 12,
        },
        sha256=hashlib.sha256(b"name,revenue").hexdigest(),
    )

    item, source_kind, session_id, attachment_id = (
        service.assets.content_reference(
            asset.id,
            workspace.id,
            person_id="person-1",
        )
    )
    assert item.id == asset.id
    assert source_kind == "attachment"
    assert session_id == "session-1"
    assert attachment_id == "attachment-1"


def test_driver_registers_message_attachment_in_focused_workspace(tmp_path):
    service, workspace, _events = _service(tmp_path)
    source = tmp_path / "customers.csv"
    source.write_text("name,revenue\nAcme,100", encoding="utf-8")
    attachment = {
        "id": "attachment-1",
        "name": "customers.csv",
        "kind": "document",
        "mime_type": "text/csv",
        "size": source.stat().st_size,
        "local_path": str(source),
    }
    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = SimpleNamespace(
        agent=SimpleNamespace(workspace_service=service),
    )

    message = LivingMessage(
        content="导入客户",
        user_id="person-1",
        session_id="session-1",
        attachments=[attachment],
    )
    asset_ids = driver._register_message_assets(message)
    observation_id = driver._register_message_observation(message, asset_ids)

    assets = service.assets.store.list_for_workspace(workspace.id)
    assert len(assets) == 1
    assert assets[0].source_type == "conversation_attachment"
    assert attachment["workspace_asset_id"] == assets[0].id
    observation = service.business.store.get_observation(observation_id)
    assert observation is not None
    assert observation.content == "导入客户"
    assert observation.asset_id == assets[0].id
    assert observation.attributes["attachment_asset_ids"] == [assets[0].id]
    assert service.assets.store.has_link(
        assets[0].id,
        workspace.id,
        entity_type="observation",
        entity_id=observation.id,
        relation="observed_with",
    )


def test_driver_reuses_asset_when_existing_artifact_is_referenced(tmp_path):
    service, workspace, _events = _service(tmp_path)
    asset = service.assets.register_artifact(
        workspace.id,
        person_id="person-1",
        session_id="session-1",
        artifact=_artifact(),
        sha256=hashlib.sha256(b"initial").hexdigest(),
    )
    attachment = {
        "id": "prepared-artifact",
        "name": "报价方案.docx",
        "kind": "document",
        "source_artifact": {
            "artifact_id": "a" * 32,
            "session_id": "session-1",
            "workspace_asset_id": asset.id,
        },
    }
    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = SimpleNamespace(
        agent=SimpleNamespace(workspace_service=service),
    )

    driver._register_message_assets(LivingMessage(
        content="继续修改",
        user_id="person-1",
        session_id="session-1",
        attachments=[attachment],
    ))

    assets = service.assets.store.list_for_workspace(workspace.id)
    assert [item.id for item in assets] == [asset.id]
    assert attachment["workspace_asset_id"] == asset.id


def test_channel_message_becomes_idempotent_observation_with_real_origin(tmp_path):
    service, workspace, _events = _service(tmp_path)
    db = ConversationDB(tmp_path / "brain.db")
    message_id = db.log(
        session_id="session-1",
        role="user",
        content="客户确认接受报价",
        user_id="person-1",
        metadata={
            "channel": "feishu",
            "external_message_id": "om_123",
            "external_timestamp": 1_786_000_000_000,
            "external_subject": "oc_customer_group",
        },
    )
    driver = ConversationDriver.__new__(ConversationDriver)
    driver._parent = SimpleNamespace(
        agent=SimpleNamespace(
            workspace_service=service,
            conversation_db=db,
        ),
    )
    message = LivingMessage(
        content="客户确认接受报价",
        user_id="person-1",
        session_id="session-1",
        turn_id="turn-channel",
        message_id=message_id,
    )

    first_id = driver._register_message_observation(message, [])
    duplicate_id = driver._register_message_observation(message, [])

    assert duplicate_id == first_id
    sources = service.business.store.list_data_sources(workspace.id)
    assert len(sources) == 1
    assert sources[0].kind == "channel"
    assert sources[0].locator == "channel:feishu:session:session-1"
    observations = service.business.store.list_observations(workspace.id)
    assert len(observations) == 1
    assert observations[0].external_ref == "external:om_123"
    assert observations[0].occurred_at == 1_786_000_000
    assert observations[0].attributes["external_subject"] == "oc_customer_group"
    db.close()


def test_asset_schema_upgrade_requests_backup_for_existing_workspace(tmp_path):
    service, workspace, _events = _service(tmp_path)
    conn = service.assets.store._get_conn()
    conn.executescript("""
        DROP TABLE asset_links;
        DROP TABLE assets;
        DELETE FROM schema_versions WHERE component = 'workspace_assets';
    """)
    conn.commit()
    service.assets.store.close()

    backups = []
    reopened = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        before_business_migration=lambda: backups.append("backup"),
    )

    assert backups == ["backup"]
    assert reopened.assets.store.list_for_workspace(workspace.id) == []
