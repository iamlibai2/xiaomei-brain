from xiaomei_brain.consciousness.turn_registry import ActiveTurnRegistry


def test_turn_snapshot_preserves_order_and_isolation():
    registry = ActiveTurnRegistry()
    registry.start("session-1", "turn-1")
    registry.append_text("session-1", "turn-1", "先查一下")
    registry.tool_event("tool.start", {
        "tool_call_id": "call-1",
        "name": "shell",
        "arguments": {"command": "echo ok"},
    }, "session-1", "turn-1")
    registry.tool_event("tool.complete", {
        "tool_call_id": "call-1",
        "name": "shell",
        "summary": "ok",
        "truncated": False,
    }, "session-1", "turn-1")
    registry.append_text("session-1", "turn-1", "完成")

    snapshot = registry.snapshot("session-1")
    assert snapshot is not None
    assert snapshot["status"] == "running"
    assert [item["type"] for item in snapshot["items"]] == ["message", "tool", "message"]
    assert snapshot["items"][1]["id"] == "call-1"
    assert snapshot["items"][1]["status"] == "complete"

    snapshot["items"].clear()
    assert len(registry.snapshot("session-1")["items"]) == 3


def test_interaction_changes_resumable_turn_state():
    registry = ActiveTurnRegistry()
    registry.start("session-1", "turn-1")
    payload = {
        "id": "interaction-1",
        "question": "继续吗？",
        "choices": ["继续", "停止"],
        "session_id": "session-1",
        "turn_id": "turn-1",
        "status": "pending",
        "response": "",
    }

    registry.interaction_event("interaction.requested", payload)
    assert registry.snapshot("session-1")["status"] == "waiting_user"

    registry.interaction_event("interaction.updated", {
        **payload,
        "status": "answered",
        "response": "继续",
    })
    snapshot = registry.snapshot("session-1")
    assert snapshot["status"] == "running"
    assert snapshot["items"][0]["response"] == "继续"

    registry.complete("session-1", "turn-1")
    assert registry.snapshot("session-1") is None
