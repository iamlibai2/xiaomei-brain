"""Tests for tui_v2/tool_card.py -- ToolCard states and passive detection."""

import pytest
from unittest.mock import patch
from xiaomei_brain.tui_v2.tool_card import (
    ToolState,
    ToolCard,
    detect_tool_calls,
    detect_tool_results,
)


# ── ToolState ─────────────────────────────────────────────────────────

def test_tool_state_values():
    assert ToolState.PENDING.value == "pending"
    assert ToolState.SUCCESS.value == "success"
    assert ToolState.ERROR.value == "error"


# ── ToolCard ──────────────────────────────────────────────────────────

def test_tool_card_defaults():
    tc = ToolCard(tool_id=1, name="calculator")
    assert tc.tool_id == 1
    assert tc.name == "calculator"
    assert tc.args == ""
    assert tc.state == ToolState.PENDING
    assert tc.result_summary == ""


def test_tool_card_icon_pending():
    tc = ToolCard(tool_id=1, name="test", state=ToolState.PENDING)
    assert tc.icon == "\u22ef"  # ⋯


def test_tool_card_icon_success():
    tc = ToolCard(tool_id=1, name="test", state=ToolState.SUCCESS)
    assert tc.icon == "\u2713"  # ✓


def test_tool_card_icon_error():
    tc = ToolCard(tool_id=1, name="test", state=ToolState.ERROR)
    assert tc.icon == "\u2717"  # ✗


def test_tool_card_elapsed_pending():
    tc = ToolCard(tool_id=1, name="test", state=ToolState.PENDING)
    # elapsed calls time.monotonic(), should be >= 0
    assert tc.elapsed >= 0


def test_tool_card_elapsed_done():
    tc = ToolCard(tool_id=1, name="test", state=ToolState.SUCCESS)
    assert tc.elapsed == 0.0


# ── detect_tool_calls ─────────────────────────────────────────────────

def test_detect_tool_calls_chinese():
    text = "让我调用 calculator：{\"expr\": \"1+1\"}"
    results = detect_tool_calls(text)
    assert len(results) == 1
    assert results[0]["name"] == "calculator"


def test_detect_tool_calls_english():
    text = "calling web_search with {\"query\": \"AI\"}"
    results = detect_tool_calls(text)
    assert len(results) == 1
    assert results[0]["name"] == "web_search"


def test_detect_tool_calls_using():
    text = "使用 memory_write: {\"content\": \"note\"}"
    results = detect_tool_calls(text)
    assert len(results) == 1
    assert results[0]["name"] == "memory_write"


def test_detect_tool_calls_no_match():
    text = "hello, how are you?"
    results = detect_tool_calls(text)
    assert results == []


def test_detect_tool_calls_multiple():
    text = "调用 calculator: {\"expr\": \"1+1\"} and using search: {\"query\": \"x\"}"
    results = detect_tool_calls(text)
    assert len(results) == 2


# ── detect_tool_results ───────────────────────────────────────────────

def test_detect_tool_results_basic():
    text = '```json\n{"result": "42"}\n```'
    results = detect_tool_results(text)
    assert len(results) == 1


def test_detect_tool_results_no_match():
    text = "hello world"
    results = detect_tool_results(text)
    assert results == []
