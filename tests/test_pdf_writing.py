import base64
import json
from pathlib import Path

from pypdf import PdfReader

from xiaomei_brain.plugin.context import PluginContext
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugins.tools.document_pdf.adapter import register as register_pdf
from xiaomei_brain.plugins.tools.document_pdf.extractor import PdfExtractor
from xiaomei_brain.tools.builtin.documents import create_write_document_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _pdf_registry() -> PluginRegistry:
    registry = PluginRegistry()
    context = PluginContext({}, "document_pdf", "test", registry)
    register_pdf(context)
    return registry


def test_pdf_plugin_owns_writer_and_skill_directory():
    registry = _pdf_registry()

    assert registry.get_document_writer("pdf") is not None
    assert registry.list_document_writers() == ["pdf"]
    skill_dirs = registry.get_skill_directories()
    assert len(skill_dirs) == 1
    assert (Path(skill_dirs[0]) / "SKILL.md").is_file()


def test_write_document_creates_chinese_pdf_with_table_image_and_text_layer(tmp_path):
    registry = _pdf_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    assets = workspace / "work"
    assets.mkdir(parents=True)
    (assets / "chart.png").write_bytes(PNG_1PX)
    spec = workspace / "report.json"
    spec.write_text(json.dumps({
        "properties": {
            "title": "项目报告",
            "author": "Xiaomei",
            "subject": "阶段总结",
            "keywords": "report,test",
        },
        "page": {
            "size": "A4",
            "orientation": "portrait",
            "margins_cm": {"top": 2, "right": 2, "bottom": 2, "left": 2},
        },
        "header": {"text": "项目报告"},
        "footer": {"text": "第", "page_number": True},
        "blocks": [
            {"type": "heading", "level": 1, "text": "项目报告"},
            {"type": "paragraph", "text": "这是报告摘要。", "align": "justify"},
            {"type": "heading", "level": 2, "text": "主要结论"},
            {"type": "list", "items": ["结论一", "结论二"]},
            {
                "type": "table",
                "headers": ["指标", "结果"],
                "rows": [["完成率", "90%"], ["风险", "低"]],
                "column_widths": [5, 10],
            },
            {
                "type": "image",
                "workspace_path": "work/chart.png",
                "width_cm": 3,
                "align": "center",
                "caption": "图 1：结果概览",
            },
            {"type": "quote", "text": "保持简单，持续交付。"},
            {"type": "page_break"},
            {"type": "heading", "level": 2, "text": "Appendix"},
            {"type": "paragraph", "text": "English text layer check."},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    with bind_tool_execution(
        tool_call_id="call-pdf-create",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        result = tool.execute(
            format="pdf",
            specification_path="report.json",
            output_name="report.pdf",
        )

    assert result.get("success") is True, result
    assert result["validation"]["valid"] is True
    assert result["validation"]["page_count"] == 2
    assert result["validation"]["image_count"] == 1
    assert result["validation"]["has_text_layer"] is True
    reader = PdfReader(outputs / "report.pdf")
    assert reader.metadata.title == "项目报告"
    assert reader.metadata.author == "Xiaomei"
    assert "English text layer check." in (reader.pages[1].extract_text() or "")
    extraction = PdfExtractor().extract(outputs / "report.pdf")
    assert extraction.metadata["requires_ocr"] is False
    assert "项目报告" in extraction.sections[0].content
    assert "Appendix" in extraction.sections[1].content


def test_pdf_writer_rejects_source_revision_and_missing_image(tmp_path):
    registry = _pdf_registry()
    tool = create_write_document_tool(registry)
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    source = tmp_path / "source.pdf"
    from pypdf import PdfWriter

    source_writer = PdfWriter()
    source_writer.add_blank_page(width=100, height=100)
    with source.open("wb") as stream:
        source_writer.write(stream)
    source_bytes = source.read_bytes()
    revision = workspace / "revision.json"
    revision.write_text(json.dumps({
        "blocks": [{"type": "paragraph", "text": "new"}],
    }), encoding="utf-8")
    missing = workspace / "missing.json"
    missing.write_text(json.dumps({
        "blocks": [{"type": "image", "workspace_path": "work/missing.png"}],
    }), encoding="utf-8")
    attachment = {
        "id": "pdf-source",
        "name": "source.pdf",
        "kind": "document",
        "local_path": str(source),
    }

    with bind_tool_execution(
        tool_call_id="call-pdf-invalid",
        tool_name="write_document",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(outputs),
    ):
        revision_result = tool.execute(
            format="pdf",
            specification_path="revision.json",
            output_name="revision.pdf",
            source_attachment_id="pdf-source",
        )
        missing_result = tool.execute(
            format="pdf",
            specification_path="missing.json",
            output_name="missing.pdf",
        )

    assert "不支持修改" in revision_result["error"]
    assert "error" in missing_result
    assert source.read_bytes() == source_bytes
    assert not list(outputs.glob("*.pdf"))
