import base64
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Cm

from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugins.tools.document_presentation.adapter import (
    register as register_presentation,
)
from xiaomei_brain.plugins.tools.document_presentation.extractor import (
    PresentationExtractor,
)
from xiaomei_brain.plugins.tools.document_io.tool import create_write_document_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _presentation_registry() -> PluginRegistry:
    registry = PluginRegistry()
    context = PluginContext({}, "document_presentation", "test", registry)
    register_presentation(context)
    return registry


def test_presentation_plugin_owns_writer_and_skill_directory():
    registry = _presentation_registry()

    assert registry.get_document_writer("presentation") is not None
    assert registry.list_document_writers() == ["presentation"]
    skill_dirs = registry.get_skill_directories()
    assert len(skill_dirs) == 1
    assert (Path(skill_dirs[0]) / "SKILL.md").is_file()


def test_write_document_creates_themed_presentation_with_image_and_notes(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    assets = workspace / "work"
    assets.mkdir(parents=True)
    (assets / "cover.png").write_bytes(PNG_1PX)
    spec = workspace / "deck.json"
    spec.write_text(json.dumps({
        "properties": {"author": "Xiaomei", "title": "Product"},
        "page": {"size": "wide"},
        "theme": {
            "background_color": "F7F9FC",
            "title_color": "172033",
            "text_color": "354052",
            "accent_color": "4F6BED",
            "font_family": "Microsoft YaHei",
        },
        "slides": [
            {
                "type": "title",
                "title": "产品介绍",
                "subtitle": "让工作自然流动",
                "notes": "开场说明",
            },
            {
                "type": "content",
                "title": "核心能力",
                "bullets": [
                    "理解真实意图",
                    {"text": "跨渠道连续关系", "level": 1},
                ],
            },
            {
                "type": "image",
                "title": "产品界面",
                "image": {
                    "workspace_path": "work/cover.png",
                    "x_cm": 6,
                    "y_cm": 4,
                    "width_cm": 20,
                },
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-create",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="deck.json",
            output_name="product.pptx",
        )

    assert result.get("success") is True, result
    assert result["validation"]["valid"] is True
    assert result["validation"]["slide_count"] == 3
    assert result["validation"]["picture_count"] == 1
    assert result["validation"]["note_slide_count"] == 1
    deck = Presentation(outputs / "product.pptx")
    assert round(deck.slide_width / Cm(1), 2) == 33.87
    assert round(deck.slide_height / Cm(1), 2) == 19.05
    assert deck.core_properties.author == "Xiaomei"
    assert deck.slides[0].notes_slide.notes_text_frame.text == "开场说明"
    assert "• 理解真实意图" in "\n".join(
        shape.text for shape in deck.slides[1].shapes if shape.has_text_frame
    )


def test_write_document_revises_presentation_copy_and_preserves_source(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "template.pptx"
    original = Presentation()
    slide = original.slides.add_slide(original.slide_layouts[1])
    slide.shapes.title.text = "原方案"
    slide.placeholders[1].text = "客户：{{customer_name}}"
    original.save(source)
    source_bytes = source.read_bytes()
    spec = workspace / "revise.json"
    spec.write_text(json.dumps({
        "operations": [
            {
                "type": "replace_placeholders",
                "values": {"customer_name": "星海科技"},
            },
            {
                "type": "update_slide",
                "slide": 1,
                "title": "更新方案",
                "notes": "重点说明客户价值",
            },
            {
                "type": "append_slides",
                "slides": [
                    {"type": "section", "title": "实施计划"},
                    {"type": "content", "title": "下一步", "bullets": ["启动试点"]},
                ],
            },
            {"type": "move_slide", "slide": 3, "to": 2},
            {"type": "delete_slide", "slide": 3},
            {"type": "set_properties", "author": "Xiaomei", "title": "最终方案"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    attachment = {
        "id": "deck-source",
        "name": "template.pptx",
        "kind": "document",
        "local_path": str(source),
    }

    with bind_tool_execution(
        tool_call_id="call-presentation-update",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="revise.json",
            output_name="updated.pptx",
            source_attachment_id="deck-source",
        )

    assert result.get("success") is True, result
    assert result["validation"]["slide_count"] == 2
    assert source.read_bytes() == source_bytes
    updated = Presentation(outputs / "updated.pptx")
    assert updated.core_properties.author == "Xiaomei"
    assert updated.core_properties.title == "最终方案"
    assert updated.slides[0].shapes.title.text == "更新方案"
    assert "星海科技" in "\n".join(
        shape.text for shape in updated.slides[0].shapes if shape.has_text_frame
    )
    assert updated.slides[0].notes_slide.notes_text_frame.text == "重点说明客户价值"
    assert any(
        shape.text == "下一步"
        for shape in updated.slides[1].shapes
        if shape.has_text_frame
    )
    extracted = PresentationExtractor().extract(outputs / "updated.pptx")
    assert "更新方案" in extracted.sections[0].content
    assert "下一步" in extracted.sections[1].content
    assert "重点说明客户价值" in extracted.sections[0].content


def test_presentation_writer_rejects_missing_image_and_invalid_slide(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    missing_image = workspace / "missing-image.json"
    missing_image.write_text(json.dumps({
        "slides": [{
            "type": "image",
            "title": "图片",
            "image": {"workspace_path": "work/missing.png"},
        }],
    }, ensure_ascii=False), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-invalid",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="missing-image.json",
            output_name="invalid.pptx",
        )

    assert "error" in result
    assert not list(outputs.glob("*.pptx"))
