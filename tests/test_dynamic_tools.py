"""Tests for DynamicToolLoader (Tool RAG)."""

import pytest

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.dynamic import (
    DynamicToolLoader,
    set_active_loader,
    notify_tools_changed,
    DEFAULT_TOP_K,
)


def _make_tool(name: str, description: str, category: str = "test") -> Tool:
    return Tool(
        name=name,
        description=description,
        category=category,
        parameters={},
        func=lambda: None,
    )


def _registry_with_tools(*names_and_descs) -> ToolRegistry:
    reg = ToolRegistry()
    for name, desc in names_and_descs:
        reg.register(_make_tool(name, desc))
    return reg


# ── Basic loading ──────────────────────────────────────────────


def test_build_index_empty():
    reg = ToolRegistry()
    loader = DynamicToolLoader(reg)
    loader.build_index()
    assert loader.select_tools("anything") == []


def test_build_index_with_tools():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("web_search", "Search the web"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()
    tools = loader.select_tools("search")
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "shell" in names
    assert "web_search" in names


# ── Core tools always present ──────────────────────────────────


def test_core_tools_always_included():
    """Core tools must appear in every selection regardless of query."""
    from xiaomei_brain.tools.dynamic import _CORE_TOOL_NAMES

    reg = ToolRegistry()
    for name in _CORE_TOOL_NAMES:
        reg.register(_make_tool(name, f"{name} tool"))
    reg.register(_make_tool("unrelated", "Something completely unrelated"))

    loader = DynamicToolLoader(reg)
    loader.build_index()

    # Query totally unrelated to core tools
    tools = loader.select_tools("completely unrelated topic xyz", top_k=1)
    names = [t.name for t in tools]

    for core in _CORE_TOOL_NAMES:
        assert core in names, f"Core tool '{core}' missing from selection"


def test_core_tools_first():
    """Core tools should appear before dynamic tools."""
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("web_search", "Search the web"),
        ("navigate_page", "Navigate browser"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()
    tools = loader.select_tools("search the web", top_k=2)
    names = [t.name for t in tools]
    # Core tools must come first
    core = ["shell", "send_message"]
    assert names[:len(core)] == core, f"Expected core tools first, got {names}"


# ── Dynamic tool selection ─────────────────────────────────────


def test_relevant_tools_ranked_higher():
    """Query should surface related tools over unrelated ones."""
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("web_search", "Search the internet with Baidu search engine"),
        ("navigate_page", "Navigate browser to a URL"),
        ("take_screenshot", "Take a screenshot of the current page"),
        ("play_music", "Play music from library"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    # "search the internet" should rank web_search above browser/music tools
    tools = loader.select_tools("search the internet for news", top_k=2)
    dynamic = [t.name for t in tools if t.name not in
               ("shell", "send_message", "read_file", "write_file", "edit_file",
                "check_inbox", "memory_search", "memory_add", "memory_list", "dag")]
    assert "web_search" in dynamic, f"web_search should be selected, got {dynamic}"


def test_browser_query_ranks_browser_tools():
    """Browser-related query should surface browser tools."""
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("web_search", "Search the internet"),
        ("navigate_page", "Navigate browser to a URL and load the page"),
        ("take_screenshot", "Take a screenshot of the browser page"),
        ("play_music", "Play music"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    tools = loader.select_tools("open baidu and take a screenshot", top_k=2)
    dynamic = [t.name for t in tools if t.name not in
               ("shell", "send_message", "read_file", "write_file", "edit_file",
                "check_inbox", "memory_search", "memory_add", "memory_list", "dag")]
    assert len(dynamic) > 0
    # Browser tools should be preferred over music
    assert dynamic[0] in ("navigate_page", "take_screenshot"), \
        f"Expected browser tool first in dynamic, got {dynamic}"


# ── Rebuild ────────────────────────────────────────────────────


def test_rebuild_picks_up_new_tools():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("web_search", "Search the web"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    reg.register(_make_tool("new_mcp_tool", "A brand new MCP tool"))
    loader.rebuild()

    tools = loader.select_tools("brand new mcp tool", top_k=3)
    names = [t.name for t in tools]
    assert "new_mcp_tool" in names, f"rebuild should pick up new tool, got {names}"


def test_notify_tools_changed_triggers_rebuild():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()
    set_active_loader(loader)

    reg.register(_make_tool("added_later", "Added after init"))
    notify_tools_changed()

    tools = loader.select_tools("added later", top_k=3)
    names = [t.name for t in tools]
    assert "added_later" in names, f"notify_tools_changed should rebuild, got {names}"


# ── Context accumulation simulation ────────────────────────────


def test_context_accumulation_improves_selection():
    """Simulate per-step context accumulation like stream()/react_nodb()."""
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("navigate_page", "Navigate browser to URL"),
        ("fill_form", "Fill a form field on the page"),
        ("click_button", "Click a button on the page"),
        ("play_music", "Play music"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    # Step 1: initial task
    ctx = "open baidu and search for python"
    tools1 = loader.select_tools(ctx, top_k=2)
    dynamic1 = [t.name for t in tools1 if t.name not in
                ("shell", "send_message", "read_file", "write_file", "edit_file",
                 "check_inbox", "memory_search", "memory_add", "memory_list", "dag")]
    assert "navigate_page" in dynamic1

    # Step 2: after navigation, need to fill form
    ctx += "\nnavigate_page: Navigated to baidu.com, page loaded with search form"
    tools2 = loader.select_tools(ctx, top_k=2)
    dynamic2 = [t.name for t in tools2 if t.name not in
                ("shell", "send_message", "read_file", "write_file", "edit_file",
                 "check_inbox", "memory_search", "memory_add", "memory_list", "dag")]
    # fill_form or click_button should now be ranked higher
    browser_actions = {"fill_form", "click_button", "navigate_page"}
    assert set(dynamic2) & browser_actions, \
        f"Step 2 should surface form/click tools, got {dynamic2}"


# ── OpenAI format ──────────────────────────────────────────────


def test_select_openai_tools():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("web_search", "Search the web"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    result = loader.select_openai_tools("search")
    assert isinstance(result, list)
    assert len(result) > 0
    for item in result:
        assert item["type"] == "function"
        assert "name" in item["function"]
        assert "description" in item["function"]
        assert "parameters" in item["function"]


# ── Top-K control ──────────────────────────────────────────────


def test_top_k_respected():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("tool_a", "Description A"),
        ("tool_b", "Description B"),
        ("tool_c", "Description C"),
        ("tool_d", "Description D"),
        ("tool_e", "Description E"),
        ("tool_f", "Description F"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    # top_k=1: 2 core + 1 dynamic = 3 total
    tools = loader.select_tools("description", top_k=1)
    dynamic_count = len([t for t in tools if t.name not in
                         ("shell", "send_message", "read_file", "write_file", "edit_file",
                          "check_inbox", "memory_search", "memory_add", "memory_list", "dag")])
    assert dynamic_count <= 1, f"top_k=1 should yield at most 1 dynamic, got {dynamic_count}"


# ── Fallback when _dynamic_loader is None ──────────────────────


def test_no_loader_returns_all():
    """When _dynamic_loader is None, to_openai_tools() returns all tools."""
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("send_message", "Send a message"),
        ("web_search", "Search"),
    )
    all_openai = reg.to_openai_tools()
    assert len(all_openai) == 3


# ── Step growth ────────────────────────────────────────────────


def test_step_growth():
    """Dynamic tool slots grow by STEP_GROWTH each step, capped at MAX_DYNAMIC."""
    from xiaomei_brain.tools.dynamic import STEP_GROWTH, MAX_DYNAMIC

    # Create many tools so we're not limited by registry size
    tools = [("shell", "Run shell commands"), ("send_message", "Send a message")]
    for i in range(MAX_DYNAMIC + 10):
        tools.append((f"tool_{i}", f"Tool number {i} for testing"))
    reg = _registry_with_tools(*tools)

    loader = DynamicToolLoader(reg)
    loader.build_index()

    def dynamic_count(t, step):
        selected = loader.select_tools("testing", top_k=t, step=step)
        return len([s for s in selected if s.name not in
                    ("shell", "send_message", "read_file", "write_file", "edit_file",
                     "check_inbox", "memory_search", "memory_add", "memory_list", "dag")])

    # Step 0: base top_k
    assert dynamic_count(10, step=0) == 10

    # Step 1: base + 3
    assert dynamic_count(10, step=1) == 13

    # Step 5: base + 15 = 25
    assert dynamic_count(10, step=5) == 25

    # Step 20: base + 60 = 70, but capped at MAX_DYNAMIC=50
    assert dynamic_count(10, step=20) == MAX_DYNAMIC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
