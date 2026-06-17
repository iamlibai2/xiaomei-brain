"""Tests for tui_v2/command_handler.py -- command registration and dispatch."""

import pytest
from xiaomei_brain.tui_v2.command_handler import CommandHandler, Command, CommandScope


# ── Helpers ───────────────────────────────────────────────────────────

def _make_ch() -> CommandHandler:
    """Create a fresh CommandHandler for each test."""
    return CommandHandler()


# ── register ──────────────────────────────────────────────────────────

def test_register():
    ch = _make_ch()
    ch.register(Command(name="test", description="test", scope=CommandScope.TUI))
    assert "test" in ch._commands


def test_register_override():
    ch = _make_ch()
    ch.register(Command(name="x", description="old", scope=CommandScope.TUI))
    ch.register(Command(name="x", description="new", scope=CommandScope.GATEWAY))
    assert ch._commands["x"].description == "new"
    assert ch._commands["x"].scope == CommandScope.GATEWAY


def test_register_tui():
    ch = _make_ch()
    handler_called = []
    ch.register_tui("clear", "Clear screen", lambda args: handler_called.append(args))
    assert "clear" in ch._commands
    assert ch._commands["clear"].scope == CommandScope.TUI


def test_register_gateway():
    ch = _make_ch()
    ch.register_gateway("fuel", "Add fuel")
    assert "fuel" in ch._commands
    assert ch._commands["fuel"].scope == CommandScope.GATEWAY


# ── is_command ────────────────────────────────────────────────────────

def test_is_command_slash():
    ch = _make_ch()
    ch.register_gateway("fuel", "test")
    assert ch.is_command("/fuel") is True


def test_is_command_unknown():
    ch = _make_ch()
    assert ch.is_command("/unknown") is False


def test_is_command_no_slash():
    ch = _make_ch()
    assert ch.is_command("hello") is False


def test_is_command_bare_slash():
    ch = _make_ch()
    assert ch.is_command("/") is True


# ── execute ───────────────────────────────────────────────────────────

def test_execute_tui_command():
    ch = _make_ch()
    args_received = []
    ch.register_tui("clear", "Clear", lambda a: args_received.append(a))
    result = ch.execute("/clear")
    assert result is True
    assert args_received == [""]


def test_execute_tui_with_args():
    ch = _make_ch()
    args_received = []
    ch.register_tui("say", "Say something", lambda a: args_received.append(a))
    ch.execute("/say hello world")
    assert args_received == ["hello world"]


def test_execute_gateway_command():
    ch = _make_ch()
    sent = []
    ch.set_send_callback(lambda t: sent.append(t))
    ch.register_gateway("fuel", "Add fuel")
    result = ch.execute("/fuel")
    assert result is True
    assert sent == ["/fuel"]


def test_execute_unknown():
    ch = _make_ch()
    result = ch.execute("/unknown")
    assert result is False


def test_execute_bare_slash():
    ch = _make_ch()
    help_called = []
    ch.register_tui("help", "Help", lambda a: help_called.append(a))
    result = ch.execute("/")
    assert result is True
    assert help_called == [""]


def test_execute_not_command():
    ch = _make_ch()
    result = ch.execute("hello")
    assert result is False


def test_execute_gateway_no_callback():
    """Gateway command without callback still returns True."""
    ch = _make_ch()
    ch.register_gateway("fuel", "test")
    result = ch.execute("/fuel")
    assert result is True  # still returns True, just doesn't send


def test_execute_tui_args_case_insensitive():
    ch = _make_ch()
    args_received = []
    ch.register_tui("test", "test", lambda a: args_received.append(a))
    ch.execute("/TEST args")
    assert args_received == ["args"]


# ── list ──────────────────────────────────────────────────────────────

def test_list_all_sorted():
    ch = _make_ch()
    ch.register_gateway("c", "c")
    ch.register_tui("a", "a", lambda: None)
    ch.register_tui("b", "b", lambda: None)
    result = ch.list_all()
    assert [c.name for c in result] == ["a", "b", "c"]


def test_list_tui():
    ch = _make_ch()
    ch.register_tui("a", "a", lambda: None)
    ch.register_gateway("b", "b")
    tui = ch.list_tui()
    assert len(tui) == 1
    assert tui[0].name == "a"


def test_list_gateway():
    ch = _make_ch()
    ch.register_tui("a", "a", lambda: None)
    ch.register_gateway("b", "b")
    gw = ch.list_gateway()
    assert len(gw) == 1
    assert gw[0].name == "b"
