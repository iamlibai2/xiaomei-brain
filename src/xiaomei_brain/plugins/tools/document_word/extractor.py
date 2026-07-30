"""DOCX paragraphs and tables, preserving their document order."""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from xiaomei_brain.documents.models import DocumentExtraction, DocumentSection
from xiaomei_brain.documents.office_xml import bounded_text, read_xml


_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_WORD_NS}t")).strip()


class WordExtractor:
    extractor_id = "document_word"
    extractor_version = "1.0.0"
    suffixes = (".docx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    def extract(self, path: Path) -> DocumentExtraction:
        try:
            with ZipFile(path) as archive:
                root = read_xml(archive, "word/document.xml")
        except (BadZipFile, KeyError, ValueError) as exc:
            raise ValueError(f"无法解析 Word 文档: {path.name}") from exc
        body = root.find(f"{_WORD_NS}body")
        if body is None:
            raise ValueError(f"Word 文档没有正文: {path.name}")
        blocks: list[str] = []
        for child in body:
            if child.tag == f"{_WORD_NS}p":
                value = _text(child)
                if value:
                    blocks.append(value)
            elif child.tag == f"{_WORD_NS}tbl":
                rows = []
                for row in child.findall(f"{_WORD_NS}tr"):
                    cells = [_text(cell) for cell in row.findall(f"{_WORD_NS}tc")]
                    if any(cells):
                        rows.append("\t".join(cells))
                if rows:
                    blocks.append("[表格]\n" + "\n".join(rows))
        content = bounded_text("\n\n".join(blocks) or "[文档中没有可提取的文字]")
        return DocumentExtraction(
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            sections=(DocumentSection("document", "正文", content),),
            metadata={"format": "docx"},
        )
