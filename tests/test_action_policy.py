from xiaomei_brain.tools.action_policy import assess_tool_action


def test_non_command_tools_are_allowed():
    assert assess_tool_action("read", {"path": "notes.txt"}).decision == "allow"


def test_platform_commands_are_automatic_when_safe():
    assert assess_tool_action("powershell", {"command": "Get-Process"}).decision == "allow"
    assert assess_tool_action("bash", {"command": "git status --short"}).decision == "allow"


def test_empty_and_catastrophic_commands_are_denied():
    assert assess_tool_action("powershell", {"command": ""}).decision == "deny"
    assert assess_tool_action("bash", {"command": "rm -rf /"}).decision == "deny"
