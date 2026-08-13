from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.gateway.methods.model_traces import ModelTraceMethods
from xiaomei_brain.llm.trace_store import ModelTraceStore, sanitize_model_payload


def test_sanitize_redacts_secrets_and_collapses_data_urls() -> None:
    value = sanitize_model_payload({
        "api_key": "secret-value",
        "arguments": '{"password": "hidden", "query": "hello"}',
        "messages": [{
            "role": "user",
            "content": [{
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,aGVsbG8="},
            }],
        }],
    })

    assert value["api_key"] == "[REDACTED]"
    assert "hidden" not in value["arguments"]
    assert "hello" in value["arguments"]
    image = value["messages"][0]["content"][0]["image_url"]["url"]
    assert image["_type"] == "binary"
    assert image["mime_type"] == "image/png"
    assert image["size"] == 5


def test_trace_store_records_request_response_and_filters(tmp_path) -> None:
    events: list[tuple[str, dict]] = []
    store = ModelTraceStore(tmp_path, on_change=lambda name, payload: events.append((name, payload)))
    trace_id = store.begin({
        "provider": "openai-compatible",
        "model": "example-model",
        "session_id": "session-a",
        "turn_id": "turn-a",
        "category": "conversation",
        "stream": True,
        "execution_selection": {
            "step": 0,
            "skills": [{"name": "document-writing", "source": "semantic"}],
            "discovery": {
                "prefetch": {"skills": [{"name": "document-writing"}]},
                "active": {
                    "query": "write a report",
                    "loaded_skill": {
                        "name": "document-writing",
                        "content": "must not be copied into trace summaries",
                    },
                    "activated_tools": [{"name": "write_document"}],
                },
            },
            "tools": {"core": ["read"], "required": [], "semantic": ["write"]},
        },
        "request": {
            "messages": [
                {"role": "system", "content": "You are an Agent."},
                {"role": "user", "content": "  Analyze   this report.  "},
                {"role": "assistant", "tool_calls": [{"function": {"name": "read"}}]},
            ],
            "tools": [{"type": "function", "function": {"name": "read"}}],
        },
    })
    store.complete(trace_id, response={
        "content": "ok",
        "tool_calls": [{"name": "read", "arguments": "{}"}],
        "usage": {
            "input_tokens": 9,
            "output_tokens": 3,
            "total_tokens": 12,
        },
    }, latency_ms=42)

    record = store.get(trace_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["request"]["messages"][0]["content"] == "You are an Agent."
    listed = store.list_records(session_id="session-a")
    assert listed["total"] == 1
    assert listed["items"][0]["tool_count"] == 1
    assert listed["items"][0]["tool_call_count"] == 1
    assert listed["items"][0]["tool_call_names"] == ["read"]
    assert listed["items"][0]["prompt_preview"] == "Analyze this report."
    assert listed["items"][0]["input_tokens"] == 9
    assert listed["items"][0]["output_tokens"] == 3
    assert listed["items"][0]["total_tokens"] == 12
    assert listed["items"][0]["execution_selection"]["skills"][0]["name"] == "document-writing"
    active = listed["items"][0]["execution_selection"]["discovery"]["active"]
    assert active["loaded_skill"] == {"name": "document-writing"}
    assert "content" not in active["loaded_skill"]
    assert "query" not in listed["items"][0]["execution_selection"]
    assert [event[0] for event in events] == ["model.trace.created", "model.trace.updated"]


def test_trace_store_counts_provider_top_level_system_message(tmp_path) -> None:
    store = ModelTraceStore(tmp_path)
    store.begin({
        "model": "anthropic-style",
        "request": {
            "system": "Agent identity and memory context",
            "messages": [{"role": "user", "content": "hello"}],
        },
    })
    listed = store.list_records()
    assert listed["items"][0]["message_count"] == 2


def test_gateway_model_trace_methods(tmp_path) -> None:
    store = ModelTraceStore(tmp_path)
    trace_id = store.begin({"model": "m", "request": {"messages": [], "tools": []}})
    methods = ModelTraceMethods(SimpleNamespace(model_trace_store=store))

    listed = methods.handle_list("conn", "req-list", {"limit": 10})
    assert listed["result"]["total"] == 1
    detail = methods.handle_get("conn", "req-get", {"trace_id": trace_id})
    assert detail["result"]["trace"]["id"] == trace_id
    cleared = methods.handle_clear("conn", "req-clear", {})
    assert cleared["result"]["removed"] == 1
