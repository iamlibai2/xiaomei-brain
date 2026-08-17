from datetime import datetime
from types import SimpleNamespace

from xiaomei_brain.tools.builtin.memory_search import create_memory_search_tools
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _Memory:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def recall(self, query: str, *, user_id: str, top_k: int):
        self.calls.append({"query": query, "user_id": user_id, "top_k": top_k})
        return []

    def get_relation_chain(self, memory_id: int, depth: int):
        return []


def test_memory_search_uses_current_person_scope():
    memory = _Memory()
    agent = SimpleNamespace(
        longterm_memory=memory,
        memory_scope_id="global",
        user_id="global",
    )
    memory_search = create_memory_search_tools(agent)[0]

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="memory_search",
        arguments={"query": "preferred style"},
        artifact_callback=None,
        person_id="person-1",
    ):
        memory_search.execute(query="preferred style")

    assert memory.calls == [{
        "query": "preferred style",
        "user_id": "person-1",
        "top_k": 5,
    }]
    assert "user_id" not in memory_search.parameters["properties"]
    assert memory_search.max_calls_per_run == 4


def test_memory_search_falls_back_to_runtime_memory_scope():
    memory = _Memory()
    agent = SimpleNamespace(
        longterm_memory=memory,
        memory_scope_id="person-background",
        user_id="global",
    )
    memory_search = create_memory_search_tools(agent)[0]

    memory_search.execute(query="previous work", top_k=3)

    assert memory.calls[0]["user_id"] == "person-background"
    assert memory.calls[0]["top_k"] == 3


def test_memory_search_displays_extended_memory_types():
    memory = _Memory()
    memory.recall = lambda query, *, user_id, top_k: [
        {"id": 1, "type": "common", "content": "world.docx 是之前使用的 world 文件", "score": 0.9},
        {"id": 2, "type": "preference_signal", "content": "博士喜欢简洁表达", "score": 0.8},
    ]
    agent = SimpleNamespace(longterm_memory=memory, memory_scope_id="person-1", user_id="global")

    result = create_memory_search_tools(agent)[0].execute(query="world 文件")

    assert "共 2 条" in result
    assert "world.docx 是之前使用的 world 文件" in result
    assert "博士喜欢简洁表达" in result
    assert "[common]" in result
    assert "[preference_signal]" in result


def test_memory_search_does_not_report_empty_content_as_results():
    memory = _Memory()
    memory.recall = lambda query, *, user_id, top_k: [
        {"id": 1, "type": "common", "content": "", "score": 0.9},
        {"id": 2, "type": "future_type", "content": "   ", "score": 0.8},
    ]
    agent = SimpleNamespace(longterm_memory=memory, memory_scope_id="person-1", user_id="global")

    result = create_memory_search_tools(agent)[0].execute(query="world 文件")

    assert result == "没有找到与「world 文件」相关的记忆。"
    assert "共 2 条" not in result


def test_memory_search_distinguishes_event_time_from_formation_time():
    memory = _Memory()
    memory.recall = lambda query, *, user_id, top_k: [
        {
            "id": 1,
            "type": "common",
            "content": "有可信消息证据",
            "event_time": datetime(2026, 8, 17, 16, 12).timestamp(),
            "event_time_end": datetime(2026, 8, 17, 16, 14).timestamp(),
            "created_at": datetime(2026, 8, 18, 8, 0).timestamp(),
            "score": 0.9,
        },
        {
            "id": 2,
            "type": "knowledge",
            "content": "旧记忆没有事件证据",
            "created_at": datetime(2026, 8, 18, 8, 0).timestamp(),
            "score": 0.8,
        },
    ]
    agent = SimpleNamespace(longterm_memory=memory, memory_scope_id="person-1", user_id="global")

    result = create_memory_search_tools(agent)[0].execute(query="时间")

    assert "发生于 2026-08-17 16:12 至 2026-08-17 16:14" in result
    assert "形成于 2026-08-18 08:00，发生时间未知" in result
