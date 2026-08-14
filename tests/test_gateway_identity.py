from __future__ import annotations

import base64
import sqlite3
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.people import PeopleService
from xiaomei_brain.people.challenge import ChallengeError, ChallengeManager


def _identity_key() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, base64.b64encode(public_key).decode("ascii")


def _sign(private_key: Ed25519PrivateKey, challenge: str) -> str:
    return base64.b64encode(
        private_key.sign(challenge.encode("utf-8")),
    ).decode("ascii")


class _Inbound:
    def __init__(self) -> None:
        self.messages = []

    def accept(self, raw):
        self.messages.append(raw)
        return Accepted(LivingMessage(
            content=raw.content,
            user_id=raw.peer_id,
            session_id=raw.session_id,
        ))


class _Biometrics:
    def __init__(self) -> None:
        self.voices: set[str] = set()
        self.faces: set[str] = set()
        self.last_face_person = ""

    def has_voiceprint(self, person_id: str) -> bool:
        return person_id in self.voices

    def has_face(self, person_id: str) -> bool:
        return person_id in self.faces

    def register_face(self, person_id: str, image_path: str) -> bool:
        assert open(image_path, "rb").read() == b"fake-jpeg"
        self.last_face_person = person_id
        self.faces.add(person_id)
        return True

    def verify_face(self, person_id: str, image_path: str) -> bool:
        assert open(image_path, "rb").read() == b"fake-jpeg"
        return person_id in self.faces


class _Living:
    def __init__(self, db_path) -> None:
        self._people_service = PeopleService.for_agent_db(db_path)
        self._people_biometrics = _Biometrics()
        self._gateway_inbound = _Inbound()
        self._agent_id = "xiaomei"
        self.user_id = "global"
        self.fresh_tail_loads = 0
        self.fresh_tail_sessions: list[tuple[str, str | None]] = []
        self._turn_registry = SimpleNamespace(snapshot=lambda _session_id: None)
        self._attention = None
        self._core = SimpleNamespace(user_id="global")
        self.agent = SimpleNamespace(_get_agent=lambda: self._core)

    def load_fresh_tail(self, session_id: str, user_id: str | None = None):
        self.fresh_tail_loads += 1
        self.fresh_tail_sessions.append((session_id, user_id))
        return []


def _connect(router: MethodRouter, conn_id: str, session_id: str) -> dict:
    response = router.dispatch(conn_id, "connect-1", "connect", {
        "client": "test",
        "session_id": session_id,
        # 旧客户端即使提交身份也只能被忽略。
        "user_id": "attacker-selected",
    })
    cm.set_pending_session(conn_id, response["result"]["session_id"])
    return response


def test_legacy_context_activation_does_not_duplicate_desktop_session_prefix(tmp_path):
    living = _Living(tmp_path / "brain.db")
    activated: list[tuple[str, list[dict]]] = []
    living._attention = SimpleNamespace(
        preload_loaded=lambda key, messages: activated.append((key, messages)),
    )
    router = MethodRouter(living=living)

    router._identity_methods._activate_legacy_conversation_context(
        "ws-db65e318", "person-1"
    )
    router._identity_methods._activate_legacy_conversation_context(
        "legacy-session", "person-1"
    )

    assert activated == [
        ("session:ws-db65e318", []),
        ("session:ws-legacy-session", []),
    ]
    assert living.fresh_tail_sessions == [
        ("ws-db65e318", "person-1"),
        ("legacy-session", "person-1"),
    ]


def test_identity_activation_does_not_mutate_active_core(tmp_path):
    living = _Living(tmp_path / "brain.db")
    living.user_id = "person-active"
    living._core.user_id = "person-active"
    living._core.messages = [{"role": "user", "content": "active turn"}]
    living._core.context_key = "session:active"
    preloaded: list[tuple[str, list[dict]]] = []
    living._attention = SimpleNamespace(
        preload_loaded=lambda key, messages: preloaded.append((key, messages)),
    )
    router = MethodRouter(living=living)

    router._identity_methods._activate_legacy_conversation_context(
        "ws-future", "person-future"
    )

    assert living.user_id == "person-active"
    assert living._core.user_id == "person-active"
    assert living._core.messages == [
        {"role": "user", "content": "active turn"},
    ]
    assert living._core.context_key == "session:active"
    assert preloaded == [("session:ws-future", [])]


def test_fresh_tail_queries_only_the_authenticated_session():
    """原始消息恢复必须同时受 Person 和 session_id 约束。"""
    from xiaomei_brain.consciousness.conscious_living import ConsciousLiving

    calls: list[dict] = []

    class ConversationDB:
        def get_recent(self, count, **filters):
            calls.append({"count": count, **filters})
            return []

    core = SimpleNamespace(messages=[
        {"role": "user", "content": "message from the previous session"},
    ])
    agent = SimpleNamespace(
        conversation_db=ConversationDB(),
        dag=object(),
        _get_agent=lambda: core,
    )
    living = SimpleNamespace(
        agent=agent,
        user_id="person-1",
        _config=SimpleNamespace(
            context=SimpleNamespace(fresh_tail_count=40),
        ),
    )

    restored = ConsciousLiving.load_fresh_tail(living, "ws-current")

    assert calls == [{
        "count": 40,
        "session_id": "ws-current",
        "user_id": "person-1",
    }]
    assert restored == []
    assert core.messages == [
        {"role": "user", "content": "message from the previous session"},
    ]


def test_register_challenge_binds_server_verified_person_to_connection(tmp_path):
    living = _Living(tmp_path / "brain.db")
    router = MethodRouter(living=living)
    conn_id = "registration-connection"
    private_key, public_key = _identity_key()

    connected = _connect(router, conn_id, "session-1")
    before_auth = router.dispatch(conn_id, "chat-0", "chat.send", {
        "content": "不能提前聊天",
        "client_request_id": "before-auth",
    })
    begin = router.dispatch(conn_id, "register-1", "identity.register.begin", {
        "display_name": "李白",
        "public_key": public_key,
    })
    challenge = begin["result"]["challenge"]
    complete = router.dispatch(
        conn_id,
        "register-2",
        "identity.register.complete",
        {
            "challenge_id": begin["result"]["challenge_id"],
            "signature": _sign(private_key, challenge),
        },
    )

    try:
        assert connected["result"]["identity_status"] == "required"
        assert before_auth["error"]["code"] == -32001
        assert complete["result"]["authenticated"] is True
        person_id = complete["result"]["person"]["person_id"]
        assert cm.get_person_id(conn_id) == person_id
        assert cm.get_session_id(conn_id) == "session-1"
        # Authentication binds the connection only.  The shared realtime Core
        # is switched later, when this connection's message reaches its Turn.
        assert living.user_id == "global"
        assert living.fresh_tail_loads == 1
        assert living.fresh_tail_sessions == [("session-1", person_id)]

        spoofed = router.dispatch(conn_id, "chat-1", "chat.send", {
            "content": "冒用别人",
            "client_request_id": "spoofed",
            "user_id": "another-person",
        })
        accepted = router.dispatch(conn_id, "chat-2", "chat.send", {
            "content": "真实身份",
            "client_request_id": "accepted",
        })
        assert spoofed["error"]["code"] == -32001
        assert accepted["result"]["accepted"] is True
        assert living._gateway_inbound.messages[0].peer_id == person_id
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)


def test_existing_identity_can_authenticate_on_a_new_connection(tmp_path):
    living = _Living(tmp_path / "brain.db")
    router = MethodRouter(living=living)
    private_key, public_key = _identity_key()

    first_conn = "first-connection"
    _connect(router, first_conn, "session-1")
    registration = router.dispatch(
        first_conn,
        "register-1",
        "identity.register.begin",
        {"display_name": "李白", "public_key": public_key},
    )
    registered = router.dispatch(
        first_conn,
        "register-2",
        "identity.register.complete",
        {
            "challenge_id": registration["result"]["challenge_id"],
            "signature": _sign(private_key, registration["result"]["challenge"]),
        },
    )
    person_id = registered["result"]["person"]["person_id"]
    issuer = registered["result"]["identity"]["issuer"]
    subject = registered["result"]["identity"]["subject"]
    router.drop_session(first_conn)
    cm.unregister(first_conn)

    second_conn = "second-connection"
    _connect(router, second_conn, "session-2")
    begin = router.dispatch(
        second_conn,
        "auth-1",
        "identity.authenticate.begin",
        {"issuer": issuer, "subject": subject},
    )
    complete = router.dispatch(
        second_conn,
        "auth-2",
        "identity.authenticate.complete",
        {
            "challenge_id": begin["result"]["challenge_id"],
            "signature": _sign(private_key, begin["result"]["challenge"]),
        },
    )
    current = router.dispatch(second_conn, "current-1", "identity.current", {})

    try:
        assert complete["result"]["person"]["person_id"] == person_id
        assert current["result"]["authenticated"] is True
        assert current["result"]["person"]["person_id"] == person_id
    finally:
        router.drop_session(second_conn)
        cm.unregister(second_conn)


def test_biometrics_are_scoped_to_authenticated_person(tmp_path):
    living = _Living(tmp_path / "brain.db")
    router = MethodRouter(living=living)
    conn_id = "biometric-connection"
    private_key, public_key = _identity_key()
    _connect(router, conn_id, "session-biometric")

    unauthorized = router.dispatch(
        conn_id,
        "biometric-before-auth",
        "identity.biometrics.status",
        {},
    )
    begin = router.dispatch(conn_id, "register-1", "identity.register.begin", {
        "display_name": "李白",
        "public_key": public_key,
    })
    complete = router.dispatch(conn_id, "register-2", "identity.register.complete", {
        "challenge_id": begin["result"]["challenge_id"],
        "signature": _sign(private_key, begin["result"]["challenge"]),
    })
    person_id = complete["result"]["person"]["person_id"]

    before = router.dispatch(conn_id, "biometric-status-1", "identity.biometrics.status", {})
    image = base64.b64encode(b"fake-jpeg").decode("ascii")
    enrolled = router.dispatch(conn_id, "biometric-enroll", "identity.biometrics.enroll", {
        "kind": "face",
        "data_base64": image,
        "mime_type": "image/jpeg",
        "size": len(b"fake-jpeg"),
        # 客户端提交的人物 ID 不参与登记归属判断。
        "person_id": "attacker-selected",
    })
    after = router.dispatch(conn_id, "biometric-status-2", "identity.biometrics.status", {})
    verified = router.dispatch(conn_id, "biometric-verify", "identity.biometrics.verify", {
        "kind": "face",
        "data_base64": image,
        "mime_type": "image/jpeg",
        "size": len(b"fake-jpeg"),
        # 验证目标同样只能来自已认证连接。
        "person_id": "attacker-selected",
    })

    try:
        assert unauthorized["error"]["code"] == -32001
        assert before["result"]["person_id"] == person_id
        assert before["result"]["face_enrolled"] is False
        assert enrolled["result"]["person_id"] == person_id
        assert living._people_biometrics.last_face_person == person_id
        assert after["result"]["face_enrolled"] is True
        assert verified["result"] == {"matched": True, "kind": "face"}
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)


def test_failed_signature_consumes_challenge(tmp_path):
    living = _Living(tmp_path / "brain.db")
    router = MethodRouter(living=living)
    conn_id = "failed-signature"
    private_key, public_key = _identity_key()
    wrong_key, _ = _identity_key()
    _connect(router, conn_id, "session-1")
    begin = router.dispatch(conn_id, "register-1", "identity.register.begin", {
        "display_name": "李白",
        "public_key": public_key,
    })
    params = {
        "challenge_id": begin["result"]["challenge_id"],
        "signature": _sign(wrong_key, begin["result"]["challenge"]),
    }
    failed = router.dispatch(
        conn_id, "register-2", "identity.register.complete", params,
    )
    replayed = router.dispatch(
        conn_id,
        "register-3",
        "identity.register.complete",
        {
            **params,
            "signature": _sign(private_key, begin["result"]["challenge"]),
        },
    )

    try:
        assert failed["error"]["code"] == -32001
        assert replayed["error"]["code"] == -32001
        assert living._people_service.store.list_people() == []
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)


def test_challenge_is_bound_to_connection_and_purpose():
    challenges = ChallengeManager(ttl_seconds=10)
    pending = challenges.begin(
        "connection-1",
        "identity.authenticate",
        {},
        now=100.0,
    )

    try:
        challenges.consume(
            pending.challenge_id,
            "connection-2",
            "identity.authenticate",
            now=101.0,
        )
    except ChallengeError as exc:
        assert "当前连接" in str(exc)
    else:
        raise AssertionError("challenge 不应允许跨连接使用")

    # 跨连接尝试后 challenge 已销毁，原连接也不能重放。
    try:
        challenges.consume(
            pending.challenge_id,
            "connection-1",
            "identity.authenticate",
            now=102.0,
        )
    except ChallengeError as exc:
        assert "已使用" in str(exc)
    else:
        raise AssertionError("challenge 不应允许重放")


def test_new_identity_cannot_claim_legacy_session_history(tmp_path):
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO messages (user_id, session_id, content) VALUES (?, ?, ?)",
        ("legacy-person", "legacy-session", "旧消息"),
    )
    conn.commit()
    conn.close()

    living = _Living(db_path)
    router = MethodRouter(living=living)
    conn_id = "legacy-claim"
    _, public_key = _identity_key()
    _connect(router, conn_id, "legacy-session")
    response = router.dispatch(
        conn_id,
        "register-1",
        "identity.register.begin",
        {"display_name": "新人物", "public_key": public_key},
    )

    try:
        assert response["error"]["code"] == -32001
        assert living._people_service.store.list_people() == []
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)


def test_remote_connection_cannot_register_new_person(tmp_path):
    living = _Living(tmp_path / "brain.db")
    router = MethodRouter(living=living)
    conn_id = "remote-registration"
    _, public_key = _identity_key()
    ws = SimpleNamespace(client=SimpleNamespace(host="10.0.0.8"))
    cm.register(conn_id, ws)
    _connect(router, conn_id, "session-1")

    response = router.dispatch(
        conn_id,
        "register-1",
        "identity.register.begin",
        {"display_name": "远程人物", "public_key": public_key},
    )

    try:
        assert response["error"]["code"] == -32001
        assert "本机" in response["error"]["message"]
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)


def test_local_authenticated_person_can_explicitly_claim_legacy_session(tmp_path):
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute(
        """
        INSERT INTO messages (
            user_id, session_id, role, content, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("legacy-person", "legacy-session", "user", "以前的消息", 1.0),
    )
    conn.commit()
    conn.close()

    living = _Living(db_path)
    router = MethodRouter(living=living)
    conn_id = "local-legacy-management"
    private_key, public_key = _identity_key()
    _connect(router, conn_id, "fresh-session")
    begin = router.dispatch(
        conn_id,
        "register-1",
        "identity.register.begin",
        {"display_name": "李白", "public_key": public_key},
    )
    registered = router.dispatch(
        conn_id,
        "register-2",
        "identity.register.complete",
        {
            "challenge_id": begin["result"]["challenge_id"],
            "signature": _sign(private_key, begin["result"]["challenge"]),
        },
    )
    person_id = registered["result"]["person"]["person_id"]

    listed = router.dispatch(
        conn_id,
        "legacy-list",
        "identity.legacy_sessions.list",
        {},
    )
    claimed = router.dispatch(
        conn_id,
        "legacy-claim",
        "identity.legacy_sessions.claim",
        {"session_id": "legacy-session"},
    )

    try:
        assert listed["result"]["sessions"][0]["session_id"] == "legacy-session"
        assert claimed["result"]["claimed"] is True
        session = living._people_service.store.get_session("legacy-session")
        assert session is not None
        assert session.scope_id == person_id
        row = living._people_service.store._get_conn().execute(
            "SELECT user_id, content FROM messages WHERE session_id = ?",
            ("legacy-session",),
        ).fetchone()
        assert tuple(row) == ("legacy-person", "以前的消息")
    finally:
        router.drop_session(conn_id)
        cm.unregister(conn_id)
