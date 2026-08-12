from types import SimpleNamespace

from xiaomei_brain.tools.builtin.memory_search import create_memory_search_tools
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _Memory:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def recall(self, query: str, *, user_id: str, top_k: int):
        self.calls.append({"query": query, "user_id": user_id, "top_k": top_k})
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
