from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.people import PeopleService


def test_unified_search_is_person_scoped(tmp_path: Path):
    db_path = tmp_path / "brain.db"
    db = ConversationDB(db_path)
    people = PeopleService.for_agent_db(db_path)
    current = people.create_person("Current Person")
    other = people.create_person("Other Person")
    people.store.ensure_session("mine", "person", current.person_id)
    people.store.ensure_session("theirs", "person", other.person_id)
    db.log("mine", "user", "project aurora current notes", user_id=current.person_id)
    db.log("theirs", "user", "project aurora private notes", user_id=other.person_id)
    db.save_artifact("mine", {
        "id": "a" * 32,
        "name": "aurora-report.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 12,
        "kind": "document",
        "description": "project aurora report",
    }, user_id=current.person_id)
    db.save_artifact("theirs", {
        "id": "b" * 32,
        "name": "aurora-secret.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 12,
        "kind": "document",
        "description": "private aurora report",
    }, user_id=other.person_id)

    living = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=db),
        _assignment_service=None,
    )
    router = MethodRouter(living=living)
    conn_id = "search-connection"
    router._auth_sessions.add(conn_id)
    router._identity_contexts[conn_id] = SimpleNamespace(person_id=current.person_id)
    try:
        response = router.dispatch(
            conn_id,
            "search-1",
            "search.query",
            {"query": "aurora", "limit": 10},
        )
    finally:
        people.store.close()
        db.close()

    assert "error" not in response
    result = response["result"]
    assert [item["session_id"] for item in result["sessions"]] == ["mine"]
    assert [item["session_id"] for item in result["messages"]] == ["mine"]
    assert [item["session_id"] for item in result["artifacts"]] == ["mine"]
    assert result["assignments"] == []


def test_unified_search_requires_verified_person(tmp_path: Path):
    db = ConversationDB(tmp_path / "brain.db")
    router = MethodRouter(living=SimpleNamespace(
        agent=SimpleNamespace(conversation_db=db),
        _assignment_service=None,
    ))
    router._auth_sessions.add("search-connection")
    try:
        response = router.dispatch(
            "search-connection",
            "search-2",
            "search.query",
            {"query": "anything"},
        )
    finally:
        db.close()

    assert response["error"]["code"] == -32001
