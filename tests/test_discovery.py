from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.discovery import DiscoveryService, create_discover_tool
from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.tools.registry import ToolRegistry


class _Capabilities:
    def discover(self, query, *, limit, person_id, min_score=0.50):
        if "附近能力" in query:
            if min_score is not None:
                return []
            outcome = SimpleNamespace(id="documents", name="飞书文档", description="修改飞书文档")
            view = SimpleNamespace(
                id="feishu_office",
                name="飞书办公",
                status=SimpleNamespace(value="ready"),
                summary="飞书企业协作",
                outcomes=[outcome],
            )
            return [{"view": view, "outcome_id": "documents", "score": 0.31}]
        if "飞书" not in query:
            return []
        outcome = SimpleNamespace(id="documents", name="飞书文档", description="修改飞书文档")
        view = SimpleNamespace(
            id="feishu_office",
            name="飞书办公",
            status=SimpleNamespace(value="ready"),
            summary="飞书企业协作",
            outcomes=[outcome],
        )
        return [{"view": view, "outcome_id": "documents", "score": 0.9}]

    def select_execution_components(self, query, *, limit, person_id):
        return (["read_feishu_document"], ["lark-doc"]) if "飞书" in query else ([], [])


class _Skills:
    def __init__(self, values):
        self.values = values

    def list_skills(self, *, query, top_k):
        return list(self.values)[:top_k]

    def view_skill(self, name):
        return next((dict(item, content=f"Full {name}") for item in self.values if item["name"] == name), None)


class _Dynamic:
    def __init__(self):
        self.active = []
        self.search_limits = []

    def search_and_activate(self, query, limit):
        self.search_limits.append(limit)
        return {"activated": [], "missing": []}

    def activate_required_tools(self, names):
        self.active.extend(names)
        return list(names), []


def _service(skills):
    registry = ToolRegistry()

    @tool(name="skill_view")
    def skill_view(name: str) -> str:
        return f"# {name}\nfull skill content"

    @tool(name="read_feishu_document")
    def read_feishu_document(document_id: str) -> str:
        return document_id

    registry.register(skill_view)
    registry.register(read_feishu_document)
    dynamic = _Dynamic()
    service = DiscoveryService(
        capability_registry=_Capabilities(),
        skill_loader=_Skills(skills),
        dynamic_tool_loader=dynamic,
        tool_registry=registry,
    )
    return service, dynamic


def test_discover_does_not_invent_platform_capability_for_generic_file_request():
    service, dynamic = _service([])

    result = service.discover("把心情写入 world 文件", person_id="person-1")

    assert result["capabilities"] == []
    assert dynamic.active == []


def test_discover_reports_low_confidence_capability_without_activating_it():
    service, dynamic = _service([])

    result = service.discover("附近能力", person_id="person-1")

    assert result["capabilities"] == []
    assert result["nearby_capabilities"][0]["id"] == "feishu_office"
    assert dynamic.active == []


def test_discovery_state_is_cleared_at_the_start_of_a_new_run():
    service, _dynamic = _service([])
    service.discover("修改飞书里的文档", person_id="person-1")

    service.begin_run()

    assert service.last_discovery is None


def test_discover_expands_explicit_platform_capability_outcome():
    service, dynamic = _service([])

    result = service.discover("修改飞书里的 world 文档", person_id="person-1")

    assert result["capabilities"][0]["id"] == "feishu_office"
    assert result["capabilities"][0]["outcome_id"] == "documents"
    assert "read_feishu_document" in dynamic.active
    assert dynamic.search_limits == [3]


def test_discover_does_not_expand_weak_capability_match():
    service, dynamic = _service([])

    def weak_discover(query, *, limit, person_id, min_score=0.50):
        outcome = SimpleNamespace(id="documents", name="Feishu documents", description="Edit documents")
        view = SimpleNamespace(
            id="feishu_office",
            name="Feishu Office",
            status=SimpleNamespace(value="ready"),
            summary="Enterprise collaboration",
            outcomes=[outcome],
        )
        return [{"view": view, "outcome_id": "documents", "score": 0.60}]

    service._capabilities.discover = weak_discover
    result = service.discover("edit a Feishu document", person_id="person-1")

    assert result["capabilities"][0]["score"] == 0.60
    assert dynamic.active == []


def test_discover_loads_one_unambiguous_skill_immediately():
    service, _dynamic = _service([{
        "name": "word-documents",
        "description": "Create and edit Word documents",
        "tags": ["word"],
        "tool_bindings": [],
    }])
    discover = create_discover_tool(service)

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="discover",
        arguments={"query": "生成 Word 建设方案"},
        artifact_callback=None,
        person_id="person-1",
    ):
        result = discover.execute(query="生成 Word 建设方案")

    assert result["loaded_skill"]["name"] == "word-documents"
    assert "full skill content" in result["loaded_skill"]["content"]


def test_discover_keeps_multiple_skill_candidates_as_summaries():
    service, _dynamic = _service([
        {"name": "word-documents", "description": "Word", "tool_bindings": []},
        {"name": "pdf-documents", "description": "PDF", "tool_bindings": []},
    ])

    result = service.discover("处理文档", person_id="person-1")

    assert result["loaded_skill"] is None
    assert [item["name"] for item in result["skills"]] == [
        "word-documents",
        "pdf-documents",
    ]
