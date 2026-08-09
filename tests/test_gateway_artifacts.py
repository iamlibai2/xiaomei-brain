import base64
import json
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.gateway import artifacts as artifact_module
from xiaomei_brain.gateway.artifacts import (
    _structured_strings,
    discover_tool_artifacts,
    project_stored_artifact,
    public_artifact_metadata,
    read_stored_artifact,
)
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.people import IdentityContext
from xiaomei_brain.projects import (
    ProjectActor,
    ProjectActorType,
    ProjectService,
    ProjectStore,
    ProjectWorkspaceManager,
)
from xiaomei_brain.workspaces import (
    WorkspaceService,
    WorkspaceStore,
    create_workspace_tools,
)


def _identity(person_id: str, conn_id: str) -> IdentityContext:
    return IdentityContext(
        person_id=person_id,
        issuer="test",
        subject=person_id,
        authentication_method="test",
        assurance="verified",
        authenticated_at=1.0,
        connection_id=conn_id,
    )


def test_human_readable_tool_result_exposes_mixed_separator_path():
    path = r"C:\Users\name/.xiaomei-brain/test\images\generated image.jpeg"

    values = _structured_strings(f"Generated 1 image:\n  - {path}")

    assert path in values


def test_write_file_becomes_agent_owned_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "report.md"
    output.parent.mkdir(parents=True)
    output.write_text("final report", encoding="utf-8")

    artifacts = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-1",
        "write_file",
        {"path": "report.md", "content": "final report"},
        f"Successfully wrote to {output}",
    )

    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "report.md"
    assert artifacts[0]["relative_path"] == "workspace/report.md"
    assert "relative_path" not in public_artifact_metadata(artifacts[0])


def test_visualization_html_becomes_sandboxed_artifact_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "sales.visualization.html"
    )
    output.parent.mkdir(parents=True)
    output.write_text(
        '<section id="sales"><button>切换地区</button><script>void 0</script></section>',
        encoding="utf-8",
    )

    artifact = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-visualize",
        "write",
        {"path": "sales.visualization.html"},
        json.dumps({"path": str(output)}, ensure_ascii=False),
    )[0]

    assert artifact["kind"] == "visualization"
    assert artifact["mime_type"] == "text/html"
    assert public_artifact_metadata(artifact)["kind"] == "visualization"


def test_audio_extension_wrapped_in_book_title_marks_is_playable(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "music"
        / "《正午散步.wav》"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")

    artifact = discover_tool_artifacts(
        "xiaomei",
        "session-audio",
        "turn-audio",
        "present_artifacts",
        {"paths": [str(output)]},
        json.dumps({"path": str(output)}, ensure_ascii=False),
    )[0]

    assert artifact["kind"] == "audio"
    assert artifact["mime_type"].startswith("audio/")
    assert artifact["storage_suffix"] == ".wav"
    stored = read_stored_artifact("xiaomei", "session-audio", artifact)
    assert base64.b64decode(stored["data_base64"]) == output.read_bytes()


def test_legacy_wrapped_audio_storage_suffix_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    artifact_id = "a" * 32
    payload = b"RIFF\x04\x00\x00\x00WAVE"
    stored_path = artifact_module._artifact_storage_path(
        "xiaomei", "session-audio", artifact_id, ".wav》",
    )
    stored_path.parent.mkdir(parents=True)
    stored_path.write_bytes(payload)
    artifact = {
        "id": artifact_id,
        "name": "《正午散步.wav》",
        "mime_type": "application/octet-stream",
        "kind": "file",
        "size": len(payload),
        "storage_suffix": ".wav》",
    }

    stored = read_stored_artifact("xiaomei", "session-audio", artifact)

    assert base64.b64decode(stored["data_base64"]) == payload


def test_oversized_visualization_is_not_discovered(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(artifact_module, "MAX_VISUALIZATION_ARTIFACT_BYTES", 8)
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "large.visualization.html"
    )
    output.parent.mkdir(parents=True)
    output.write_text("<div>too large</div>", encoding="utf-8")

    artifacts = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-visualize",
        "write",
        {"path": str(output)},
        json.dumps({"path": str(output)}, ensure_ascii=False),
    )

    assert artifacts == []


def test_artifact_discovery_ignores_files_outside_agent_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    outside = tmp_path / "private.txt"
    outside.write_text("secret", encoding="utf-8")

    artifacts = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": str(outside), "content": "secret"},
        f"Successfully wrote to {outside}",
    )

    assert artifacts == []


def test_project_video_uses_video_specific_artifact_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(artifact_module, "MAX_ARTIFACT_BYTES", 4)
    monkeypatch.setattr(artifact_module, "MAX_VIDEO_ARTIFACT_BYTES", 16)
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "projects"
        / "project_1" / "deliverables" / "clip.mp4"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"video123")

    artifacts = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-1",
        "generate_video_minimax",
        {},
        f"- output_path: {output}",
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "video"
    assert artifacts[0]["relative_path"] == (
        "projects/project_1/deliverables/clip.mp4"
    )


def test_read_file_is_not_reported_as_created_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    existing = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "input.pptx"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing input")

    artifacts = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-1",
        "read_file",
        {"path": "input.pptx"},
        "existing input",
    )

    assert artifacts == []


def test_artifact_can_be_projected_into_origin_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "result.pptx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"presentation")
    artifact = discover_tool_artifacts(
        "xiaomei",
        "assignment:1",
        "assignment-run:1",
        "write_file",
        {"path": "result.pptx"},
        f"Successfully wrote to {output}",
    )[0]

    project_stored_artifact(
        "xiaomei",
        "assignment:1",
        "session-origin",
        artifact,
    )

    projected = read_stored_artifact("xiaomei", "session-origin", artifact)
    assert base64.b64decode(projected["data_base64"]) == b"presentation"
    assert projected["mime_type"].endswith("presentationml.presentation")


def test_artifact_rpc_reads_only_exact_session_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "result.txt"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"result data")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "result.txt"}, f"Successfully wrote to {output}",
    )[0]
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("session-1", artifact, tool_call_id="tool-1")
    output.write_bytes(b"later revision")
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")
    router._identity_contexts["connection-1"] = _identity(
        "person-1",
        "connection-1",
    )

    response = router.dispatch("connection-1", "rpc-1", "artifact.get", {
        "session_id": "session-1", "artifact_id": artifact["id"],
    })
    denied = router.dispatch("connection-1", "rpc-2", "artifact.get", {
        "session_id": "session-2", "artifact_id": artifact["id"],
    })

    assert base64.b64decode(response["result"]["artifact"]["data_base64"]) == b"result data"
    assert "relative_path" not in response["result"]["artifact"]
    assert denied["error"]["code"] == -32602
    db.close()


def test_chat_send_references_person_owned_artifact_as_annotated_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "proposal.docx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"docx snapshot")
    artifact = discover_tool_artifacts(
        "xiaomei", "source-session", "turn-1", "write_file",
        {"path": "proposal.docx"}, f"Successfully wrote to {output}",
    )[0]
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("source-session", artifact, user_id="person-1")

    class Inbound:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return Accepted(LivingMessage(
                content=raw.content,
                session_id=raw.session_id,
                attachments=raw.attachments,
                images=raw.images,
            ))

    inbound = Inbound()
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
        _gateway_inbound=inbound,
    ))
    router._auth_sessions.add("connection-1")
    router._identity_contexts["connection-1"] = _identity("person-1", "connection-1")
    cm.set_session("target-session", "connection-1", "person-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.send", {
        "content": "把这段改得更正式",
        "client_request_id": "request-1",
        "session_id": "target-session",
        "artifact_references": [{
            "artifact_id": artifact["id"],
            "session_id": "source-session",
            "selection": {
                "kind": "text",
                "page": 2,
                "selected_text": "原来的段落",
                "context_before": "上一段",
                "context_after": "下一段",
            },
        }],
    })

    assert response.get("result", {}).get("accepted") is True, response
    attachment = inbound.messages[0].attachments[0]
    assert attachment["name"] == "proposal.docx"
    assert attachment["source_artifact"] == {
        "artifact_id": artifact["id"],
        "session_id": "source-session",
    }
    assert attachment["managed_artifact_relative_path"] == "proposal.docx"
    assert attachment["annotation"]["selected_text"] == "原来的段落"
    assert Path(attachment["local_path"]).read_bytes() == b"docx snapshot"
    cm.unregister("connection-1")
    db.close()


def test_chat_send_rejects_artifact_owned_by_another_person(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "private.docx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"private")
    artifact = discover_tool_artifacts(
        "xiaomei", "source-session", "turn-1", "write_file",
        {"path": "private.docx"}, f"Successfully wrote to {output}",
    )[0]
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("source-session", artifact, user_id="person-2")
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")
    router._identity_contexts["connection-1"] = _identity("person-1", "connection-1")
    cm.set_session("target-session", "connection-1", "person-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.send", {
        "content": "修改它",
        "client_request_id": "request-1",
        "session_id": "target-session",
        "artifact_references": [{
            "artifact_id": artifact["id"],
            "session_id": "source-session",
        }],
    })

    assert response["error"]["code"] == -32602
    cm.unregister("connection-1")
    db.close()


def test_artifact_rpc_lists_only_person_and_global_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
    output.mkdir(parents=True)
    db = ConversationDB(tmp_path / "brain.db")
    for name, person_id, session_id in (
        ("mine.txt", "person-1", "session-mine"),
        ("shared.txt", "global", "session-shared"),
        ("private.txt", "person-2", "session-private"),
    ):
        path = output / name
        path.write_text(name, encoding="utf-8")
        artifact = discover_tool_artifacts(
            "xiaomei",
            session_id,
            f"turn-{name}",
            "write_file",
            {"path": name},
            f"Successfully wrote to {path}",
        )[0]
        db.save_artifact(session_id, artifact, user_id=person_id)

    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")
    router._identity_contexts["connection-1"] = _identity(
        "person-1",
        "connection-1",
    )

    response = router.dispatch("connection-1", "rpc-1", "artifact.list", {})
    artifacts = response["result"]["artifacts"]

    assert {item["name"] for item in artifacts} == {"mine.txt", "shared.txt"}
    assert all("user_id" not in item for item in artifacts)
    assert all("relative_path" not in item for item in artifacts)
    assert {item["display_path"] for item in artifacts} == {
        "workspace/mine.txt",
        "workspace/shared.txt",
    }
    db.close()


def test_artifact_event_is_persisted_and_contains_no_local_path(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "answer.md"
    output.parent.mkdir(parents=True)
    output.write_text("answer", encoding="utf-8")
    db = ConversationDB(tmp_path / "brain.db")

    class Router:
        def __init__(self):
            self.events = []

        def route_for_session(self, _session_id):
            return SimpleNamespace(type="ws")

        def deliver_event(self, event, payload, route, **context):
            self.events.append((event, payload, route, context))

    gateway_router = Router()
    parent = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
        _router=gateway_router,
    )
    callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-1", "user-1", parent,
    )

    callback("tool-1", "write_file", {"path": "answer.md"}, f"Successfully wrote to {output}")
    rows, _ = db.get_history_page(session_id="session-1", limit=10)
    artifacts = db.list_artifacts("session-1")

    assert rows == []
    assert artifacts[0]["name"] == "answer.md"
    assert db.get_recent(session_id="session-1") == []
    assert db.search("answer.md") == []
    assert db.count("session-1") == 0
    assert gateway_router.events[0][0] == "artifact.created"
    assert "relative_path" not in gateway_router.events[0][1]
    db.close()


def test_present_artifacts_publishes_created_then_presented(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "answer.md"
    output.parent.mkdir(parents=True)
    output.write_text("answer", encoding="utf-8")
    db = ConversationDB(tmp_path / "brain.db")

    class Router:
        def __init__(self):
            self.events = []

        def route_for_session(self, _session_id):
            return SimpleNamespace(type="ws")

        def deliver_event(self, event, payload, route, **context):
            self.events.append((event, payload, route, context))

    gateway_router = Router()
    parent = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
        _router=gateway_router,
    )
    callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-1", "user-1", parent,
    )

    result = json.dumps({"path": [str(output)], "message": "这是最终报告"})
    published = callback(
        "tool-1",
        "present_artifacts",
        {"paths": [str(output)], "message": "这是最终报告"},
        result,
    )

    assert [item[0] for item in gateway_router.events] == [
        "artifact.created",
        "artifact.presented",
    ]
    assert gateway_router.events[1][1]["message"] == "这是最终报告"
    assert "relative_path" not in gateway_router.events[1][1]
    stored = db.list_artifacts("session-1")[0]
    assert stored["name"] == "answer.md"
    assert stored["presented"] is True
    assert len(published) == 1
    assert published[0]["id"] == stored["id"]
    assert published[0]["session_id"] == "session-1"
    assert published[0]["name"] == "answer.md"
    db.close()


def test_focused_workspace_adopts_conversation_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "quote.md"
    output.parent.mkdir(parents=True)
    output.write_text("quote", encoding="utf-8")
    db = ConversationDB(tmp_path / "brain.db")
    workspace_service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
    )
    workspace = workspace_service.create(
        name="客户经营",
        purpose="跟进客户与报价",
        created_by_person_id="person-1",
    )
    workspace_service.focus_session(
        workspace.id,
        session_id="session-1",
        person_id="person-1",
        turn_id="turn-focus",
    )
    core = SimpleNamespace(
        current_attachments=[], active_assignment_id="", active_project_id="",
    )
    agent = SimpleNamespace(
        id="xiaomei",
        conversation_db=db,
        workspace_service=workspace_service,
        _get_agent=lambda: core,
    )
    parent = SimpleNamespace(_agent_id="xiaomei", agent=agent, _router=None)
    callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-1", "person-1", parent,
    )

    published = callback(
        "tool-1",
        "present_artifacts",
        {"paths": [str(output)], "message": "报价方案"},
        json.dumps({"path": [str(output)]}),
    )

    first_artifact_id = published[0]["id"]
    output.write_text("quote revised", encoding="utf-8")
    second_callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-2", "person-1", parent,
    )
    revised = second_callback(
        "tool-2",
        "edit",
        {"path": str(output)},
        json.dumps({"path": str(output)}),
    )

    assets = workspace_service.assets.store.list_for_workspace(workspace.id)
    assert len(assets) == 1
    assert first_artifact_id != revised[0]["id"]
    assert published[0]["workspace_asset_id"] == assets[0].id
    assert revised[0]["workspace_asset_id"] == assets[0].id
    assert assets[0].revision == 2
    assert assets[0].source_type == "agent_working_file"
    assert assets[0].metadata["latest_artifact_id"] == revised[0]["id"]
    assert assets[0].sha256
    restored_asset = workspace_service.assets.find_by_artifact_reference(
        "session-1",
        revised[0]["id"],
    )
    assert restored_asset is not None
    assert restored_asset.id == assets[0].id

    core.user_id = "person-1"
    core.session_id = "session-1"
    core.turn_id = "turn-3"
    tools = {tool.name: tool for tool in create_workspace_tools(agent)}
    read_result = tools["read_workspace_asset"].execute(asset_id=assets[0].id)
    assert read_result["content"] == "quote revised"
    assert read_result["next_offset"] is None
    evidence_result = tools["preserve_workspace_asset_as_evidence"].execute(
        asset_id=assets[0].id,
        reason="报价已发送给客户",
    )
    evidence_id = evidence_result["evidence"]["id"]
    output.write_text("unrecorded later edit", encoding="utf-8")
    evidence_read = tools["read_workspace_asset"].execute(asset_id=evidence_id)
    assert evidence_read["content"] == "quote revised"
    db.close()


def test_downloaded_artifact_links_back_to_external_workspace_asset(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "downloads" / "确认单.pdf"
    )
    output.parent.mkdir(parents=True)
    output.write_bytes(b"pdf-content")
    db = ConversationDB(tmp_path / "brain.db")
    workspace_service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
    )
    workspace = workspace_service.create(
        name="客户经营",
        purpose="跟进客户与报价",
        created_by_person_id="person-1",
    )
    workspace_service.focus_session(
        workspace.id,
        session_id="session-1",
        person_id="person-1",
        turn_id="turn-focus",
    )
    external = workspace_service.assets.register_external(
        workspace.id,
        person_id="person-1",
        source_type="qq_mail_attachment",
        source_id="person@qq.com:INBOX:42:2",
        name="确认单.pdf",
        locator="qq-mail://person@qq.com/INBOX/42/attachments/2",
        kind="file",
        mime_type="application/pdf",
        session_id="session-1",
    )
    core = SimpleNamespace(
        current_attachments=[], active_assignment_id="", active_project_id="",
    )
    agent = SimpleNamespace(
        id="xiaomei",
        conversation_db=db,
        workspace_service=workspace_service,
        _get_agent=lambda: core,
    )
    parent = SimpleNamespace(_agent_id="xiaomei", agent=agent, _router=None)
    callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-1", "person-1", parent,
    )

    published = callback(
        "tool-1",
        "download_qq_mail_attachment",
        {"uid": "42", "attachment_id": "2"},
        json.dumps({
            "path": output.resolve().as_posix(),
            "source_asset_id": external.id,
        }),
    )

    working_id = published[0]["workspace_asset_id"]
    assert workspace_service.assets.store.has_link(
        working_id,
        workspace.id,
        entity_type="asset",
        entity_id=external.id,
        relation="materialized_from",
    )
    assert workspace_service.assets.store.has_link(
        external.id,
        workspace.id,
        entity_type="asset",
        entity_id=working_id,
        relation="materialized_as",
    )
    db.close()


def test_presented_workspace_artifact_is_adopted_by_active_project(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"final-video")
    db = ConversationDB(tmp_path / "conversation.db")
    project_service = ProjectService(
        ProjectStore(tmp_path / "project.db"),
        ProjectWorkspaceManager(tmp_path / "projects"),
    )
    workspace_service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
    )
    workspace = workspace_service.create(
        name="Film workspace",
        purpose="Produce and deliver one film",
        created_by_person_id="person-1",
    )
    workspace_service.focus_session(
        workspace.id,
        session_id="session-1",
        person_id="person-1",
        turn_id="turn-focus",
    )
    actor = ProjectActor(ProjectActorType.AGENT, "xiaomei")
    project = project_service.create(
        name="Film", project_type="video.production", actor=actor,
        scope_type="person", scope_id="person-1",
    )
    core = SimpleNamespace(active_assignment_id="", active_project_id=project.id)
    agent = SimpleNamespace(
        id="xiaomei",
        conversation_db=db,
        project_service=project_service,
        workspace_service=workspace_service,
        _get_agent=lambda: core,
    )
    parent = SimpleNamespace(_agent_id="xiaomei", agent=agent, _router=None)
    callback = ConversationDriver._make_artifact_callback(
        "session-1", "turn-1", "person-1", parent,
    )

    callback(
        "tool-1", "present_artifacts",
        {"paths": [str(output)], "message": "final"},
        json.dumps({"path": [str(output)]}),
    )

    assets = project_service.store.list_assets(project.id)
    assert len(assets) == 1
    assert assets[0].role.value == "deliverable"
    unified_assets = workspace_service.assets.store.list_for_workspace(workspace.id)
    assert len(unified_assets) == 1
    assert assets[0].metadata["asset_id"] == unified_assets[0].id
    assert workspace_service.assets.store.has_link(
        unified_assets[0].id,
        workspace.id,
        entity_type="project_asset",
        entity_id=assets[0].id,
        relation="projected_as",
    )
    adopted = Path(project.state_root) / assets[0].relative_uri
    assert adopted.read_bytes() == b"final-video"
    project_service.store.close()
    db.close()


def test_artifact_update_reuses_id_and_refreshes_stored_content(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "report.docx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"original")
    original = discover_tool_artifacts(
        "xiaomei", "source-session", "turn-1", "write_file",
        {"path": str(output)}, json.dumps({"output_path": str(output)}),
    )[0]
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("source-session", original, user_id="person-1")

    class Router:
        def __init__(self):
            self.events = []

        def route_for_session(self, _session_id):
            return SimpleNamespace(type="ws")

        def deliver_event(self, event, payload, route, **context):
            self.events.append((event, payload, route, context))

    gateway_router = Router()
    parent = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
        _router=gateway_router,
    )
    callback = ConversationDriver._make_artifact_callback(
        "current-session", "turn-2", "person-1", parent,
    )
    output.write_bytes(b"updated content")
    result = json.dumps({
        "success": True,
        "output_path": str(output),
        "updated_artifact": {
            "artifact_id": original["id"],
            "session_id": "source-session",
            "output_path": str(output),
        },
    })

    callback("tool-update", "write_document", {"output_name": "report.docx"}, result)

    artifacts = db.list_artifacts("source-session")
    assert len(artifacts) == 1
    assert artifacts[0]["id"] == original["id"]
    assert artifacts[0]["size"] == len(b"updated content")
    stored = artifact_module.read_stored_artifact(
        "xiaomei", "source-session", artifacts[0],
    )
    assert base64.b64decode(stored["data_base64"]) == b"updated content"
    assert gateway_router.events[0][0] == "artifact.updated"
    assert gateway_router.events[0][1]["session_id"] == "source-session"
    assert gateway_router.events[0][3]["session_id"] == "current-session"
    db.close()


def test_fullscreen_visualization_edit_reuses_attached_artifact_identity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "dashboard.visualization.html"
    )
    output.parent.mkdir(parents=True)
    output.write_text("<div>updated</div>", encoding="utf-8")
    artifact_id = "a" * 32

    artifact = discover_tool_artifacts(
        "xiaomei",
        "current-session",
        "turn-2",
        "edit",
        {"path": "dashboard.visualization.html"},
        json.dumps({"path": str(output), "replacements": 1}),
        source_attachments=({
            "presentation_mode": "visualization_fullscreen",
            "managed_artifact_path": str(output),
            "source_artifact": {
                "artifact_id": artifact_id,
                "session_id": "source-session",
            },
        },),
    )[0]

    assert artifact["id"] == artifact_id
    assert artifact["session_id"] == "source-session"
    assert artifact["updated"] is True


def test_non_fullscreen_visualization_edit_keeps_normal_artifact_discovery(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "dashboard.visualization.html"
    )
    output.parent.mkdir(parents=True)
    output.write_text("<div>updated</div>", encoding="utf-8")
    source_id = "b" * 32

    artifact = discover_tool_artifacts(
        "xiaomei",
        "current-session",
        "turn-2",
        "edit",
        {"path": "dashboard.visualization.html"},
        json.dumps({"path": str(output), "replacements": 1}),
        source_attachments=({
            "managed_artifact_path": str(output),
            "source_artifact": {
                "artifact_id": source_id,
                "session_id": "source-session",
            },
        },),
    )[0]

    assert artifact["id"] != source_id
    assert artifact["session_id"] == "current-session"
    assert artifact["updated"] is False


def test_chat_history_exposes_artifact_card_without_internal_path(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "history.txt"
    output.parent.mkdir(parents=True)
    output.write_text("history", encoding="utf-8")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "history.txt"}, f"Successfully wrote to {output}",
    )[0]
    artifact["presented"] = True
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("session-1", artifact, tool_call_id="tool-1")
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei", agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.history", {
        "session_id": "session-1",
    })
    card = response["result"]["messages"][0]["artifact"]

    assert card["name"] == "history.txt"
    assert "relative_path" not in card
    db.close()


def test_represented_artifact_moves_to_latest_history_position(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "report.xlsx"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"first")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "present_artifacts",
        {}, json.dumps({"path": [str(output)]}),
    )[0]
    artifact["presented"] = True
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact("session-1", artifact, tool_call_id="tool-1")
    assistant_id = db.log("session-1", "assistant", "first delivery complete")

    output.write_bytes(b"second")
    updated = dict(artifact)
    updated.update({"size": len(b"second"), "turn_id": "turn-2", "presented": True})
    db.save_artifact("session-1", updated, tool_call_id="tool-2")
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei", agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")

    messages = router.dispatch("connection-1", "rpc-1", "chat.history", {
        "session_id": "session-1",
    })["result"]["messages"]

    assert [item["role"] for item in messages] == ["assistant", "artifact"]
    assert messages[0]["id"] == assistant_id
    assert messages[1]["artifact"]["id"] == artifact["id"]
    db.close()


def test_chat_history_preserves_tool_turn_id(tmp_path):
    db = ConversationDB(tmp_path / "brain.db")
    db.log(
        "session-1",
        "tool",
        "command completed",
        tool_name="shell",
        tool_call_id="tool-1",
        metadata={"turn_id": "turn-1", "duration_ms": 1250},
    )
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei", agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.history", {
        "session_id": "session-1",
    })

    tool_message = response["result"]["messages"][0]
    assert tool_message["role"] == "tool"
    assert tool_message["turn_id"] == "turn-1"
    assert tool_message["duration_ms"] == 1250
    db.close()


def test_chat_history_hides_unpresented_process_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    workspace = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
    workspace.mkdir(parents=True)
    helper = workspace / "generate_report.py"
    report = workspace / "report.docx"
    helper.write_text("print('helper')", encoding="utf-8")
    report.write_bytes(b"final-report")
    db = ConversationDB(tmp_path / "brain.db")

    process_artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "generate_report.py"}, f"Successfully wrote to {helper}",
    )[0]
    final_artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "present_artifacts",
        {}, json.dumps({"path": [str(report)]}),
    )[0]
    final_artifact["presented"] = True
    db.save_artifact("session-1", process_artifact, tool_call_id="tool-1")
    db.save_artifact("session-1", final_artifact, tool_call_id="tool-2")

    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei", agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")
    response = router.dispatch("connection-1", "rpc-1", "chat.history", {
        "session_id": "session-1",
    })

    cards = [
        item["artifact"]["name"]
        for item in response["result"]["messages"]
        if item["role"] == "artifact"
    ]
    assert cards == ["report.docx"]
    assert {item["name"] for item in db.list_artifacts("session-1")} == {
        "generate_report.py",
        "report.docx",
    }
    db.close()


def test_legacy_artifact_message_is_moved_to_artifacts_table(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "legacy.txt"
    output.parent.mkdir(parents=True)
    output.write_text("legacy", encoding="utf-8")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "legacy.txt"}, f"Successfully wrote to {output}",
    )[0]
    artifact["presented"] = True
    db_path = tmp_path / "brain.db"
    db = ConversationDB(db_path)
    db.log(
        "session-1", "artifact", "legacy.txt",
        tool_call_id="tool-1", metadata=artifact,
    )
    db._set_schema_version("conversation_db", 1)
    db.close()

    migrated = ConversationDB(db_path)
    message_rows = migrated._get_conn().execute(
        "SELECT * FROM messages WHERE role = 'artifact'",
    ).fetchall()

    assert message_rows == []
    assert migrated.get_artifact_metadata("session-1", artifact["id"])["name"] == "legacy.txt"
    assert migrated.get_recent(session_id="session-1") == []
    migrated.close()


def test_artifact_between_message_pages_is_returned_with_older_page(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "paged.txt"
    output.parent.mkdir(parents=True)
    output.write_text("paged", encoding="utf-8")
    db = ConversationDB(tmp_path / "brain.db")
    db.log("session-1", "user", "create a file")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "paged.txt"}, f"Successfully wrote to {output}",
    )[0]
    artifact["presented"] = True
    db.save_artifact("session-1", artifact, tool_call_id="tool-1")
    assistant_id = db.log("session-1", "assistant", "done")
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei", agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")

    newest = router.dispatch("connection-1", "rpc-1", "chat.history", {
        "session_id": "session-1", "limit": 1,
    })["result"]
    older = router.dispatch("connection-1", "rpc-2", "chat.history", {
        "session_id": "session-1", "limit": 1, "before_id": assistant_id,
    })["result"]

    assert [item["role"] for item in newest["messages"]] == ["assistant"]
    assert [item["role"] for item in older["messages"]] == ["user", "artifact"]
    db.close()
