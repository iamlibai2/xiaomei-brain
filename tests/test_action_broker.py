import threading

from xiaomei_brain.consciousness.action_broker import ActionBroker


def test_action_approval_is_bound_to_session_and_turn_and_seals_arguments():
    published = []
    proposed = threading.Event()

    def publish(event, payload):
        published.append((event, payload))
        if event == "action.proposed":
            proposed.set()

    broker = ActionBroker(publish)
    arguments = {"command": "mkdir approval-test"}
    result = []
    worker = threading.Thread(target=lambda: result.append(broker.propose(
        tool_call_id="call-1",
        tool_name="shell",
        arguments=arguments,
        summary="执行 Shell 命令",
        reason="可能修改文件",
        risk_level="medium",
        session_id="session-a",
        user_id="user-a",
        turn_id="turn-a",
        timeout=1,
    )))
    worker.start()
    assert proposed.wait(timeout=1)
    action_id = published[0][1]["id"]
    arguments["command"] = "different command"

    assert not broker.respond(action_id, "allow", "session-b", "turn-a")
    assert not broker.respond(action_id, "allow", "session-a", "turn-b")
    assert broker.respond(action_id, "allow", "session-a", "turn-a")
    worker.join(timeout=1)

    request = result[0]
    assert request.status == "approved"
    assert request.arguments == {"command": "mkdir approval-test"}
    assert broker.complete(action_id, "created", failed=False)
    assert [event for event, _ in published] == ["action.proposed", "action.completed"]
    assert published[-1][1]["status"] == "completed"


def test_rejected_action_completes_without_approval():
    published = []
    proposed = threading.Event()
    broker = ActionBroker(lambda event, payload: (
        published.append((event, payload)),
        proposed.set() if event == "action.proposed" else None,
    ))
    result = []
    worker = threading.Thread(target=lambda: result.append(broker.propose(
        tool_call_id="call-2",
        tool_name="shell",
        arguments={"command": "echo changed > file.txt"},
        summary="执行 Shell 命令",
        reason="可能修改文件",
        risk_level="medium",
        session_id="session-a",
        user_id="user-a",
        turn_id="turn-a",
        timeout=1,
    )))
    worker.start()
    assert proposed.wait(timeout=1)
    action_id = published[0][1]["id"]
    assert broker.respond(action_id, "deny", "session-a", "turn-a")
    worker.join(timeout=1)
    assert result[0].status == "rejected"
    assert broker.complete(action_id, "Blocked: user rejected this action", failed=True)
    assert published[-1][1]["status"] == "rejected"


def test_action_timeout_fails_closed():
    published = []
    broker = ActionBroker(lambda event, payload: published.append((event, payload)))
    request = broker.propose(
        tool_call_id="call-timeout",
        tool_name="shell",
        arguments={"command": "echo late"},
        summary="执行 Shell 命令",
        reason="可能产生副作用",
        risk_level="medium",
        session_id="session-timeout",
        user_id="user",
        turn_id="turn-timeout",
        timeout=0.01,
    )

    assert request.status == "expired"
    assert request.decision == "deny"
    assert [event for event, _ in published] == ["action.proposed", "action.completed"]
    assert not broker.respond(request.id, "allow", "session-timeout", "turn-timeout")
