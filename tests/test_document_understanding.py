from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from xiaomei_brain.documents.models import DocumentExtraction, DocumentSection
from xiaomei_brain.documents.service import DocumentService
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.plugins.tools.document_pdf.extractor import PdfExtractor
from xiaomei_brain.plugins.tools.document_presentation.extractor import PresentationExtractor
from xiaomei_brain.plugins.tools.document_spreadsheet.extractor import SpreadsheetExtractor
from xiaomei_brain.plugins.tools.document_word.extractor import WordExtractor
from xiaomei_brain.plugins.tools.document_io.tool import create_read_document_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _office_file(path: Path, files: dict[str, str]) -> Path:
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def test_word_plugin_extracts_paragraphs_and_tables(tmp_path):
    path = _office_file(tmp_path / "plan.docx", {
        "word/document.xml": """
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>Project brief</w:t></w:r></w:p>
            <w:tbl><w:tr>
              <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
              <w:tc><w:p><w:r><w:t>Xiaomei</w:t></w:r></w:p></w:tc>
            </w:tr></w:tbl>
          </w:body>
        </w:document>
        """,
    })

    result = WordExtractor().extract(path)

    assert result.sections[0].key == "document"
    assert "Project brief" in result.sections[0].content
    assert "[表格 1 | 1 行 × 2 列]" in result.sections[0].content
    assert "Name\tXiaomei" in result.sections[0].content
    assert result.metadata["table_count"] == 1
    assert result.metadata["tables"] == [{"index": 1, "rows": 1, "columns": 2}]


def test_presentation_plugin_returns_one_section_per_slide(tmp_path):
    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    path = _office_file(tmp_path / "deck.pptx", {
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="urn:p" xmlns:a="{ns}"><a:t>Positioning</a:t></p:sld>',
        "ppt/slides/slide2.xml": f'<p:sld xmlns:p="urn:p" xmlns:a="{ns}"><a:t>Architecture</a:t></p:sld>',
        "ppt/notesSlides/notesSlide1.xml": f'<p:notes xmlns:p="urn:p" xmlns:a="{ns}"><a:t>Speaker note</a:t></p:notes>',
    })

    result = PresentationExtractor().extract(path)

    assert [section.key for section in result.sections] == ["slide:1", "slide:2"]
    assert "Speaker note" in result.sections[0].content
    assert "Architecture" in result.sections[1].content


def test_pdf_plugin_reports_scanned_document(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "scan.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as stream:
        writer.write(stream)

    result = PdfExtractor().extract(path)

    assert result.sections[0].key == "page:1"
    assert result.metadata["requires_ocr"] is True


def test_spreadsheet_plugin_returns_one_section_per_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "data.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Summary"
    workbook.active.append(["Metric", "Value"])
    workbook.active.append(["Users", 12])
    workbook.create_sheet("Details").append(["A", "B"])
    workbook.save(path)

    result = SpreadsheetExtractor().extract(path)

    assert [section.key for section in result.sections] == ["sheet:1", "sheet:2"]
    assert result.sections[0].title == "Summary"
    assert "Users\t12" in result.sections[0].content


class _CountingExtractor:
    extractor_id = "counting"
    extractor_version = "1"
    suffixes = (".docx",)
    mime_types = ("application/test-document",)

    def __init__(self):
        self.calls = 0

    def extract(self, path):
        self.calls += 1
        return DocumentExtraction(
            self.extractor_id,
            self.extractor_version,
            (DocumentSection("document", "Body", "0123456789"),),
        )


def test_document_service_caches_by_asset_hash_and_supports_paging(tmp_path):
    path = tmp_path / "test.docx"
    path.write_bytes(b"first")
    extractor = _CountingExtractor()
    registry = PluginRegistry()
    registry.register_document_extractor(extractor)
    service = DocumentService(registry, tmp_path / "brain.db")
    attachment = {
        "id": "asset-1", "name": "test.docx", "mime_type": "application/test-document",
        "kind": "document", "local_path": str(path),
    }

    first = service.read(attachment, session_id="session-1", limit=4)
    second = service.read(attachment, session_id="session-1", offset=4, limit=4)
    path.write_bytes(b"changed")
    service.read(attachment, session_id="session-1", limit=4)

    assert first["content"] == "0123" and first["next_offset"] == 4
    assert second["content"] == "4567" and second["next_offset"] == 8
    assert extractor.calls == 2


def test_read_document_tool_accepts_current_turn_attachment(tmp_path):
    path = tmp_path / "test.docx"
    path.write_bytes(b"content")
    extractor = _CountingExtractor()
    registry = PluginRegistry()
    registry.register_document_extractor(extractor)
    tool = create_read_document_tool(registry, lambda: SimpleNamespace(db_path=tmp_path / "brain.db"))
    attachment = {
        "id": "allowed", "name": "test.docx", "mime_type": "application/test-document",
        "kind": "document", "local_path": str(path),
    }

    with bind_tool_execution(
        tool_call_id="call-1", tool_name="read_document", arguments={},
        artifact_callback=None, session_id="session-1", attachments=(attachment,),
    ):
        allowed = tool.execute(attachment_id="allowed", limit=5)
        denied = tool.execute(attachment_id="another")

    assert allowed["content"] == "01234"
    assert "error" in denied


def test_read_document_restores_attachment_from_current_session(tmp_path, monkeypatch):
    path = tmp_path / "stored.docx"
    path.write_bytes(b"content")
    extractor = _CountingExtractor()
    registry = PluginRegistry()
    registry.register_document_extractor(extractor)

    from xiaomei_brain.memory.conversation_db import ConversationDB
    db_path = tmp_path / "brain.db"
    ConversationDB(db_path).log(
        "session-1",
        "user",
        "attached",
        user_id="person-1",
        metadata={"attachments": [{
            "id": "session-asset",
            "name": "stored.docx",
            "mime_type": "application/test-document",
            "size": 7,
            "kind": "document",
        }]},
    )

    def restore(agent_id, session_id, attachments):
        assert agent_id == "test"
        assert session_id == "session-1"
        assert attachments[0]["id"] == "session-asset"
        return ([{**attachments[0], "local_path": str(path)}], [])

    monkeypatch.setattr(
        "xiaomei_brain.gateway.attachments.restore_attachment_refs",
        restore,
    )
    tool = create_read_document_tool(
        registry,
        lambda: SimpleNamespace(db_path=db_path, agent_id="test"),
    )

    with bind_tool_execution(
        tool_call_id="call-session",
        tool_name="read_document",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        person_id="person-1",
        attachments=(),
    ):
        restored = tool.execute(attachment_id="session-asset", limit=5)
        denied = tool.execute(attachment_id="missing")

    assert restored["content"] == "01234"
    assert "error" in denied


def test_read_document_prefers_live_agent_artifact_over_ingress_snapshot(tmp_path):
    class ContentExtractor(_CountingExtractor):
        def extract(self, path):
            self.calls += 1
            return DocumentExtraction(
                self.extractor_id,
                self.extractor_version,
                (DocumentSection("document", "Body", path.read_text(encoding="utf-8")),),
            )

    snapshot = tmp_path / "snapshot.docx"
    snapshot.write_text("old", encoding="utf-8")
    managed = tmp_path / "managed.docx"
    managed.write_text("current", encoding="utf-8")
    extractor = ContentExtractor()
    registry = PluginRegistry()
    registry.register_document_extractor(extractor)
    tool = create_read_document_tool(
        registry,
        lambda: SimpleNamespace(db_path=tmp_path / "brain.db"),
    )
    attachment = {
        "id": "artifact-1",
        "name": "managed.docx",
        "mime_type": "application/test-document",
        "kind": "document",
        "local_path": str(snapshot),
        "managed_artifact_path": str(managed),
    }

    with bind_tool_execution(
        tool_call_id="call-live",
        tool_name="read_document",
        arguments={},
        artifact_callback=None,
        session_id="session-1",
        attachments=(attachment,),
    ):
        first = tool.execute(attachment_id="artifact-1")
        managed.write_text("latest", encoding="utf-8")
        second = tool.execute(attachment_id="artifact-1")

    assert first["content"] == "current"
    assert second["content"] == "latest"
    assert extractor.calls == 2
