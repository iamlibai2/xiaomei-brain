import base64
import json
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import RGBColor

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
                "allow": [
                    "document_io",
                    "document_pdf",
                    "document_presentation",
                    "document_spreadsheet",
                    "document_word",
                ],
            },
        },
        agent_id="test",
    )

    loaded = loader.boot([str(tools_root)])

    assert {
        item.manifest.name
        for item in loaded
        if item.status == "loaded"
    } == {
        "document_io",
        "document_pdf",
        "document_presentation",
        "document_spreadsheet",
        "document_word",
    }
    assert {
        tool.name for tool in registry.get_agent_tools()
    } == {"read_document", "write_document"}
    assert registry.get_document_writer("word") is not None
    assert registry.get_document_writer("spreadsheet") is not None
    assert registry.get_document_writer("presentation") is not None
    assert registry.get_document_writer("pdf") is not None


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


def test_word_creation_applies_professional_theme_and_table_hierarchy(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    spec = workspace / "themed.json"
    spec.write_text(json.dumps({
        "title": "企业试点报告",
        "subtitle": "管理层决策材料",
        "theme": {"preset": "technology"},
        "blocks": [
            {"type": "heading", "level": 1, "text": "执行摘要"},
            {"type": "paragraph", "text": "本报告用于验证专业排版主题。"},
            {"type": "quote", "text": "结论先行，证据随后。"},
            {
                "type": "table",
                "headers": ["指标", "结果"],
                "rows": [["效率", "提升20%"], ["风险", "可控"]],
                "column_widths_cm": [5, 8],
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-theme",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="themed.json",
            output_name="themed.docx",
        )

    assert result["success"] is True
    assert result["validation"]["theme"] == "technology"
    assert result["validation"]["render_validation"]["status"] == "disabled"
    document = Document(outputs / "themed.docx")
    assert round(document.sections[0].page_width.cm, 1) == 21.0
    assert round(document.sections[0].page_height.cm, 1) == 29.7
    assert document.styles["Title"].font.color.rgb == RGBColor(0x12, 0x3B, 0x5D)
    assert document.styles["Heading 1"].paragraph_format.keep_with_next is True
    title_fonts = document.styles["Title"]._element.rPr.rFonts
    assert title_fonts.get(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia"
    ) == "Microsoft YaHei"
    assert "eastAsiaTheme" not in title_fonts.xml
    assert "w:pBdr" in document.styles["Heading 1"]._element.xml
    assert "w:fill=\"123B5D\"" in document.tables[0].rows[0].cells[0]._tc.xml
    assert document.tables[0].rows[0].cells[0].paragraphs[0].runs[0].bold is True


def test_word_visual_validation_is_opt_in_and_reported(tmp_path, monkeypatch):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    spec = workspace / "visual.json"
    spec.write_text(json.dumps({
        "visual_validation": True,
        "blocks": [{"type": "paragraph", "text": "需要渲染检查"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.document_word.writer.render_office_document",
        lambda path: {
            "status": "passed",
            "performed": True,
            "backend": "microsoft-office-com",
            "page_count": 1,
            "blank_pages": [],
        },
    )

    with bind_tool_execution(
        tool_call_id="call-visual",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="visual.json",
            output_name="visual.docx",
        )

    rendered = result["validation"]["render_validation"]
    assert rendered["status"] == "passed"
    assert rendered["backend"] == "microsoft-office-com"


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


def test_word_template_replaces_cross_run_placeholders_across_document_parts(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "template.docx"

    template = Document()
    paragraph = template.add_paragraph()
    paragraph.add_run("客户：")
    paragraph.add_run("{{customer").bold = True
    paragraph.add_run("_name}}").italic = True
    paragraph.add_run("（重点客户）").underline = True
    table = template.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "项目：{{project_name}}"
    header = template.sections[0].header.paragraphs[0]
    header.text = "报告：{{project_name}}"
    footer = template.sections[0].footer.paragraphs[0]
    footer.text = "联系人：{{customer_name}}"
    template.save(source)

    spec = workspace / "template-values.json"
    spec.write_text(json.dumps({
        "operations": [{
            "type": "replace_placeholders",
            "values": {
                "customer_name": "星海科技",
                "project_name": "智能办公平台",
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")
    attachment = {
        "id": "template-1",
        "name": "template.docx",
        "kind": "document",
        "local_path": str(source),
    }

    with bind_tool_execution(
        tool_call_id="call-template",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="template-values.json",
            output_name="filled.docx",
            source_attachment_id="template-1",
        )

    assert result["success"] is True
    assert result["validation"]["replacements"] == 4
    filled = Document(outputs / "filled.docx")
    body = filled.paragraphs[0]
    assert body.text == "客户：星海科技（重点客户）"
    assert body.runs[1].bold is True
    assert body.runs[3].underline is True
    assert filled.tables[0].cell(0, 0).text == "项目：智能办公平台"
    assert filled.sections[0].header.paragraphs[0].text == "报告：智能办公平台"
    assert filled.sections[0].footer.paragraphs[0].text == "联系人：星海科技"


def test_word_template_inserts_blocks_at_body_marker(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "template.docx"

    template = Document()
    template.add_paragraph("前言")
    template.add_paragraph("{{DETAILS}}")
    template.add_paragraph("结语")
    template.save(source)
    spec = workspace / "insert.json"
    spec.write_text(json.dumps({
        "operations": [{
            "type": "insert_blocks_after",
            "marker": "{{DETAILS}}",
            "remove_marker": True,
            "blocks": [
                {"type": "heading", "level": 1, "text": "项目详情"},
                {"type": "paragraph", "text": "这是插入的正文。"},
                {"type": "list", "items": ["第一项", "第二项"]},
            ],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    attachment = {
        "id": "template-2",
        "name": "template.docx",
        "kind": "document",
        "local_path": str(source),
    }

    with bind_tool_execution(
        tool_call_id="call-insert",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="insert.json",
            output_name="inserted.docx",
            source_attachment_id="template-2",
        )

    assert result["success"] is True
    assert result["validation"]["insertions"] == 4
    inserted = Document(outputs / "inserted.docx")
    assert [paragraph.text for paragraph in inserted.paragraphs] == [
        "前言",
        "项目详情",
        "这是插入的正文。",
        "第一项",
        "第二项",
        "结语",
    ]


def test_word_creation_uses_owned_image_and_page_layout(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    image = tmp_path / "logo.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
        "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    spec = workspace / "styled.json"
    spec.write_text(json.dumps({
        "default_style": {"font": "Microsoft YaHei", "size_pt": 11},
        "page": {
            "size": "A4",
            "orientation": "landscape",
            "margins_cm": {"top": 2, "right": 1.5, "bottom": 2, "left": 1.5},
        },
        "header": {"text": "小美企业报告"},
        "footer": {"text": "第 ", "page_number": True},
        "blocks": [
            {"type": "paragraph", "text": "报告正文"},
            {
                "type": "image",
                "attachment_id": "logo-1",
                "width_cm": 2,
                "caption": "企业标识",
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    attachment = {
        "id": "logo-1",
        "name": "logo.png",
        "kind": "image",
        "local_path": str(image),
    }

    with bind_tool_execution(
        tool_call_id="call-layout",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="styled.json",
            output_name="styled.docx",
        )

    assert result["success"] is True
    styled = Document(outputs / "styled.docx")
    section = styled.sections[0]
    assert section.orientation == WD_ORIENT.LANDSCAPE
    assert round(section.top_margin.cm, 1) == 2.0
    assert round(section.left_margin.cm, 1) == 1.5
    assert styled.styles["Normal"].font.name == "Microsoft YaHei"
    assert round(styled.styles["Normal"].font.size.pt, 1) == 11.0
    assert section.header.paragraphs[0].text == "小美企业报告"
    assert section.footer.paragraphs[0].text == "第 "
    footer_xml = section.footer.paragraphs[0]._p.xml
    assert "PAGE" in footer_xml
    assert len(styled.inline_shapes) == 1
    assert "企业标识" in [paragraph.text for paragraph in styled.paragraphs]


def test_word_creation_uses_controlled_workspace_image(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    work = workspace / "work"
    outputs = workspace / "outputs"
    work.mkdir(parents=True)
    image = work / "generated.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
        "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    spec = work / "with-image.json"
    spec.write_text(json.dumps({
        "blocks": [{
            "type": "image",
            "workspace_path": "work/generated.png",
            "width_cm": 2,
        }],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-workspace-image",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(work),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="word",
            specification_path="work/with-image.json",
            output_name="workspace-image.docx",
        )

    assert result["success"] is True
    assert len(Document(outputs / "workspace-image.docx").inline_shapes) == 1


def test_write_document_rejects_workspace_image_traversal(tmp_path):
    registry = _word_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = workspace / "unsafe.json"
    spec.write_text(json.dumps({
        "blocks": [{"type": "image", "workspace_path": "../outside.png"}],
    }), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-unsafe-image",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(workspace / "outputs"),
    ):
        result = tool.execute(
            format="word",
            specification_path="unsafe.json",
            output_name="unsafe.docx",
        )

    assert "relative workspace path" in result["error"]
    assert not (workspace / "outputs" / "unsafe.docx").exists()


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
