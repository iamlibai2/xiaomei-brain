from types import SimpleNamespace

from xiaomei_brain.cli.local_commands import execute_local_command


class _IdentityManager:
    def __init__(self):
        self._items = {
            "person-a": {"name": "甲"},
            "person-b": {"name": "乙"},
        }

    def resolve(self, value):
        if value in self._items:
            return self._items[value]
        for item in self._items.values():
            if item["name"] == value:
                return item
        return None

    def list_ids(self):
        return list(self._items)

    def get_display_name(self, value):
        item = self.resolve(value)
        return item["name"] if item else value


class _ConversationDB:
    def get_session_ids(self):
        return ["session-a", "session-b"]

    def count(self, session_id):
        return 7 if session_id == "session-b" else 3


def _living():
    core = SimpleNamespace(user_id="core-user", session_id="core-session")
    agent = SimpleNamespace(
        commands=None,
        conversation_db=_ConversationDB(),
        _get_agent=lambda: core,
    )
    return SimpleNamespace(agent=agent, _intent_commands={}), core


def test_user_switch_is_returned_without_mutating_shared_core():
    living, core = _living()

    result = execute_local_command(
        living,
        "/user 乙",
        user_id="person-a",
        session_id="session-a",
        identity_mgr=_IdentityManager(),
    )

    assert result.handled is True
    assert result.user_id == "person-b"
    assert core.user_id == "core-user"
    assert core.session_id == "core-session"


def test_session_switch_is_returned_without_mutating_shared_core():
    living, core = _living()

    result = execute_local_command(
        living,
        "/switch session-b",
        user_id="person-a",
        session_id="session-a",
        identity_mgr=_IdentityManager(),
    )

    assert result.handled is True
    assert result.session_id == "session-b"
    assert core.user_id == "core-user"
    assert core.session_id == "core-session"


def test_unknown_slash_text_is_left_for_normal_chat():
    living, _ = _living()

    result = execute_local_command(
        living,
        "/not-a-command hello",
        user_id="person-a",
        session_id="session-a",
        identity_mgr=_IdentityManager(),
    )

    assert result.handled is False
