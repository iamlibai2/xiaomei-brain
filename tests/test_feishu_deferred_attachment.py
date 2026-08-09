from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.plugins.channels.feishu.deferred_attachment import (
    create_fetch_group_attachment_tool,
)
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.tools.dynamic import _contextual_required_tool_names
from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore


def test_remote_group_attachment_guarantees_fetch_tool_selection():
    required = _contextual_required_tool_names(
        "<group_observations>remote_group_attachment "
        "ref=feishu_om-file-1 name=quote.xlsx</group_observations>"
    )
    assert "fetch_group_attachment" in required


def test_feishu_group_attachment_downloads_only_when_tool_is_called(
    tmp_path,
    monkeypatch,
):
    from xiaomei_brain.gateway import attachments as attachment_module

    monkeypatch.setattr(
        attachment_module.Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    db = ConversationDB(tmp_path / "brain.db")
    db.log_group_message(
        session_id="feishu-group-demo",
        channel="feishu",
        issuer="feishu:app:demo",
        external_message_id="om-file-1",
        external_subject="ou-1",
        display_name="Alice",
        content="[file: quote.txt]",
        message_type="file",
        metadata={
            "remote_attachment": {
                "id": "feishu_om-file-1",
                "channel": "feishu",
                "account_id": "default",
                "message_id": "om-file-1",
                "resource_key": "file-key-1",
                "resource_type": "file",
                "message_type": "file",
                "name": "quote.txt",
                "status": "remote",
            },
        },
    )

    downloads = []

    class Channel:
        account_id = "default"

        def download_message_resource(self, message_id, resource_key, **kwargs):
            downloads.append((message_id, resource_key, kwargs))
            return "quote total: 1200".encode()

    core = SimpleNamespace(current_attachments=[])
    agent = SimpleNamespace(
        conversation_db=db,
        _get_agent=lambda: core,
    )
    adapter = SimpleNamespace(
        _living=SimpleNamespace(agent=agent, _agent_id="test"),
        _channel=Channel(),
        _detect_image_format=lambda _data: (".jpg", "image/jpeg"),
    )
    tool = create_fetch_group_attachment_tool(adapter)

    def execute():
        with bind_tool_execution(
            tool_call_id="call-1",
            tool_name=tool.name,
            arguments={"attachment_ref": "feishu_om-file-1"},
            artifact_callback=None,
            session_id="feishu-group-demo",
            person_id="person-1",
        ):
            return tool.execute(attachment_ref="feishu_om-file-1")

    assert downloads == []
    first = execute()
    second = execute()

    assert first["attachment"]["kind"] == "text"
    assert first["attachment"]["id"] == "feishu_om-file-1"
    assert second["attachment"]["id"] == "feishu_om-file-1"
    assert len(downloads) == 1
    assert len(core.current_attachments) == 1
    assert Path(core.current_attachments[0]["local_path"]).is_file()
    stored = db.find_group_attachments(
        "feishu-group-demo",
        "feishu_om-file-1",
    )[0]
    assert stored["materialized_attachment"]["id"] == "feishu_om-file-1"
    db.close()


def test_materialized_group_attachment_becomes_workspace_asset_and_observation(
    tmp_path,
    monkeypatch,
):
    from xiaomei_brain.gateway import attachments as attachment_module

    monkeypatch.setattr(
        attachment_module.Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    session_id = "feishu-group-workspace"
    person_id = "person-1"
    db = ConversationDB(tmp_path / "brain.db")
    workspace_service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
    )
    workspace = workspace_service.create(
        name="客户经营",
        purpose="沉淀客户群中的业务事实",
        created_by_person_id=person_id,
    )
    workspace_service.focus_session(
        workspace.id,
        session_id=session_id,
        person_id=person_id,
    )
    source = workspace_service.business.create_data_source(
        workspace.id,
        kind="channel",
        name="feishu group conversation",
        locator=f"channel:feishu:session:{session_id}",
    )
    observation = workspace_service.business.observe(
        workspace.id,
        content="[file: customer-list.csv]",
        data_source_id=source.id,
        external_ref="external:om-file-workspace",
        attributes={
            "channel": "feishu",
            "group": True,
            "remote_attachment": {
                "id": "feishu_om-file-workspace",
                "name": "customer-list.csv",
                "status": "remote",
            },
        },
        session_id=session_id,
    )
    group_message_id = db.log_group_message(
        session_id=session_id,
        channel="feishu",
        issuer="feishu:app:demo",
        external_message_id="om-file-workspace",
        external_subject="ou-1",
        display_name="Alice",
        content="[file: customer-list.csv]",
        message_type="file",
        metadata={
            "workspace_observation_id": observation.id,
            "remote_attachment": {
                "id": "feishu_om-file-workspace",
                "channel": "feishu",
                "account_id": "default",
                "message_id": "om-file-workspace",
                "resource_key": "file-key-workspace",
                "resource_type": "file",
                "message_type": "file",
                "name": "customer-list.csv",
                "status": "remote",
            },
        },
    )

    class Channel:
        account_id = "default"

        @staticmethod
        def download_message_resource(*_args, **_kwargs):
            return "name,amount\nAlice,1200\n".encode()

    core = SimpleNamespace(current_attachments=[])
    agent = SimpleNamespace(
        conversation_db=db,
        workspace_service=workspace_service,
        _get_agent=lambda: core,
    )
    adapter = SimpleNamespace(
        _living=SimpleNamespace(agent=agent, _agent_id="test"),
        _channel=Channel(),
        _detect_image_format=lambda _data: (".jpg", "image/jpeg"),
    )
    tool = create_fetch_group_attachment_tool(adapter)

    def execute():
        with bind_tool_execution(
            tool_call_id="call-workspace",
            tool_name=tool.name,
            arguments={"attachment_ref": "feishu_om-file-workspace"},
            artifact_callback=None,
            session_id=session_id,
            person_id=person_id,
            workspace_service=workspace_service,
        ):
            return tool.execute(attachment_ref="feishu_om-file-workspace")

    first = execute()
    second = execute()

    assert first["workspace"]["workspace_id"] == workspace.id
    assert first["workspace"]["observation_id"] == observation.id
    assert second["workspace"] == first["workspace"]
    assets = workspace_service.assets.list_snapshots(workspace.id)
    assert len(assets) == 1
    assert assets[0]["id"] == first["workspace"]["asset_id"]
    updated = workspace_service.business.store.get_observation(observation.id)
    assert updated.asset_id == assets[0]["id"]
    assert updated.attributes["remote_attachment"]["status"] == "materialized"
    assert updated.attributes["remote_attachment"]["asset_id"] == assets[0]["id"]
    stored = db.find_group_attachments(
        session_id,
        "feishu_om-file-workspace",
    )[0]
    assert stored["metadata"]["workspace_id"] == workspace.id
    assert stored["metadata"]["workspace_asset_id"] == assets[0]["id"]
    assert stored["metadata"]["workspace_observation_id"] == observation.id
    assert group_message_id is not None
    db.close()
