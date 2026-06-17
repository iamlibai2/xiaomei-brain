"""Tests for base/message_utils.py -- pure token estimation and message scrubbing."""

import pytest
from xiaomei_brain.base.message_utils import estimate_tokens, scrub_tool_calls_incomplete


# ── estimate_tokens ───────────────────────────────────────────────

def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_none():
    assert estimate_tokens(None) == 0


def test_estimate_tokens_ascii():
    # "hello" = 5 chars → 5/4 = 1.25 → int → 1
    assert estimate_tokens("hello") == 1


def test_estimate_tokens_cjk():
    # "你好世界" = 4 CJK chars → 4 * 1.5 = 6
    assert estimate_tokens("你好世界") == 6


def test_estimate_tokens_mixed():
    # "hello你好" = 5 ascii + 2 cjk → 5/4 + 2*1.5 = 1 + 3 = 4
    assert estimate_tokens("hello你好") == 4


def test_estimate_tokens_cjk_boundary_start():
    # U+4E00 is the first CJK unified ideograph
    assert estimate_tokens("\u4e00") == 1  # 1 * 1.5 = 1.5 → int → 1


def test_estimate_tokens_cjk_boundary_end():
    # U+9FFF is the last CJK unified ideograph
    assert estimate_tokens("\u9fff") == 1


def test_estimate_tokens_not_cjk():
    # U+4DFF is just below the CJK range — treated as ASCII (counted /4)
    assert estimate_tokens("\u4dff") == 0  # 1/4 = 0


def test_estimate_tokens_long_text():
    # 100 ASCII chars → 100/4 = 25
    assert estimate_tokens("a" * 100) == 25


# ── scrub_tool_calls_incomplete ───────────────────────────────────

def test_scrub_empty():
    assert scrub_tool_calls_incomplete([]) == []


def test_scrub_no_tool_calls():
    msgs = [{"role": "user", "content": "hello"}]
    assert scrub_tool_calls_incomplete(msgs) == msgs


def test_scrub_no_assistant():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    # All messages preserved; no assistant to have incomplete tool_calls
    assert len(result) == 2


def test_scrub_incomplete_stripped():
    """Assistant with 1 tool_call but no tool response → tool_calls stripped."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert "tool_calls" not in result[0]


def test_scrub_complete_preserved():
    """Assistant with 1 tool_call + matching tool response → preserved."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert "tool_calls" in result[0]
    assert result[0]["tool_calls"][0]["id"] == "tc1"


def test_scrub_partial_stripped():
    """Assistant with 2 tool_calls, only 1 has response → entire tool_calls stripped."""
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "tc2", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "result1"},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert "tool_calls" not in result[0]


def test_scrub_multiple_assistants():
    """First assistant complete, second incomplete → first preserved, second stripped."""
    msgs = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "result1"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "tc2", "type": "function", "function": {"name": "y", "arguments": "{}"}}],
        },
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert "tool_calls" in result[0]
    assert "tool_calls" not in result[2]


def test_scrub_returns_new_list():
    """Original list not mutated."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert result is not msgs
    assert "tool_calls" in msgs[0]  # original still has tool_calls


def test_scrub_no_tool_call_id():
    """Tool call without id → id="" → not in tool_response_ids → stripped."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"type": "function", "function": {"name": "x", "arguments": "{}"}}]},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    # tool_calls element has no id → tc_id="" not in tool_response_ids → missing → stripped
    assert "tool_calls" not in result[0]


def test_scrub_tool_response_not_matching():
    """Tool response with id that doesn't match any assistant tool_call."""
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_other", "content": "result"},
    ]
    result = scrub_tool_calls_incomplete(msgs)
    assert "tool_calls" not in result[0]
