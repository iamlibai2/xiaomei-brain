"""Tests for agent/message_utils.py -- input cleaning and message repair."""

import pytest
from xiaomei_brain.agent.message_utils import (
    clean_input,
    strip_orphaned_tool_messages,
    strip_orphaned_assistant_tool_calls,
    clean_messages,
    estimate_content_tokens,
    append_to_content,
)


# ── clean_input ───────────────────────────────────────────────────

def test_clean_input_normal():
    assert clean_input("hello world") == "hello world"


def test_clean_input_removes_surrogates():
    # \ud800 is a high surrogate
    assert clean_input("he\ud800llo") == "hello"


def test_clean_input_removes_replacement_char():
    assert clean_input("hel\ufffdlo") == "hello"


def test_clean_input_removes_control_chars():
    assert clean_input("he\x00llo") == "hello"
    assert clean_input("he\x01llo") == "hello"
    assert clean_input("he\x1fllo") == "hello"


def test_clean_input_keeps_tab_newline_cr():
    assert clean_input("hello\tworld\n!\r") == "hello\tworld\n!\r"


def test_clean_input_mixed():
    text = "hel\x00lo\ud800\ufffd wo\x01rld\ttest"
    assert clean_input(text) == "hello world\ttest"


def test_clean_input_empty():
    assert clean_input("") == ""


def test_clean_input_cjk():
    assert clean_input("你好世界") == "你好世界"


# ── strip_orphaned_tool_messages ──────────────────────────────────

def test_strip_orphaned_tool_messages_empty():
    assert strip_orphaned_tool_messages([]) == []


def test_strip_orphaned_tool_messages_valid():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
    ]
    result = strip_orphaned_tool_messages(msgs)
    assert len(result) == 2


def test_strip_orphaned_tool_messages_orphaned():
    """Tool message with no matching assistant tool_call → removed."""
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "tc1", "content": "orphan"},
    ]
    result = strip_orphaned_tool_messages(msgs)
    assert len(result) == 1
    assert result[0]["role"] == "user"


def test_strip_orphaned_tool_messages_multiple_orphaned():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "valid"},
        {"role": "tool", "tool_call_id": "tc2", "content": "orphan"},
    ]
    result = strip_orphaned_tool_messages(msgs)
    assert len(result) == 2


def test_strip_orphaned_tool_messages_no_tool_call_id():
    """Tool message without tool_call_id → orphaned, removed."""
    msgs = [
        {"role": "tool", "content": "no tool_call_id"},
    ]
    result = strip_orphaned_tool_messages(msgs)
    assert len(result) == 0


# ── strip_orphaned_assistant_tool_calls ───────────────────────────

def test_strip_orphaned_assistant_tc_empty():
    assert strip_orphaned_assistant_tool_calls([]) == []


def test_strip_orphaned_assistant_tc_complete():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
    ]
    result = strip_orphaned_assistant_tool_calls(msgs)
    assert "tool_calls" in result[0]


def test_strip_orphaned_assistant_tc_missing():
    """Assistant has tool_calls but matching tool response is missing."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
    ]
    result = strip_orphaned_assistant_tool_calls(msgs)
    assert "tool_calls" not in result[0]


def test_strip_orphaned_assistant_tc_wrong_order():
    """Tool call ids match but tool messages are in wrong position."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "user", "content": "interrupting"},  # not a tool message
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
    ]
    result = strip_orphaned_assistant_tool_calls(msgs)
    # The tool response at pos 2 is not immediately after assistant (needs consecutive)
    assert "tool_calls" not in result[0]


def test_strip_orphaned_assistant_tc_multiple_tools():
    """Assistant with 2 tool_calls, both matched → preserved."""
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "tc2", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "r1"},
        {"role": "tool", "tool_call_id": "tc2", "content": "r2"},
    ]
    result = strip_orphaned_assistant_tool_calls(msgs)
    assert "tool_calls" in result[0]


# ── clean_messages ────────────────────────────────────────────────

def test_clean_messages_str_content():
    msgs = [{"role": "user", "content": "hel\ud800lo"}]
    result = clean_messages(msgs)
    assert "\ud800" not in result[0]["content"]


def test_clean_messages_list_content():
    msgs = [
        {"role": "user", "content": [
            {"type": "text", "text": "hel\ud800lo"},
            {"type": "image_url", "image_url": {"url": "http://x.com/img.png"}},
        ]},
    ]
    result = clean_messages(msgs)
    parts = result[0]["content"]
    assert "\ud800" not in parts[0]["text"]
    assert parts[1]["type"] == "image_url"


def test_clean_messages_no_content():
    msgs = [{"role": "system", "name": "test"}]
    result = clean_messages(msgs)
    assert result[0] == msgs[0]


def test_clean_messages_returns_new_list():
    msgs = [{"role": "user", "content": "hello"}]
    result = clean_messages(msgs)
    assert result is not msgs


# ── estimate_content_tokens ───────────────────────────────────────

def test_estimate_content_tokens_none():
    assert estimate_content_tokens(None) == 0


def test_estimate_content_tokens_empty_list():
    assert estimate_content_tokens([]) == 0


def test_estimate_content_tokens_string():
    assert estimate_content_tokens("hello") == 1


def test_estimate_content_tokens_multimodal():
    content = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "http://x.com/img.png"}},
        {"type": "image_url", "image_url": {"url": "http://x.com/img2.png"}},
    ]
    # "hello" = 1 + 2 images * 85 = 171
    assert estimate_content_tokens(content) == 171


# ── append_to_content ─────────────────────────────────────────────

def test_append_to_content_string():
    assert append_to_content("hello", " world") == "hello world"


def test_append_to_content_list_existing_text():
    content = [{"type": "text", "text": "hello"}]
    result = append_to_content(content, " world")
    assert result[0]["text"] == "hello world"


def test_append_to_content_list_no_text():
    content = [{"type": "image_url", "image_url": {"url": "http://x.com/img.png"}}]
    result = append_to_content(content, "hello")
    assert result[0]["type"] == "text"
    assert result[0]["text"] == "hello"


def test_append_to_content_fallback():
    assert append_to_content(42, "hello") == 42
