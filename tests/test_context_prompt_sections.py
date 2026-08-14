from __future__ import annotations

from types import SimpleNamespace

from xiaomei_brain.consciousness.workspace import inject_consciousness_v3 as module
from xiaomei_brain.agent import render_execution_context as execution_module


def test_disabled_prompt_section_is_not_rendered(monkeypatch):
    monkeypatch.setattr(module, "_render_header", lambda _si: ["HEADER"])
    monkeypatch.setattr(module, "_render_being", lambda _si: ["BEING"])
    monkeypatch.setattr(module, "_render_cornerstone", lambda _si: ["CORNERSTONE"])
    monkeypatch.setattr(module, "_render_essence", lambda _si: ["ESSENCE"])
    monkeypatch.setattr(module, "_render_body", lambda _si: ["BODY"])
    monkeypatch.setattr(module, "_render_observed", lambda _si: ["OBSERVED"])
    monkeypatch.setattr(module, "_render_dag_summaries", lambda _si: ["DAG"])
    si = SimpleNamespace(
        _context_config=SimpleNamespace(prompt_sections={"body": False}),
    )

    rendered = module._assemble_flow(si)

    assert "HEADER" in rendered
    assert "BEING" in rendered
    assert "BODY" not in rendered
    assert "OBSERVED" in rendered


def test_prompt_sections_default_to_enabled(monkeypatch):
    monkeypatch.setattr(module, "_render_header", lambda _si: ["HEADER"])
    monkeypatch.setattr(module, "_render_being", lambda _si: ["BEING"])
    monkeypatch.setattr(module, "_render_cornerstone", lambda _si: ["CORNERSTONE"])
    monkeypatch.setattr(module, "_render_essence", lambda _si: ["ESSENCE"])
    monkeypatch.setattr(module, "_render_body", lambda _si: ["BODY"])
    monkeypatch.setattr(module, "_render_observed", lambda _si: ["OBSERVED"])
    monkeypatch.setattr(module, "_render_dag_summaries", lambda _si: ["DAG"])

    rendered = module._assemble_flow(SimpleNamespace())

    assert "BODY" in rendered


def test_execution_prompt_sections_use_same_policy():
    agent = SimpleNamespace(
        _living_cfg=SimpleNamespace(
            context=SimpleNamespace(
                prompt_sections={"project": False, "assignment": True},
            ),
        ),
    )
    rendered: list[str] = []

    execution_module._append_section(agent, rendered, "project", "PROJECT")
    execution_module._append_section(agent, rendered, "assignment", "ASSIGNMENT")

    assert rendered == ["ASSIGNMENT"]
