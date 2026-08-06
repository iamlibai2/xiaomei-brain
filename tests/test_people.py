from __future__ import annotations

import sqlite3

import pytest

from xiaomei_brain.people import PeopleBiometricService, PeopleService, PeopleStore


def test_people_schema_is_additive_and_preserves_existing_user_id(tmp_path):
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'global',
            content TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO messages (user_id, content) VALUES (?, ?)",
        ("xiaoshuai", "保留的历史消息"),
    )
    conn.commit()
    conn.close()

    store = PeopleStore(db_path)
    conn = store._get_conn()

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        ).fetchall()
    }
    assert {
        "persons",
        "identity_bindings",
        "identity_events",
        "conversation_sessions",
    }.issubset(tables)
    assert conn.execute(
        "SELECT version FROM schema_versions WHERE component = 'people'",
    ).fetchone()[0] == 2
    assert [
        row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
    ] == ["id", "user_id", "content"]
    assert tuple(conn.execute(
        "SELECT user_id, content FROM messages",
    ).fetchone()) == ("xiaoshuai", "保留的历史消息")


def test_person_and_verified_identity_binding_lifecycle(tmp_path):
    service = PeopleService.for_agent_db(tmp_path / "brain.db")
    person = service.create_person("李白", person_id="libai")

    binding = service.store.create_binding(
        person.person_id,
        "self:key:abc",
        "abc",
        "public_key",
        public_key="PUBLIC KEY",
        verified_at=123.0,
    )

    resolved = service.store.resolve_identity("self:key:abc", "abc")
    assert resolved == binding
    assert service.store.list_bindings("libai") == [binding]

    assert service.store.revoke_binding(binding.binding_id, now=456.0)
    assert service.store.resolve_identity("self:key:abc", "abc") is None
    revoked = service.store.resolve_identity(
        "self:key:abc",
        "abc",
        include_revoked=True,
    )
    assert revoked is not None
    assert revoked.revoked_at == 456.0


def test_external_identity_can_only_bind_once(tmp_path):
    service = PeopleService.for_agent_db(tmp_path / "brain.db")
    service.create_person("甲", person_id="person-a")
    service.create_person("乙", person_id="person-b")
    service.store.create_binding(
        "person-a",
        "issuer",
        "subject",
        "public_key",
    )

    with pytest.raises(ValueError, match="外部身份已绑定"):
        service.store.create_binding(
            "person-b",
            "issuer",
            "subject",
            "public_key",
        )


def test_initialization_does_not_create_people_implicitly(tmp_path):
    service = PeopleService.for_agent_db(tmp_path / "brain.db")

    assert service.store.list_people() == []


def test_person_biometrics_are_scoped_to_people_and_not_legacy_contacts(tmp_path):
    import numpy as np

    people = PeopleService.for_agent_db(tmp_path / "memory" / "brain.db")
    person = people.create_person("李白", person_id="person-1")
    biometric_dir = tmp_path / "people" / "biometrics"
    voices_dir = biometric_dir / "voices"
    voices_dir.mkdir(parents=True)
    np.save(voices_dir / f"{person.person_id}.npy", np.asarray([0.1, 0.2]))

    biometrics = PeopleBiometricService(people, biometric_dir)

    assert biometrics.has_voiceprint(person.person_id) is True
    with pytest.raises(ValueError, match="人物不存在"):
        biometrics.has_voiceprint("legacy-contact")


def test_conversation_session_scope_cannot_change(tmp_path):
    store = PeopleStore(tmp_path / "brain.db")
    session = store.ensure_session("session-1", "person", "libai", now=1.0)

    assert session.scope_type == "person"
    assert store.ensure_session(
        "session-1",
        "person",
        "libai",
        now=2.0,
    ) == session
    with pytest.raises(ValueError, match="会话作用域不一致"):
        store.ensure_session("session-1", "agent", "xiaomei")


def test_legacy_session_claim_is_additive_and_audited(tmp_path):
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.executemany(
        """
        INSERT INTO messages (
            session_id, user_id, role, content, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("legacy-1", "old-libai", "user", "以前的问题", 1.0),
            ("legacy-1", "old-libai", "assistant", "以前的回答", 2.0),
        ],
    )
    conn.commit()
    conn.close()

    service = PeopleService.for_agent_db(db_path)
    person = service.create_person("李白")

    candidates = service.store.list_unclaimed_legacy_sessions()
    assert [item["session_id"] for item in candidates] == ["legacy-1"]
    assert candidates[0]["legacy_user_ids"] == ["old-libai"]

    claimed = service.store.claim_legacy_session("legacy-1", person.person_id)
    assert claimed.scope_type == "person"
    assert claimed.scope_id == person.person_id
    assert service.store.list_unclaimed_legacy_sessions() == []

    conn = service.store._get_conn()
    assert [
        tuple(row)
        for row in conn.execute(
            "SELECT user_id, role, content FROM messages ORDER BY id",
        ).fetchall()
    ] == [
        ("old-libai", "user", "以前的问题"),
        ("old-libai", "assistant", "以前的回答"),
    ]
    event = conn.execute(
        """
        SELECT event_type, person_id, metadata_json
        FROM identity_events ORDER BY event_id DESC LIMIT 1
        """,
    ).fetchone()
    assert event["event_type"] == "legacy_session_claimed"
    assert event["person_id"] == person.person_id
    assert '"session_id": "legacy-1"' in event["metadata_json"]
