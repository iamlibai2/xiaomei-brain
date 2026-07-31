import json
from pathlib import Path

from docx import Document

from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugins.tools.document_word.adapter import register as register_word
from xiaomei_brain.tools.builtin.documents import create_write_document_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution
from xiaomei_brain.gateway import artifacts as artifact_module
from xiaomei_brain.gateway.artifacts import discover_tool_artifacts


def _word_registry() -> PluginRegistry:
    registry = PluginRegistry()
    context = PluginContext({}, "document_word", "test", registry)
    register_word(context)
    return registry


def test_word_plugin_owns_writer_and_skill_directory():
    registry = _word_registry()

    assert registry.get_document_writer("word") is not None
    assert registry.list_document_writers() == ["word"]
    skill_dirs = registry.get_skill_directories()
    assert len(skill_dirs) == 1
    assert (Path(skill_dirs[0]) / "SKILL.md").is_file()


def test_document_tools_and_writer_are_discovered_through_plugins():
    registry = PluginRegistry()
    tools_root = (
        Path(__file__).parents[1]
        / "src"
        / "xiaomei_brain"
        / "plugins"
        / "tools"
    )
    loader = PluginLoader(
        registry,
        config={
            "plugins": {
                "allow": ["document_io", "document_word"],
            },
        },
        agent_id="test",
    )

    loaded = loader.boot([str(tools_root)])

    assert {
        item.manifest.name
        for item in loaded
        if item.status == "loaded"
    } == {"document_io", "document_word"}
    assert {
        tool.name for tool in registry.get_agent_tools()
    } == {"read_document", "write_document"}
    assert registry.get_document_writer("word") is not None


def test_write_document_creates_and_validates_word_file(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    spec = workspace / "report.json"
    spec.write_text(json.dumps({
        "title": "Quarterly Report",
        "properties": {"author": "Xiaomei"},
        "blocks": [
            {"type": "heading", "level": 1, "text": "Summary"},
            {"type": "paragraph", "text": "Work completed."},
            {"type": "list", "items": ["One", "Two"]},
            {"type": "table", "headers": ["Metric", "Value"], "rows": [["Users", 12]]},
        ],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-1",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="report.json",
            output_name="quarterly.docx",
        )

    output = outputs / "quarterly.docx"
    assert result["success"] is True
    assert result["validation"]["valid"] is True
    assert result["validation"]["tables"] == 1
    assert output.is_file()
    document = Document(output)
    assert document.core_properties.author == "Xiaomei"
    assert "Quarterly Report" in "\n".join(p.text for p in document.paragraphs)


def test_write_document_revises_copy_without_overwriting_attachment(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "source.docx"
    original = Document()
    original.add_paragraph("Old wording")
    original.save(source)
    original_bytes = source.read_bytes()
    spec = workspace / "revision.json"
    spec.write_text(json.dumps({
        "operations": [
            {"type": "replace_text", "old": "Old wording", "new": "New wording"},
            {"type": "append_blocks", "blocks": [{"type": "paragraph", "text": "Added note"}]},
        ],
    }), encoding="utf-8")
    attachment = {
        "id": "source-1",
        "name": "source.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": source.stat().st_size,
        "kind": "document",
        "local_path": str(source),
    }

    with bind_tool_execution(
        tool_call_id="call-2",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="revision.json",
            output_name="revised.docx",
            source_attachment_id="source-1",
        )

    assert result["success"] is True
    assert result["validation"]["replacements"] == 1
    assert source.read_bytes() == original_bytes
    revised = Document(outputs / "revised.docx")
    text = "\n".join(paragraph.text for paragraph in revised.paragraphs)
    assert "New wording" in text and "Added note" in text


def test_write_document_rejects_paths_and_unowned_sources(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    valid = workspace / "valid.json"
    valid.write_text(json.dumps({
        "blocks": [{"type": "paragraph", "text": "Valid"}],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-3",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(workspace / "outputs"),
    ):
        outside_result = tool.execute(
            format="word",
            specification_path=str(outside),
            output_name="result.docx",
        )
        traversal_result = tool.execute(
            format="word",
            specification_path="valid.json",
            output_name="../result.docx",
        )
        source_result = tool.execute(
            format="word",
            specification_path="valid.json",
            output_name="result.docx",
            source_attachment_id="not-owned",
        )

    assert "error" in outside_result
    assert "error" in traversal_result
    assert "error" in source_result


def test_write_document_preserves_existing_output_and_removes_failed_temporary_file(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True)
    existing = outputs / "report.docx"
    existing.write_bytes(b"existing deliverable")
    valid = workspace / "valid.json"
    valid.write_text(json.dumps({
        "blocks": [{"type": "paragraph", "text": "New deliverable"}],
    }), encoding="utf-8")
    invalid = workspace / "invalid.json"
    invalid.write_text(json.dumps({
        "blocks": [{"type": "unsupported"}],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-safe-output",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        created = tool.execute(
            format="word",
            specification_path="valid.json",
            output_name="report.docx",
        )
        failed = tool.execute(
            format="word",
            specification_path="invalid.json",
            output_name="broken.docx",
        )

    assert created["success"] is True
    assert created["output_name"] == "report (1).docx"
    assert existing.read_bytes() == b"existing deliverable"
    assert (outputs / "report (1).docx").is_file()
    assert "error" in failed
    assert not (outputs / "broken.docx").exists()
    assert not list(outputs.glob(".*.tmp.docx"))


def test_written_word_is_discovered_by_existing_artifact_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_module.Path, "home", classmethod(lambda cls: tmp_path))
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
    workspace.mkdir(parents=True)
    spec = workspace / "artifact.json"
    spec.write_text(json.dumps({
        "blocks": [{"type": "paragraph", "text": "Deliverable"}],
    }), encoding="utf-8")
    with bind_tool_execution(
        tool_call_id="call-4",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(workspace),
    ):
        result = tool.execute(
            format="word",
            specification_path="artifact.json",
            output_name="deliverable.docx",
        )

    discovered = discover_tool_artifacts(
        "xiaomei",
        "session-1",
        "turn-1",
        "write_document",
        {"output_name": "deliverable.docx"},
        json.dumps(result, ensure_ascii=False),
    )

    assert len(discovered) == 1
    assert discovered[0]["name"] == "deliverable.docx"
    assert discovered[0]["kind"] == "document"
