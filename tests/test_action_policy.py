from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.gateway.channel_adapter import ChannelCapabilities
from xiaomei_brain.tools.action_policy import assess_tool_action


def test_non_shell_tools_keep_existing_behavior():
    assert assess_tool_action("read_file", {"path": "notes.txt"}).decision == "allow"


def test_shell_commands_are_automatic_when_not_hard_blocked():
    assert assess_tool_action("shell", {"command": "git status --short"}).decision == "allow"
    assert assess_tool_action("shell", {"command": "python --version"}).decision == "allow"
    assert assess_tool_action("shell", {"command": "mkdir approval-test"}).decision == "allow"


def test_existing_hard_blocks_never_become_approvable():
    assessment = assess_tool_action("shell", {"command": "powershell -Command Get-Process"})
    assert assessment.decision == "deny"
    assert assessment.risk_level == "high"


def test_non_desktop_channels_execute_allowed_shell_without_approval():
    parent = SimpleNamespace(
        _router=SimpleNamespace(
            route_for_session=lambda _session_id: SimpleNamespace(type="http_p2p"),
        ),
    )
    callback = ConversationDriver._make_tool_approval_callback(
        "comms-xiaomei", "turn-1", "user", parent,
    )

    result = callback("call-1", "shell", {"command": "echo side-effect"})

    assert result is None


def test_allowed_shell_does_not_create_action_broker_request():
    captured = {}

    class Broker:
        def propose(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id="action-1", status="approved", error="")

    adapter = SimpleNamespace(
        capabilities=ChannelCapabilities(action_approval=True),
    )
    router = SimpleNamespace(
        route_for_session=lambda _session_id: SimpleNamespace(type="feishu"),
        get_adapter=lambda _channel: adapter,
    )
    parent = SimpleNamespace(_router=router, _action_broker=Broker())
    callback = ConversationDriver._make_tool_approval_callback(
        "feishu-user-1", "turn-1", "user-1", parent,
    )

    result = callback("call-1", "shell", {"command": "mkdir approval-test"})

    assert result is None
    assert captured == {}
