import base64
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.gateway import artifacts as artifact_module
from xiaomei_brain.gateway.artifacts import (
    discover_tool_artifacts,
    public_artifact_metadata,
)
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.memory.conversation_db import ConversationDB


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


def test_chat_history_exposes_artifact_card_without_internal_path(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "history.txt"
    output.parent.mkdir(parents=True)
    output.write_text("history", encoding="utf-8")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "history.txt"}, f"Successfully wrote to {output}",
    )[0]
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


def test_legacy_artifact_message_is_moved_to_artifacts_table(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    output = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace" / "legacy.txt"
    output.parent.mkdir(parents=True)
    output.write_text("legacy", encoding="utf-8")
    artifact = discover_tool_artifacts(
        "xiaomei", "session-1", "turn-1", "write_file",
        {"path": "legacy.txt"}, f"Successfully wrote to {output}",
    )[0]
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
