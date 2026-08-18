import base64
import json
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
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
    assert result["presentation_project"]["schema"] == "xiaomei.presentation.v1"
    assert result["presentation_project"]["slide_count"] == 3
    project_dir = outputs / ".presentation" / "product"
    assert (project_dir / "product.pptd").is_file()
    project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert len(project["slides"]) == 3
    assert any(
        element["elementType"] == "image"
        for element in project["slides"][2]["elements"]
    )
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


def test_write_document_updates_exact_presentation_element_and_rebuilds_project(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "source.pptx"
    original = Presentation()
    slide = original.slides.add_slide(original.slide_layouts[6])
    slide.shapes.add_textbox(Cm(2), Cm(2), Cm(12), Cm(3)).text = "Original text"
    original.save(source)
    spec = workspace / "element-update.json"
    spec.write_text(json.dumps({
        "operations": [{
            "type": "update_element",
            "slide": 1,
            "element_id": "slide-1-shape-1",
            "text": "Updated text",
            "text_color": "336699",
            "fill_color": "F5F7FA",
            "font_size_pt": 24,
            "bold": True,
        }],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-element-update",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=({
            "id": "source-deck",
            "name": "source.pptx",
            "kind": "document",
            "local_path": str(source),
        },),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="element-update.json",
            output_name="edited.pptx",
            source_attachment_id="source-deck",
        )

    assert result.get("success") is True, result
    edited = Presentation(outputs / "edited.pptx")
    shape = edited.slides[0].shapes[0]
    assert shape.text == "Updated text"
    assert shape.text_frame.paragraphs[0].runs[0].font.bold is True
    project_dir = outputs / ".presentation" / "edited"
    assert result["presentation_project"]["path"] == str(project_dir)
    assert (project_dir / "edited.pptd").is_file()
    project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    assert project["slides"][0]["elements"][0]["content"]["text"] == "Updated text"
    assert project["slides"][0]["elements"][0]["elementId"].startswith(
        "slide-1-shape-id-"
    )
    assert len(project["sourceRevision"]) == 64
    assert sorted(path.name for path in (outputs / ".presentation").iterdir()) == ["edited"]


def test_presentation_annotation_operations_update_table_cell_and_replace_image(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "source.pptx"
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(PNG_1PX)

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    table_shape = slide.shapes.add_table(2, 2, Cm(1), Cm(1), Cm(12), Cm(4))
    table_shape.table.cell(1, 1).text = "Old value"
    image_shape = slide.shapes.add_picture(str(replacement), Cm(15), Cm(1), width=Cm(3))
    deck.save(source)

    from xiaomei_brain.documents.presentation_project import build_presentation_project

    preview_dir = tmp_path / ".presentation" / "source"
    build_presentation_project(source, preview_dir)
    project = json.loads((preview_dir / "project.json").read_text(encoding="utf-8"))
    elements = project["slides"][0]["elements"]
    table_id = next(item["elementId"] for item in elements if item["elementType"] == "table")
    image_id = next(item["elementId"] for item in elements if item["elementType"] == "image")
    assert table_id.endswith(str(table_shape.shape_id))
    assert image_id.endswith(str(image_shape.shape_id))

    spec = workspace / "precise-update.json"
    spec.write_text(json.dumps({
        "operations": [
            {
                "type": "update_table_cell",
                "slide": 1,
                "element_id": table_id,
                "row": 2,
                "column": 2,
                "text": "New value",
                "fill_color": "EAF2EC",
                "bold": True,
            },
            {
                "type": "replace_image",
                "slide": 1,
                "element_id": image_id,
                "attachment_id": "replacement-image",
            },
        ],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-precise-update",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(
            {"id": "source-deck", "name": "source.pptx", "kind": "document", "local_path": str(source)},
            {"id": "replacement-image", "name": "replacement.png", "kind": "image", "local_path": str(replacement)},
        ),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="precise-update.json",
            output_name="precise.pptx",
            source_attachment_id="source-deck",
        )

    assert result.get("success") is True, result
    updated = Presentation(outputs / "precise.pptx")
    assert updated.slides[0].shapes[0].table.cell(1, 1).text == "New value"
    assert updated.slides[0].shapes[0].table.cell(1, 1).text_frame.paragraphs[0].runs[0].font.bold is True


def test_write_document_rejects_stale_presentation_annotation(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "source.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Cm(1), Cm(1), Cm(5), Cm(2)).text = "Hello"
    deck.save(source)
    spec = workspace / "update.json"
    spec.write_text(json.dumps({
        "operations": [{"type": "update_element", "slide": 1, "element_id": "slide-1-shape-1", "text": "Changed"}],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-stale",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=({
            "id": "source-deck",
            "name": "source.pptx",
            "kind": "document",
            "local_path": str(source),
            "annotation": {
                "kind": "presentation",
                "source_revision": "0" * 64,
            },
        },),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="update.json",
            output_name="stale.pptx",
            source_attachment_id="source-deck",
        )

    assert result["subtype"] == "stale_presentation_selection"
    assert not (outputs / "stale.pptx").exists()


def test_presentation_chart_is_previewable_and_remains_native_when_updated(tmp_path):
    registry = _presentation_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "chart-source.pptx"

    data = CategoryChartData()
    data.categories = ["Q1", "Q2", "Q3"]
    data.add_series("East", [10, 18, 24])
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    chart_shape = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Cm(2), Cm(2), Cm(22), Cm(12),
        data,
    )
    chart_shape.chart.has_title = True
    chart_shape.chart.chart_title.text_frame.text = "Quarterly sales"
    chart_shape.chart.has_legend = True
    deck.save(source)

    from xiaomei_brain.documents.presentation_project import build_presentation_project

    preview_dir = tmp_path / ".presentation" / "chart-source"
    build_presentation_project(source, preview_dir)
    project = json.loads((preview_dir / "project.json").read_text(encoding="utf-8"))
    chart_element = next(
        item for item in project["slides"][0]["elements"]
        if item["elementType"] == "chart"
    )
    assert chart_element["elementId"].endswith(str(chart_shape.shape_id))
    assert chart_element["title"] == "Quarterly sales"
    assert chart_element["fill"]["color"] == "transparent"
    assert chart_element["categories"] == ["Q1", "Q2", "Q3"]
    assert chart_element["series"][0]["values"] == [10.0, 18.0, 24.0]

    spec = workspace / "update-chart.json"
    spec.write_text(json.dumps({
        "operations": [{
            "type": "update_chart",
            "slide": 1,
            "element_id": chart_element["elementId"],
            "title": "Updated sales",
            "categories": ["Q1", "Q2", "Q3", "Q4"],
            "series": [
                {"name": "East", "values": [12, 20, 28, 35]},
                {"name": "West", "values": [8, 15, 19, 26]},
            ],
            "show_legend": True,
            "series_colors": ["2F6B4F", "D97706"],
        }],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-presentation-chart-update",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=({
            "id": "chart-source",
            "name": "chart-source.pptx",
            "kind": "document",
            "local_path": str(source),
        },),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="presentation",
            specification_path="update-chart.json",
            output_name="chart-updated.pptx",
            source_attachment_id="chart-source",
        )

    assert result.get("success") is True, result
    assert result["validation"]["chart_count"] == 1
    updated = Presentation(outputs / "chart-updated.pptx")
    updated_chart = updated.slides[0].shapes[0].chart
    assert updated_chart.chart_title.text_frame.text == "Updated sales"
    assert [str(label[0]) for label in updated_chart.plots[0].categories.flattened_labels] == [
        "Q1", "Q2", "Q3", "Q4",
    ]
    assert [series.name for series in updated_chart.series] == ["East", "West"]
    assert list(updated_chart.series[1].values) == [8.0, 15.0, 19.0, 26.0]
    assert updated_chart.has_legend is True


def test_presentation_preview_preserves_no_fill_and_no_line(tmp_path):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from xiaomei_brain.documents.presentation_project import (
        PROJECT_GENERATOR_VERSION,
        build_presentation_project,
    )

    source = tmp_path / "dark-cover.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(0x14, 0x14, 0x14)
    text_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Cm(2), Cm(2), Cm(20), Cm(3),
    )
    text_shape.text = "把对话变成生产力"
    text_shape.fill.background()
    text_shape.line.fill.background()
    deck.save(source)

    project_dir = tmp_path / ".presentation" / "dark-cover"
    build_presentation_project(source, project_dir)
    project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    element = project["slides"][0]["elements"][0]

    assert project["generatorVersion"] == PROJECT_GENERATOR_VERSION
    assert project["slides"][0]["background"]["color"] == "#141414"
    assert element["fill"] == {"type": "none", "color": "transparent"}
    assert element["line"] == {
        "type": "none",
        "color": "transparent",
        "width": 0,
    }


def test_presentation_preview_preserves_rich_text_layout_and_rotation(tmp_path):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Pt
    from xiaomei_brain.documents.presentation_project import build_presentation_project

    source = tmp_path / "rich-cover.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(2), Cm(2), Cm(20), Cm(5))
    shape.rotation = 4
    shape.fill.background()
    shape.line.fill.background()
    frame = shape.text_frame
    frame.clear()
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.margin_left = Pt(12)
    frame.margin_right = Pt(14)
    frame.margin_top = Pt(6)
    frame.margin_bottom = Pt(8)
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    paragraph.space_after = Pt(5)
    first = paragraph.add_run()
    first.text = "Before "
    first.font.size = Pt(42)
    first.font.bold = True
    first.font.color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
    second = paragraph.add_run()
    second.text = "After"
    second.font.size = Pt(42)
    second.font.bold = True
    second.font.color.rgb = RGBColor(0xC6, 0xF2, 0x4E)
    deck.save(source)

    project_dir = tmp_path / ".presentation" / "rich-cover"
    build_presentation_project(source, project_dir)
    project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    element = project["slides"][0]["elements"][0]
    text_style = element["textStyle"]
    rich_paragraph = element["richText"]["paragraphs"][0]

    assert element["rotation"] == 4.0
    assert text_style["verticalAlign"] == "middle"
    assert text_style["margins"] == [6.0, 14.0, 8.0, 12.0]
    assert rich_paragraph["align"] == "center"
    assert rich_paragraph["spaceAfter"] == 5.0
    assert [run["color"] for run in rich_paragraph["runs"]] == ["#F2F2F2", "#C6F24E"]
    assert [run["fontSize"] for run in rich_paragraph["runs"]] == [42.0, 42.0]


def test_presentation_preview_preserves_table_cell_styles_and_merges(tmp_path):
    from pptx.dml.color import RGBColor
    from pptx.util import Pt
    from xiaomei_brain.documents.presentation_project import build_presentation_project

    source = tmp_path / "styled-table.pptx"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Cm(2), Cm(2), Cm(20), Cm(8)).table
    header = table.cell(0, 0)
    header.text = "Header"
    header.fill.solid()
    header.fill.fore_color.rgb = RGBColor(0x14, 0x14, 0x14)
    header.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
    header.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    header.merge(table.cell(0, 1))
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "B"
    deck.save(source)

    project_dir = tmp_path / ".presentation" / "styled-table"
    build_presentation_project(source, project_dir)
    project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    cells = project["slides"][0]["elements"][0]["cells"]

    assert cells[0]["fill"] == {"type": "solid", "color": "#141414"}
    assert cells[0]["textStyle"]["color"] == "#F2F2F2"
    assert cells[0]["textStyle"]["fontSize"] == 18.0
    assert cells[0]["columnSpan"] == 2
    assert cells[1]["hidden"] is True
