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
        tables: list[dict[str, int]] = []
        for child in body:
            if child.tag == f"{_WORD_NS}p":
                value = _text(child)
                if value:
                    blocks.append(value)
            elif child.tag == f"{_WORD_NS}tbl":
                table_index = len(tables) + 1
                rows = []
                row_elements = child.findall(f"{_WORD_NS}tr")
                column_count = 0
                for row in row_elements:
                    cells = [_text(cell) for cell in row.findall(f"{_WORD_NS}tc")]
                    column_count = max(column_count, len(cells))
                    if any(cells):
                        rows.append("\t".join(cells))
                tables.append({
                    "index": table_index,
                    "rows": len(row_elements),
                    "columns": column_count,
                })
                heading = f"[表格 {table_index} | {len(row_elements)} 行 × {column_count} 列]"
                blocks.append(heading + ("\n" + "\n".join(rows) if rows else ""))
        content = bounded_text("\n\n".join(blocks) or "[文档中没有可提取的文字]")
        return DocumentExtraction(
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            sections=(DocumentSection("document", "正文", content),),
            metadata={
                "format": "docx",
                "table_count": len(tables),
                "tables": tables,
            },
        )
