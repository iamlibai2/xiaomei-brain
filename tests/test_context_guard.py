from xiaomei_brain.agent.context_guard import _trim_messages


def _assistant_call(*call_ids: str, content: str = "") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "test_tool", "arguments": "{}"},
            }
            for call_id in call_ids
        ],
    }


def _tool_result(call_id: str, content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_trim_keeps_multi_tool_exchange_as_one_atomic_unit():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old " * 200},
        _assistant_call("call-1", "call-2"),
        _tool_result("call-1"),
        _tool_result("call-2"),
        {"role": "assistant", "content": "done"},
    ]

    trimmed = _trim_messages(messages, max_tokens=80)

    assert [message["role"] for message in trimmed] == [
        "system",
        "assistant",
        "tool",
        "tool",
        "assistant",
    ]
    assert trimmed[1]["tool_calls"][0]["id"] == "call-1"
    assert trimmed[2]["tool_call_id"] == "call-1"
    assert trimmed[3]["tool_call_id"] == "call-2"


def test_trim_drops_entire_multi_tool_exchange_when_it_does_not_fit():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old"},
        _assistant_call("call-1", "call-2"),
        _tool_result("call-1", "large " * 200),
        _tool_result("call-2", "large " * 200),
        {"role": "assistant", "content": "latest"},
    ]

    trimmed = _trim_messages(messages, max_tokens=30)

    assert trimmed == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "latest"},
    ]


def test_context_guard_removes_orphan_tool_results_even_without_trimming():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        _tool_result("missing-call"),
        {"role": "assistant", "content": "answer"},
    ]

    guarded = _trim_messages(messages, max_tokens=1000)

    assert guarded == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "answer"},
    ]


def test_context_guard_strips_incomplete_tool_call_and_results():
    messages = [
        {"role": "system", "content": "system"},
        _assistant_call("call-1", "call-2", content="working"),
        _tool_result("call-1"),
    ]

    guarded = _trim_messages(messages, max_tokens=1000)

    assert guarded == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "working"},
    ]
