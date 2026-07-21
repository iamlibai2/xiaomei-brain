from types import SimpleNamespace

from xiaomei_brain.consciousness.conversation_driver import ConversationDriver
from xiaomei_brain.tools.action_policy import assess_tool_action


def test_non_shell_tools_keep_existing_behavior():
    assert assess_tool_action("read_file", {"path": "notes.txt"}).decision == "allow"


def test_conservative_shell_reads_are_automatic():
    assert assess_tool_action("shell", {"command": "git status --short"}).decision == "allow"
    assert assess_tool_action("shell", {"command": "python --version"}).decision == "allow"


def test_shell_side_effects_require_approval():
    assessment = assess_tool_action("shell", {"command": "mkdir approval-test"})
    assert assessment.decision == "ask"
    assert "mkdir approval-test" in assessment.summary


def test_existing_hard_blocks_never_become_approvable():
    assessment = assess_tool_action("shell", {"command": "powershell -Command Get-Process"})
    assert assessment.decision == "deny"
    assert assessment.risk_level == "high"


def test_non_desktop_channels_fail_closed_instead_of_waiting_for_approval():
    parent = SimpleNamespace(
        _router=SimpleNamespace(
            route_for_session=lambda _session_id: SimpleNamespace(type="http_p2p"),
        ),
    )
    callback = ConversationDriver._make_tool_approval_callback(
        "comms-xiaomei", "turn-1", "user", parent,
    )

    result = callback("call-1", "shell", {"command": "echo side-effect"})

    assert result["approved"] is False
    assert "interactive Desktop" in result["result"]
