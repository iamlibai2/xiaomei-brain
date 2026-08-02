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
    callback(
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
    db.close()


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
