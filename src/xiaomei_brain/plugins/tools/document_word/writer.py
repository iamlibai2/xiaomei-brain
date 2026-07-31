"""Deterministic DOCX creation and common non-destructive revisions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

from xiaomei_brain.plugins.tools.document_word.extractor import WordExtractor


class WordWriter:
    format_id = "word"
    suffix = ".docx"
    writer_version = "1.0.0"

    def write(
        self,
        specification: dict[str, Any],
        output_path: Path,
        *,
        source_path: Path | None = None,
    ) -> dict[str, Any]:
        try:
            from docx import Document
        except ImportError as exc:
            raise ValueError("Word 写入依赖 python-docx 未安装") from exc

        if source_path is not None:
            if source_path.suffix.lower() != self.suffix:
                raise ValueError("Word writer 只能修改 DOCX 附件")
            shutil.copy2(source_path, output_path)
            document = Document(str(output_path))
            operations = specification.get("operations")
            if not isinstance(operations, list) or not operations:
                raise ValueError("修改 Word 文档时 specification.operations 不能为空")
            replacements = 0
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ValueError("Word operation 必须是对象")
                kind = str(operation.get("type") or "")
                if kind == "replace_text":
                    old = str(operation.get("old") or "")
                    new = str(operation.get("new") or "")
                    if not old:
                        raise ValueError("replace_text.old 不能为空")
                    replacements += self._replace_text(
                        document,
                        old,
                        new,
                        replace_all=operation.get("all") is True,
                    )
                elif kind == "append_blocks":
                    blocks = operation.get("blocks")
                    if not isinstance(blocks, list):
                        raise ValueError("append_blocks.blocks 必须是数组")
                    self._append_blocks(document, blocks)
                elif kind == "set_properties":
                    self._set_properties(document, operation)
                else:
                    raise ValueError(f"不支持的 Word operation: {kind}")
            document.save(str(output_path))
        else:
            document = Document()
            self._set_properties(document, specification.get("properties", {}))
            title = str(specification.get("title") or "").strip()
            if title:
                document.add_heading(title, level=0)
            subtitle = str(specification.get("subtitle") or "").strip()
            if subtitle:
                document.add_paragraph(subtitle, style="Subtitle")
            blocks = specification.get("blocks")
            if not isinstance(blocks, list) or not blocks:
                raise ValueError("创建 Word 文档时 specification.blocks 不能为空")
            self._append_blocks(document, blocks)
            document.save(str(output_path))
            replacements = 0

        # Structural and semantic verification happen before the file is
        # announced as an artifact.
        verified = Document(str(output_path))
        if not verified.paragraphs and not verified.tables:
            raise ValueError("生成的 Word 文档为空")
        extraction = WordExtractor().extract(output_path)
        preview = extraction.sections[0].content[:1200] if extraction.sections else ""
        return {
            "writer": self.format_id,
            "writer_version": self.writer_version,
            "validation": {
                "valid": True,
                "paragraphs": len(verified.paragraphs),
                "tables": len(verified.tables),
                "replacements": replacements,
                "content_preview": preview,
            },
        }

    @staticmethod
    def _set_properties(document: Any, values: Any) -> None:
        if not isinstance(values, dict):
            return
        properties = document.core_properties
        for key in ("title", "subject", "author", "keywords", "comments"):
            if key in values:
                setattr(properties, key, str(values[key]))

    def _append_blocks(self, document: Any, blocks: Iterable[Any]) -> None:
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("Word block 必须是对象")
            kind = str(block.get("type") or "paragraph")
            if kind == "heading":
                level = max(1, min(int(block.get("level", 1)), 9))
                document.add_heading(str(block.get("text") or ""), level=level)
            elif kind == "paragraph":
                paragraph = document.add_paragraph(str(block.get("text") or ""))
                style = str(block.get("style") or "").strip()
                if style:
                    try:
                        paragraph.style = style
                    except KeyError as exc:
                        raise ValueError(f"Word 样式不存在: {style}") from exc
            elif kind == "list":
                items = block.get("items")
                if not isinstance(items, list):
                    raise ValueError("list.items 必须是数组")
                style = "List Number" if block.get("ordered") is True else "List Bullet"
                for item in items:
                    document.add_paragraph(str(item), style=style)
            elif kind == "table":
                headers = block.get("headers", [])
                rows = block.get("rows", [])
                if not isinstance(headers, list) or not isinstance(rows, list):
                    raise ValueError("table.headers 和 table.rows 必须是数组")
                width = len(headers) or max(
                    (len(row) for row in rows if isinstance(row, list)),
                    default=0,
                )
                if width <= 0:
                    raise ValueError("表格至少需要一列")
                table = document.add_table(rows=1 if headers else 0, cols=width)
                table.style = str(block.get("style") or "Table Grid")
                if headers:
                    for index, value in enumerate(headers[:width]):
                        table.rows[0].cells[index].text = str(value)
                for row in rows:
                    if not isinstance(row, list):
                        raise ValueError("table.rows 中每一项必须是数组")
                    cells = table.add_row().cells
                    for index, value in enumerate(row[:width]):
                        cells[index].text = str(value)
            elif kind == "page_break":
                document.add_page_break()
            elif kind == "quote":
                document.add_paragraph(str(block.get("text") or ""), style="Quote")
            else:
                raise ValueError(f"不支持的 Word block: {kind}")

    @staticmethod
    def _paragraphs(document: Any) -> Iterable[Any]:
        yield from document.paragraphs
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from cell.paragraphs

    def _replace_text(
        self,
        document: Any,
        old: str,
        new: str,
        *,
        replace_all: bool,
    ) -> int:
        count = 0
        for paragraph in self._paragraphs(document):
            if old not in paragraph.text:
                continue
            replacements = paragraph.text.count(old) if replace_all else 1
            updated = paragraph.text.replace(old, new, -1 if replace_all else 1)
            if paragraph.runs:
                paragraph.runs[0].text = updated
                for run in paragraph.runs[1:]:
                    run.text = ""
            else:
                paragraph.add_run(updated)
            count += replacements
            if not replace_all:
                break
        if count == 0:
            raise ValueError(f"Word 文档中没有找到要替换的文字: {old}")
        return count
