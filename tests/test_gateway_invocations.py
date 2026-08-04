from __future__ import annotations

from types import SimpleNamespace

import pytest

from xiaomei_brain.agent.invocations import (
    process_matches_capability,
    render_invocation_context,
    validate_invocation,
)
from xiaomei_brain.gateway.methods.invocations import InvocationMethods
from xiaomei_brain.gateway.methods.chat import ChatMethods
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.processes.templates import ProcessTemplate


class _TemplateRegistry:
    def __init__(self, templates):
        self._templates = {item.id: item for item in templates}

    def list(self):
        return list(self._templates.values())

    def require(self, template_id):
        if template_id not in self._templates:
            raise KeyError(template_id)
        return self._templates[template_id]


class _SkillLoader:
    def list_skills(self, query="", top_k=10):
        return [{
            "name": "doc-coauthoring",
            "description": "共同完成结构化文档",
            "tags": ["document"],
        }][:top_k]

    def view_skill(self, name):
        if name != "doc-coauthoring":
            return None
        return {
            "name": name,
            "description": "共同完成结构化文档",
            "content": "先确认受众，再逐段完善。",
        }


def _template(*, capability_ids=("video_production",), project_types=("video.production",)):
    return ProcessTemplate(
        id="video-fast-3",
        name="三阶段视频交付标准",
        description="快速视频交付",
        capability_ids=capability_ids,
        project_types=project_types,
        tags=("video",),
        definition={
            "id": "video-fast-3",
            "name": "三阶段视频交付标准",
            "ordered": False,
            "stages": [
                {"id": "brief", "title": "需求", "position": 1, "required": True, "requirements": []},
                {"id": "build", "title": "制作", "position": 2, "required": True, "requirements": []},
                {"id": "deliver", "title": "交付", "position": 3, "required": True, "requirements": []},
            ],
        },
        source_path="video-fast-3.yaml",
    )


def _agent():
    template = _template()
    return SimpleNamespace(
        list_capabilities=lambda: [
            {
                "id": "video_production",
                "name": "视频制作",
                "summary": "从创意到成片",
                "enabled": True,
                "status": "ready",
            },
            {
                "id": "broken",
                "name": "尚未就绪",
                "summary": "不应显示",
                "enabled": True,
                "status": "unavailable",
            },
        ],
        get_capability=lambda capability_id: {
            "id": "video_production",
            "name": "视频制作",
            "summary": "从创意到成片",
            "enabled": True,
            "status": "ready",
        } if capability_id == "video_production" else None,
        _process_template_registry=_TemplateRegistry([template]),
        _skill_loader=_SkillLoader(),
    )


def test_interaction_catalog_exposes_only_user_facing_usable_choices():
    living = SimpleNamespace(agent=_agent())
    response = InvocationMethods(living).handle_catalog("connection", "request-1", {})

    result = response["result"]
    assert [item["id"] for item in result["capabilities"]] == ["video_production"]
    assert result["capabilities"][0]["processes"][0]["id"] == "video-fast-3"
    assert result["skills"][0]["id"] == "doc-coauthoring"
    assert [item["id"] for item in result["execution_modes"]] == ["assignment", "project"]


def test_explicit_invocation_is_validated_and_rendered_as_a_constraint():
    agent = _agent()
    selected = validate_invocation(agent, {
        "kind": "capability",
        "id": "video_production",
        "process_template_id": "video-fast-3",
    })
    context = render_invocation_context(agent, selected)

    assert selected["process_template_id"] == "video-fast-3"
    assert "apply_project_process_template" in context
    assert "template_id=video-fast-3" in context
    assert "不得自行缩减" in context


def test_skill_and_execution_modes_render_the_selected_method():
    agent = _agent()
    skill_context = render_invocation_context(agent, {
        "kind": "skill",
        "id": "doc-coauthoring",
    })
    assignment_context = render_invocation_context(agent, {
        "kind": "execution",
        "id": "assignment",
    })

    assert "先确认受众" in skill_context
    assert "必须使用 delegate" in assignment_context


def test_invalid_process_cannot_be_attached_to_an_unrelated_capability():
    template = _template(capability_ids=("office_documents",))
    assert process_matches_capability(template, "video_production") is False

    agent = _agent()
    agent._process_template_registry = _TemplateRegistry([template])
    with pytest.raises(ValueError, match="不属于"):
        validate_invocation(agent, {
            "kind": "capability",
            "id": "video_production",
            "process_template_id": "video-fast-3",
        })


def test_legacy_process_project_type_still_matches_installed_packages():
    template = _template(capability_ids=())
    assert process_matches_capability(template, "video_production") is True


def test_chat_compact_uses_the_bound_person_and_session():
    calls = []

    class _Commands:
        def execute(self, name, **kwargs):
            calls.append((name, kwargs))
            return SimpleNamespace(data={"node_id": 7, "tokens": 128})

    conn_id = "invocation-compact-connection"
    cm.connections[conn_id] = object()
    cm.set_session("session-1", conn_id, "person-1")
    try:
        living = SimpleNamespace(agent=SimpleNamespace(commands=_Commands()))
        response = ChatMethods(living).handle_compact(
            conn_id,
            "request-compact",
            {"session_id": "session-1"},
        )
    finally:
        cm.unregister(conn_id)

    assert response["result"]["compacted"] is True
    assert calls == [("summarize", {"user_id": "person-1", "session_id": "session-1"})]
