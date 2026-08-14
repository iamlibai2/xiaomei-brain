"""Tests for DynamicToolLoader (Tool RAG)."""

import pytest
from unittest.mock import MagicMock

from xiaomei_brain.agent.core import Agent
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.dynamic import (
    DynamicToolLoader,
    build_step_tool_selection_context,
    build_tool_selection_context,
    create_tool_search_tool,
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


def test_tool_selection_context_keeps_recent_user_intent_and_attachments():
    messages = [
        {"role": "user", "content": "做一个有图片的 Word 文件"},
        {"role": "assistant", "content": "错误判断：我没有 write_document"},
        {"role": "user", "content": "图片需要居中并添加图注"},
        {"role": "assistant", "content": "请把图片发给我"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "那你用这个图片"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,SHOULD_NOT_APPEAR"},
                },
            ],
        },
    ]
    attachments = [{
        "name": "screen.png",
        "mime_type": "image/png",
        "kind": "image",
    }]

    context = build_tool_selection_context(messages, attachments)

    assert "那你用这个图片" in context
    assert "做一个有图片的 Word 文件" in context
    assert "图片需要居中并添加图注" in context
    assert "screen.png" in context
    assert "image/png" in context
    assert "错误判断" not in context
    assert "SHOULD_NOT_APPEAR" not in context


def test_tool_selection_context_uses_only_latest_three_user_messages():
    messages = [
        {"role": "user", "content": "旧话题：播放音乐"},
        {"role": "user", "content": "制作季度报告"},
        {"role": "user", "content": "输出 Word 文档"},
        {"role": "user", "content": "继续"},
    ]

    context = build_tool_selection_context(messages)

    assert "旧话题" not in context
    assert "制作季度报告" in context
    assert "输出 Word 文档" in context
    assert "继续" in context


def test_tool_selection_context_removes_transport_timestamps_from_user_intent():
    messages = [
        {"role": "user", "content": "距上条消息 2分钟 hi"},
        {"role": "user", "content": "[08-11 23:31] hello"},
    ]

    context = build_tool_selection_context(messages)

    assert "距上条消息" not in context
    assert "2分钟" not in context
    assert "08-11 23:31" not in context
    assert "hi" in context
    assert "hello" in context


def test_tool_selection_context_is_bounded():
    messages = [
        {"role": "user", "content": "A" * 1000},
        {"role": "user", "content": "B" * 1000},
        {"role": "user", "content": "C" * 1000},
    ]

    context = build_tool_selection_context(messages, max_chars=400)

    assert len(context) <= 400
    assert "C" * 100 in context
    assert "Current user request" not in context
    assert "Recent user context" not in context


def test_step_selection_context_excludes_tool_progress():
    original = "Current user request:\n分析销售数据并生成图表"
    context = build_step_tool_selection_context(
        original,
        ["read_document: " + "old" * 500, "analyze_data: latest result"],
    )

    assert context == original
    assert "read_document" not in context
    assert "analyze_data" not in context


def test_agent_refreshes_runtime_tool_context_after_first_step():
    from xiaomei_brain.agent.render_execution_context import prepare_execution_selection

    agent = Agent(llm=object(), tools=ToolRegistry())
    state = {"focused": False}

    def workspace_context(_agent, _query):
        if not state["focused"]:
            return ""
        return (
            '<focused_workspace>{"id":"workspace-1",'
            '"name":"原料采购"}</focused_workspace>'
        )

    agent.add_tool_selection_context_provider(workspace_context)
    _messages, initial = prepare_execution_selection(agent, [
        {"role": "user", "content": "新建一个原料采购工作空间"},
    ])
    assert "focused_workspace" not in initial

    state["focused"] = True
    from xiaomei_brain.agent.render_execution_context import render_step_selection_context

    refreshed = render_step_selection_context(agent, initial, [
        "create_workspace: workspace-1",
    ])
    assert "<focused_workspace>" in refreshed
    assert "原料采购" in refreshed


def test_execution_renderer_injects_selected_skill():
    from xiaomei_brain.agent.render_execution_context import prepare_execution_selection

    agent = Agent(llm=object(), tools=ToolRegistry())
    agent.session_id = "session-1"
    agent.user_id = "person-1"
    agent._skill_loader = MagicMock()
    agent._skill_loader.build_skill_index_prompt.return_value = (
        "<available_skills>document-writing</available_skills>"
    )

    prepared, query = prepare_execution_selection(agent, [
        {"role": "system", "content": "consciousness"},
        {"role": "user", "content": "写一份报告"},
    ])

    assert "写一份报告" in query
    assert prepared[0]["content"].startswith("consciousness")
    assert "document-writing" in prepared[0]["content"]


def test_execution_renderer_exposes_selection_snapshot():
    from xiaomei_brain.agent.render_execution_context import (
        current_execution_selection,
        prepare_execution_selection,
    )

    agent = Agent(llm=object(), tools=ToolRegistry())
    agent.session_id = "session-1"
    agent.user_id = "person-1"
    prepare_execution_selection(agent, [
        {"role": "system", "content": "consciousness"},
        {"role": "user", "content": "write a report"},
    ])

    snapshot = current_execution_selection(agent, 2, {
        "core": ["read"],
        "required": ["write_document"],
        "semantic": ["present_artifact"],
    })

    assert snapshot["step"] == 2
    assert snapshot["tools"]["required"] == ["write_document"]


def test_capability_prefetch_is_reused_by_context_and_execution_selection():
    from xiaomei_brain.agent.render_execution_context import (
        prepare_execution_selection,
        render_execution_context,
    )

    class Discovery:
        def __init__(self) -> None:
            self.calls = 0
            self.last_discovery = None

        def begin_run(self) -> None:
            self.last_discovery = None

        def prefetch(self, query: str, *, person_id: str):
            self.calls += 1
            return {
                "capabilities": [{"id": "office_documents", "name": "Office"}],
                "skills": [],
                "context": "<relevant_capability>Office</relevant_capability>",
            }

    agent = Agent(llm=object(), tools=ToolRegistry())
    agent.session_id = "session-1"
    agent.turn_id = "turn-1"
    agent.user_id = "person-1"
    agent.messages = [{"role": "user", "content": "write a report"}]
    discovery = Discovery()
    agent._discovery_service = discovery

    rendered = render_execution_context(agent, "write a report")
    prepare_execution_selection(agent, [
        {"role": "system", "content": "consciousness"},
        {"role": "user", "content": "write a report"},
    ])

    assert discovery.calls == 1
    assert "<relevant_capability>Office</relevant_capability>" in rendered
    assert agent._execution_selection_base["capability"]["capabilities"][0]["id"] == "office_documents"


def test_focused_workspace_does_not_expand_a_keyword_rule_kit(monkeypatch):
    tool_names = (
        "get_current_workspace",
        "define_collection",
        "add_collection_fields",
        "record_business_context",
        "create_surface",
        "update_surface",
        "list_business_actions",
        "establish_business_action",
        "unrelated_tool",
    )
    reg = _registry_with_tools(*((name, name) for name in tool_names))
    loader = DynamicToolLoader(reg, top_k=1)

    class _EmptySearch:
        def limit(self, _count):
            return self

        def to_list(self):
            return []

    class _Table:
        def count_rows(self):
            return 1

        def search(self, _vector):
            return _EmptySearch()

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._shared, "embed", lambda _query, **_kwargs: [0.0])

    query = (
        "Current user request:\n你先按你自己理解建\n\n"
        "Current runtime context:\n"
        '<focused_workspace>{"id":"workspace-1",'
        '"name":"原料采购"}</focused_workspace>'
    )
    selected = {tool.name for tool in loader.select_tools(query, top_k=1)}

    # Runtime context improves retrieval, but no longer injects an entire
    # authoring kit before the model has decided what operation is missing.
    assert len(selected) <= 1
    assert not selected.issuperset(set(tool_names) - {"unrelated_tool"})


def test_tool_embedding_fingerprint_includes_parameter_schema():
    reg = ToolRegistry()
    first = Tool(
        name="search_mail",
        description="Search mail",
        category="mail",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        func=lambda: None,
    )
    second = Tool(
        name="search_mail",
        description="Search mail",
        category="mail",
        parameters={"type": "object", "properties": {"sender": {"type": "string"}}},
        func=lambda: None,
    )
    loader = DynamicToolLoader(reg)

    assert loader._tool_fingerprint(first) != loader._tool_fingerprint(second)


def test_cached_fingerprints_are_read_without_pandas(monkeypatch):
    """The packaged Agent runtime must not need pandas to open the tool cache."""

    class _ArrowRows:
        def select(self, columns):
            assert columns == ["id", "fingerprint"]
            return self

        @staticmethod
        def to_pylist():
            return [
                {"id": "read_document", "fingerprint": "abc"},
                {"id": "write_document", "fingerprint": "def"},
            ]

    class _Table:
        @staticmethod
        def count_rows():
            return 2

        @staticmethod
        def to_arrow():
            return _ArrowRows()

    loader = DynamicToolLoader(ToolRegistry())
    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())

    assert loader._get_cached_fingerprints() == {
        "read_document": "abc",
        "write_document": "def",
    }


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
    core = ["shell"]
    assert names[:len(core)] == core, f"Expected core tools first, got {names}"


def test_assignment_tools_are_deferred_instead_of_permanent_core():
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("list_assignments", "List earlier assignments"),
        ("revise_assignment", "Revise a completed assignment"),
        ("start_assignment", "Resume a paused assignment"),
        ("unrelated", "An unrelated operation"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    names = [tool.name for tool in loader.select_tools("再增加一些代码结构分析", top_k=1)]

    assignment_names = {
        "list_assignments", "revise_assignment", "start_assignment",
    }
    assert len(assignment_names & set(names)) <= 1


def test_skill_required_tools_are_scoped_to_one_run(monkeypatch):
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("write_document", "Create or edit a document"),
        ("unrelated", "An unrelated operation"),
    )
    loader = DynamicToolLoader(reg, top_k=1)

    class _EmptySearch:
        def limit(self, _count):
            return self

        def to_list(self):
            return []

    class _Table:
        def count_rows(self):
            return 1

        def search(self, _vector):
            return _EmptySearch()

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._shared, "embed", lambda _query, **_kwargs: [0.0])

    loader.begin_run("session-a")
    activated, missing = loader.activate_required_tools(
        ["write_document", "not_registered"]
    )
    names = [tool.name for tool in loader.select_tools("make a report")]

    assert activated == ["write_document"]
    assert missing == ["not_registered"]
    assert "write_document" in names

    loader.begin_run("session-b")
    names = [tool.name for tool in loader.select_tools("make a report")]
    assert "write_document" not in names

    loader.begin_run("session-a")
    names = [tool.name for tool in loader.select_tools("make a report")]
    assert "write_document" in names

    loader.begin_run("session-a", reset=True)
    names = [tool.name for tool in loader.select_tools("unrelated request")]
    assert "write_document" not in names


def test_tool_search_activates_deferred_workspace_import(monkeypatch):
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("import_tabular_data", "Import a spreadsheet into a Workspace"),
        ("upsert_business_record", "Write one business record"),
    )
    loader = DynamicToolLoader(reg, top_k=1)

    class _EmptySearch:
        def limit(self, _count):
            return self

        def to_list(self):
            return []

    class _Table:
        def count_rows(self):
            return 1

        def search(self, _vector):
            return _EmptySearch()

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._shared, "embed", lambda _query, **_kwargs: [0.0])

    query = (
        "Current user request:\n把这份表导入刚才的 Workspace，作为持续经营数据\n\n"
        "Current attachments:\n- file, text/csv, 客户经营数据.csv"
    )
    loader.begin_run("session-a", reset=True)
    result = loader.search_and_activate(query, limit=1)
    assert result["activated"][0]["name"] == "import_tabular_data"
    names = [tool.name for tool in loader.select_tools("continue", top_k=0)]
    assert "import_tabular_data" in names


def test_model_directed_search_can_activate_business_tools(monkeypatch):
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("get_current_workspace", "Inspect focused Workspace"),
        ("query_business_records", "Query business records"),
        ("upsert_business_record", "Update a business record"),
        ("record_observation", "Preserve received business information"),
        ("list_business_actions", "List established business actions"),
        ("execute_business_action", "Execute an established business action"),
        ("establish_business_action", "Establish an action candidate"),
        ("validate_business_action_candidate", "Validate historical action evidence"),
        ("write_document", "Write a document"),
    )
    loader = DynamicToolLoader(reg, top_k=1)

    class _EmptySearch:
        def limit(self, _count):
            return self

        def to_list(self):
            return []

    class _Table:
        def count_rows(self):
            return 1

        def search(self, _vector):
            return _EmptySearch()

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._shared, "embed", lambda _query, **_kwargs: [0.0])

    loader.begin_run("session-a", reset=True)
    result = loader.search_and_activate(
        "query and update Workspace customer business records",
        limit=5,
    )
    activated = {item["name"] for item in result["activated"]}
    assert "query_business_records" in activated
    assert "upsert_business_record" in activated


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


def test_model_can_refine_tool_search_between_steps():
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

    loader.begin_run("session-a", reset=True)
    first = loader.search_and_activate("navigate browser to a URL", limit=1)
    assert first["activated"][0]["name"] == "navigate_page"

    second = loader.search_and_activate("fill a form field on the browser page", limit=2)
    assert "fill_form" in {item["name"] for item in second["activated"]}

    visible = {
        item.name for item in loader.select_tools("continue", top_k=0)
    }
    assert {"navigate_page", "fill_form"}.issubset(visible)


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


def test_explicit_tool_name_is_not_truncated_by_full_embedding_results(monkeypatch):
    reg = _registry_with_tools(
        ("tool_a", "First semantic result"),
        ("tool_b", "Second semantic result"),
        ("forced_tool", "Explicitly requested operation"),
    )
    loader = DynamicToolLoader(reg)
    loader.build_index()

    class _Table:
        @staticmethod
        def count_rows():
            return 3

        @staticmethod
        def search(_query):
            return _Table()

        @staticmethod
        def limit(_count):
            return _Table()

        @staticmethod
        def to_list():
            return [
                {"id": "tool_a", "_distance": 0.40},
                {"id": "tool_b", "_distance": 0.50},
            ]

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._get_embedder(), "embed", lambda _query, **_kwargs: [0.0])

    selected = loader.select_tools("please run forced_tool", top_k=2)

    assert [tool.name for tool in selected] == ["forced_tool", "tool_a"]


def test_semantic_prefetch_rejects_nearest_but_irrelevant_tools(monkeypatch):
    reg = _registry_with_tools(
        ("schedule_alarm", "Schedule a reminder or alarm"),
        ("check_inbox", "Check unread inbox messages"),
    )
    loader = DynamicToolLoader(reg, top_k=5)

    class _Table:
        @staticmethod
        def count_rows():
            return 2

        @staticmethod
        def search(_query):
            return _Table()

        @staticmethod
        def limit(_count):
            return _Table()

        @staticmethod
        def to_list():
            return [
                {"id": "schedule_alarm", "_distance": 0.90},
                {"id": "check_inbox", "_distance": 0.94},
            ]

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._get_embedder(), "embed", lambda _query, **_kwargs: [0.0])

    assert loader.select_tools("hi") == []


def test_transport_scaffolding_does_not_create_lexical_tool_relevance(monkeypatch):
    reg = _registry_with_tools(
        ("schedule_alarm", "Schedule an action for the current user in a few minutes"),
        ("check_inbox", "Check the current user's new messages"),
    )
    loader = DynamicToolLoader(reg, top_k=5)

    class _Table:
        @staticmethod
        def count_rows():
            return 2

        @staticmethod
        def search(_query):
            return _Table()

        @staticmethod
        def limit(_count):
            return _Table()

        @staticmethod
        def to_list():
            return [
                {"id": "schedule_alarm", "_distance": 0.90},
                {"id": "check_inbox", "_distance": 0.94},
            ]

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._get_embedder(), "embed", lambda _query, **_kwargs: [0.0])

    query = build_tool_selection_context([
        {"role": "user", "content": "距上条消息 2分钟 hi"},
    ])
    assert loader.select_tools(query) == []


def test_lexical_prefetch_uses_parameter_schema_for_exact_format_terms(monkeypatch):
    from xiaomei_brain.plugins.tools.document_io.tool import (
        create_write_document_tool,
    )

    reg = ToolRegistry()
    reg.register(create_write_document_tool(plugin_registry=None))
    reg.register(Tool(
        name="generate_video_minimax",
        description="生成一个视频文件。",
        category="video",
        parameters={},
        func=lambda **_kwargs: None,
    ))
    loader = DynamicToolLoader(reg, top_k=1)

    class _Table:
        @staticmethod
        def count_rows():
            return 0

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())

    query = build_tool_selection_context([
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "写个word文件，里面就一个字：好"},
    ])
    selected = loader.select_tools(query)

    assert [tool.name for tool in selected] == ["write_document"]


def test_execution_progress_does_not_pollute_lexical_tool_ranking(monkeypatch):
    reg = _registry_with_tools(
        ("write_document", "Create a Word document"),
        ("play_music", "Play an audio file from the music library"),
    )
    loader = DynamicToolLoader(reg, top_k=1)

    class _Table:
        @staticmethod
        def count_rows():
            return 0

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    query = (
        "Current user request:\n写个 Word 文件\n\n"
        "Recent execution progress:\n"
        "skill_view returned a long guide mentioning music audio playlist repeatedly"
    )

    assert [tool.name for tool in loader.select_tools(query)] == ["write_document"]


def test_prefetch_embeds_plain_intent_without_execution_progress(monkeypatch):
    reg = _registry_with_tools(
        ("write_document", "创建 Word 文件和 PowerPoint 演示文稿"),
        ("play_music", "播放音乐"),
    )
    loader = DynamicToolLoader(reg, top_k=1)
    embedded_queries: list[str] = []

    class _Search:
        @staticmethod
        def limit(_count):
            return _Search()

        @staticmethod
        def to_list():
            return []

    class _Table:
        @staticmethod
        def count_rows():
            return 1

        @staticmethod
        def search(_vector):
            return _Search()

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(
        loader._shared,
        "embed",
        lambda query, **_kwargs: embedded_queries.append(query) or [0.0],
    )
    loader.begin_run("session-a", reset=True)
    initial_query = (
        "Current user request:\n随便写一页\n\n"
        "Recent user context:\n- 演示文稿会写吗"
    )
    later_query = (
        f"{initial_query}\n\nRecent execution progress:\n"
        "skill_view: presentation-documents 的完整正文"
    )

    first = loader.select_tools(initial_query, step=0)
    later = loader.select_tools(later_query, step=1)

    assert embedded_queries == [
        "随便写一页\n- 演示文稿会写吗",
        "随便写一页\n- 演示文稿会写吗",
    ]
    assert [tool.name for tool in later] == [tool.name for tool in first]


def test_semantic_prefetch_accepts_absolutely_relevant_tool(monkeypatch):
    reg = _registry_with_tools(
        ("schedule_alarm", "Schedule a reminder or alarm"),
        ("check_inbox", "Check unread inbox messages"),
    )
    loader = DynamicToolLoader(reg, top_k=1)

    class _Table:
        @staticmethod
        def count_rows():
            return 2

        @staticmethod
        def search(_query):
            return _Table()

        @staticmethod
        def limit(_count):
            return _Table()

        @staticmethod
        def to_list():
            return [
                {"id": "schedule_alarm", "_distance": 0.72},
                {"id": "check_inbox", "_distance": 0.93},
            ]

    monkeypatch.setattr(loader, "_get_lance_table", lambda: _Table())
    monkeypatch.setattr(loader._get_embedder(), "embed", lambda _query, **_kwargs: [0.0])

    assert [tool.name for tool in loader.select_tools("remind me later")] == [
        "schedule_alarm"
    ]


def test_tool_search_activates_deferred_schema_for_next_step(monkeypatch):
    reg = _registry_with_tools(
        ("shell", "Run shell commands"),
        ("workspace_record_query", "Query business records in a Workspace"),
    )
    loader = DynamicToolLoader(reg, top_k=0)
    loader.build_index()
    monkeypatch.setattr(loader, "_get_lance_table", lambda: None)

    search_tool = create_tool_search_tool(loader)
    reg.register(search_tool)

    before = [tool.name for tool in loader.select_tools("inspect customers", top_k=0)]
    result = search_tool.execute(query="query Workspace business records", limit=3)
    after = [tool.name for tool in loader.select_tools("inspect customers", top_k=0)]

    assert before == ["shell"]
    assert [item["name"] for item in result["activated"]] == ["workspace_record_query"]
    assert after == ["shell", "workspace_record_query"]
    _schemas, selection = loader.select_openai_tools_with_selection(
        "inspect customers", top_k=0,
    )
    assert selection["required"] == []
    assert selection["discovered"] == ["workspace_record_query"]


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


def test_prefetch_does_not_grow_across_steps():
    """Later ReAct steps discover tools explicitly instead of growing schemas."""
    from xiaomei_brain.tools.dynamic import MAX_DYNAMIC

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

    assert dynamic_count(10, step=0) == MAX_DYNAMIC
    assert dynamic_count(10, step=1) == MAX_DYNAMIC
    assert dynamic_count(10, step=5) == MAX_DYNAMIC
    assert dynamic_count(10, step=20) == MAX_DYNAMIC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
