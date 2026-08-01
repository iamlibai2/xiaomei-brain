"""Deterministic PDF creation from structured document blocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

from .extractor import PdfExtractor


MAX_BLOCKS = 2_000
MAX_TABLE_ROWS = 5_000
MAX_TABLE_COLUMNS = 50
MAX_TEXT_LENGTH = 200_000

DEFAULT_THEME = {
    "font": "STSong-Light",
    "title_color": "172033",
    "text_color": "354052",
    "accent_color": "4F6BED",
    "muted_color": "6B7280",
    "title_size_pt": 24,
    "body_size_pt": 10.5,
    "line_spacing": 1.45,
}


class PdfWriter:
    format_id = "pdf"
    suffix = ".pdf"
    writer_version = "1.0.0"

    def write(
        self,
        specification: dict[str, Any],
        output_path: Path,
        *,
        source_path: Path | None = None,
        asset_paths: dict[str, Path] | None = None,
    ) -> dict[str, Any]:
        if source_path is not None:
            raise ValueError("PDF writer 第一版不支持修改已有 PDF，请创建新的 PDF")
        try:
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate
        except ImportError as exc:
            raise ValueError("PDF 写入依赖 reportlab 未安装") from exc

        blocks = specification.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("创建 PDF 时 specification.blocks 必须是非空数组")
        if len(blocks) > MAX_BLOCKS:
            raise ValueError(f"PDF 不能超过 {MAX_BLOCKS} 个内容块")

        theme = self._theme(specification.get("theme"))
        self._register_font(theme["font"])
        page_size, margins = self._page(specification.get("page"))
        styles = self._styles(getSampleStyleSheet(), theme)
        story, image_count = self._build_story(
            blocks,
            styles=styles,
            theme=theme,
            asset_paths=asset_paths,
            available_width=page_size[0] - margins[1] - margins[3],
            available_height=page_size[1] - margins[0] - margins[2] - 36,
        )
        properties = self._properties(specification.get("properties"))
        header = self._header_footer(specification.get("header"), "header")
        footer = self._header_footer(specification.get("footer"), "footer")
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=page_size,
            rightMargin=margins[1],
            leftMargin=margins[3],
            topMargin=margins[0] + (18 if header["text"] else 0),
            bottomMargin=margins[2] + (
                18 if footer["text"] or footer["page_number"] else 0
            ),
            title=properties["title"],
            author=properties["author"],
            subject=properties["subject"],
            creator="xiaomei-brain",
        )
        on_page = self._page_callback(
            page_size=page_size,
            margins=margins,
            theme=theme,
            properties=properties,
            header=header,
            footer=footer,
        )
        document.build(story, onFirstPage=on_page, onLaterPages=on_page)

        try:
            from pypdf import PdfReader

            reader = PdfReader(str(output_path))
        except ImportError as exc:
            raise ValueError("PDF 验收依赖 pypdf 未安装") from exc
        if reader.is_encrypted or not reader.pages:
            raise ValueError("生成的 PDF 无法正常重新读取")
        extraction = PdfExtractor().extract(output_path)
        preview = extraction.sections[0].content[:1200] if extraction.sections else ""
        if extraction.metadata.get("requires_ocr"):
            raise ValueError("生成的 PDF 没有可读取的文本层")
        return {
            "writer": self.format_id,
            "writer_version": self.writer_version,
            "validation": {
                "valid": True,
                "page_count": len(reader.pages),
                "block_count": len(blocks),
                "image_count": image_count,
                "has_text_layer": True,
                "content_preview": preview,
            },
        }

    @staticmethod
    def _register_font(font_name: str) -> None:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        if font_name in pdfmetrics.getRegisteredFontNames():
            return
        if font_name == "STSong-Light":
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
            return
        if font_name not in {
            "Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold",
            "Courier", "Courier-Bold",
        }:
            raise ValueError(
                "theme.font 仅支持 STSong-Light、Helvetica、Times-Roman 或 Courier"
            )

    @staticmethod
    def _bold_font(font_name: str) -> str:
        return {
            "Helvetica": "Helvetica-Bold",
            "Times-Roman": "Times-Bold",
            "Courier": "Courier-Bold",
        }.get(font_name, font_name)

    @classmethod
    def _theme(cls, values: Any) -> dict[str, Any]:
        if values is not None and not isinstance(values, dict):
            raise ValueError("theme 必须是对象")
        theme = {**DEFAULT_THEME, **(values or {})}
        theme["font"] = str(theme["font"] or "").strip()
        if not theme["font"]:
            raise ValueError("theme.font 不能为空")
        for key in ("title_color", "text_color", "accent_color", "muted_color"):
            theme[key] = cls._hex_color(theme[key], f"theme.{key}")
        for key, minimum, maximum in (
            ("title_size_pt", 14, 48),
            ("body_size_pt", 7, 20),
            ("line_spacing", 1.0, 2.5),
        ):
            value = float(theme[key])
            if not minimum <= value <= maximum:
                raise ValueError(f"theme.{key} 必须在 {minimum} 到 {maximum} 之间")
            theme[key] = value
        return theme

    @staticmethod
    def _hex_color(value: Any, field: str) -> str:
        color = str(value or "").strip().lstrip("#").upper()
        if len(color) != 6 or any(ch not in "0123456789ABCDEF" for ch in color):
            raise ValueError(f"{field} 必须是 6 位十六进制颜色")
        return color

    @staticmethod
    def _page(values: Any):
        from reportlab.lib.pagesizes import A4, LETTER, landscape
        from reportlab.lib.units import cm

        if values is not None and not isinstance(values, dict):
            raise ValueError("page 必须是对象")
        values = values or {}
        size_name = str(values.get("size") or "A4").upper()
        sizes = {"A4": A4, "LETTER": LETTER}
        if size_name not in sizes:
            raise ValueError("page.size 仅支持 A4 或 Letter")
        orientation = str(values.get("orientation") or "portrait").lower()
        if orientation not in {"portrait", "landscape"}:
            raise ValueError("page.orientation 仅支持 portrait 或 landscape")
        page_size = landscape(sizes[size_name]) if orientation == "landscape" else sizes[size_name]
        margin_values = values.get("margins_cm", {})
        if not isinstance(margin_values, dict):
            raise ValueError("page.margins_cm 必须是对象")
        margins = []
        for key in ("top", "right", "bottom", "left"):
            margin = float(margin_values.get(key, 2.2))
            if not 0.5 <= margin <= 8:
                raise ValueError(f"page.margins_cm.{key} 必须在 0.5 到 8 之间")
            margins.append(margin * cm)
        return page_size, tuple(margins)

    @staticmethod
    def _properties(values: Any) -> dict[str, str]:
        if values is not None and not isinstance(values, dict):
            raise ValueError("properties 必须是对象")
        values = values or {}
        return {
            "title": str(values.get("title") or ""),
            "author": str(values.get("author") or values.get("creator") or ""),
            "subject": str(values.get("subject") or values.get("description") or ""),
            "keywords": str(values.get("keywords") or ""),
        }

    @staticmethod
    def _header_footer(values: Any, field: str) -> dict[str, Any]:
        if values is not None and not isinstance(values, dict):
            raise ValueError(f"{field} 必须是对象")
        values = values or {}
        return {
            "text": str(values.get("text") or ""),
            "page_number": values.get("page_number") is True,
        }

    @classmethod
    def _styles(cls, sample: Any, theme: dict[str, Any]) -> dict[str, Any]:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
        from reportlab.lib.styles import ParagraphStyle

        body_size = theme["body_size_pt"]
        leading = body_size * theme["line_spacing"]
        common = {
            "fontName": theme["font"],
            "textColor": HexColor("#" + theme["text_color"]),
            "fontSize": body_size,
            "leading": leading,
            "spaceAfter": body_size * 0.75,
        }
        return {
            "body": ParagraphStyle("XiaomeiBody", parent=sample["BodyText"], **common),
            "quote": ParagraphStyle(
                "XiaomeiQuote", parent=sample["BodyText"],
                **{
                    **common,
                    "textColor": HexColor("#" + theme["muted_color"]),
                },
                leftIndent=14, rightIndent=14,
                borderColor=HexColor("#" + theme["accent_color"]),
                borderWidth=1.5, borderPadding=8,
            ),
            "caption": ParagraphStyle(
                "XiaomeiCaption", parent=sample["BodyText"],
                fontName=theme["font"], fontSize=max(7, body_size - 2),
                leading=max(9, leading - 2), alignment=TA_CENTER,
                textColor=HexColor("#" + theme["muted_color"]), spaceAfter=8,
            ),
            "alignments": {
                "left": TA_LEFT, "center": TA_CENTER,
                "right": TA_RIGHT, "justify": TA_JUSTIFY,
            },
            "heading_sizes": {
                1: theme["title_size_pt"],
                2: max(body_size + 6, theme["title_size_pt"] - 6),
                3: max(body_size + 3, theme["title_size_pt"] - 11),
            },
        }

    @staticmethod
    def _safe_text(value: Any) -> str:
        text = str(value or "")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"单个文本内容不能超过 {MAX_TEXT_LENGTH} 个字符")
        return escape(text).replace("\n", "<br/>")

    @classmethod
    def _paragraph(cls, text: Any, style: Any, *, align: str | None = None, styles: Any = None):
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph

        target = style
        if align:
            alignments = styles["alignments"]
            if align not in alignments:
                raise ValueError("align 仅支持 left、center、right 或 justify")
            target = ParagraphStyle(f"{style.name}-{align}", parent=style, alignment=alignments[align])
        return Paragraph(cls._safe_text(text), target)

    @classmethod
    def _heading_style(cls, level: int, styles: Any, theme: dict[str, Any]):
        from reportlab.lib.colors import HexColor
        from reportlab.lib.styles import ParagraphStyle

        size = styles["heading_sizes"][level]
        return ParagraphStyle(
            f"XiaomeiHeading{level}", parent=styles["body"],
            fontName=cls._bold_font(theme["font"]), fontSize=size,
            leading=size * 1.25, textColor=HexColor("#" + theme["title_color"]),
            spaceBefore=12 if level > 1 else 0, spaceAfter=10, keepWithNext=True,
        )

    @classmethod
    def _build_story(
        cls,
        blocks: Iterable[Any],
        *,
        styles: dict[str, Any],
        theme: dict[str, Any],
        asset_paths: dict[str, Path] | None,
        available_width: float,
        available_height: float,
    ) -> tuple[list[Any], int]:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.units import cm
        from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

        story = []
        image_count = 0
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("PDF block 必须是对象")
            kind = str(block.get("type") or "paragraph").lower()
            if kind == "heading":
                level = int(block.get("level", 1))
                if level not in {1, 2, 3}:
                    raise ValueError("heading.level 仅支持 1、2 或 3")
                story.append(cls._paragraph(block.get("text"), cls._heading_style(level, styles, theme)))
            elif kind == "paragraph":
                story.append(cls._paragraph(
                    block.get("text"), styles["body"],
                    align=str(block.get("align") or "left").lower(), styles=styles,
                ))
            elif kind == "quote":
                story.append(cls._paragraph(block.get("text"), styles["quote"]))
            elif kind == "list":
                items = block.get("items")
                if not isinstance(items, list):
                    raise ValueError("list.items 必须是数组")
                ordered = block.get("ordered") is True
                for index, item in enumerate(items, start=1):
                    prefix = f"{index}. " if ordered else "• "
                    story.append(cls._paragraph(prefix + str(item), styles["body"]))
            elif kind == "table":
                headers = block.get("headers", [])
                rows = block.get("rows", [])
                if not isinstance(headers, list) or not isinstance(rows, list):
                    raise ValueError("table.headers 和 table.rows 必须是数组")
                if len(rows) > MAX_TABLE_ROWS:
                    raise ValueError(f"PDF 表格不能超过 {MAX_TABLE_ROWS} 行")
                width = len(headers) or max((len(row) for row in rows if isinstance(row, list)), default=0)
                if not 1 <= width <= MAX_TABLE_COLUMNS:
                    raise ValueError(f"PDF 表格列数必须在 1 到 {MAX_TABLE_COLUMNS} 之间")
                data = [list(map(str, headers[:width]))] if headers else []
                for row in rows:
                    if not isinstance(row, list):
                        raise ValueError("table.rows 中的每一项必须是数组")
                    padded = list(row[:width]) + [""] * max(0, width - len(row))
                    data.append([Paragraph(cls._safe_text(value), styles["body"]) for value in padded])
                if not data:
                    raise ValueError("PDF 表格不能为空")
                column_widths = block.get("column_widths")
                if column_widths is not None:
                    if not isinstance(column_widths, list) or len(column_widths) != width:
                        raise ValueError("table.column_widths 必须与列数相同")
                    parsed_widths = [float(value) * cm for value in column_widths]
                    if any(value <= 0 for value in parsed_widths):
                        raise ValueError("table.column_widths 必须大于 0")
                    if sum(parsed_widths) > available_width * 1.02:
                        raise ValueError("table.column_widths 超出页面可用宽度")
                else:
                    parsed_widths = [available_width / width] * width
                table = Table(data, colWidths=parsed_widths, repeatRows=1 if headers else 0)
                commands = [
                    ("FONTNAME", (0, 0), (-1, -1), theme["font"]),
                    ("FONTSIZE", (0, 0), (-1, -1), theme["body_size_pt"]),
                    ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#" + theme["text_color"])),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#D7DCE5")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
                if headers:
                    commands.extend([
                        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#" + theme["accent_color"])),
                        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
                    ])
                table.setStyle(TableStyle(commands))
                story.extend([table, Spacer(1, 10)])
            elif kind == "image":
                image_path = cls._asset_path(block, asset_paths)
                image = Image(str(image_path))
                width_cm = float(block.get("width_cm", 12))
                if not 0 < width_cm <= 50:
                    raise ValueError("image.width_cm 必须大于 0 且不超过 50")
                target_width = min(width_cm * cm, available_width)
                target_height = target_width * image.imageHeight / image.imageWidth
                if block.get("height_cm") is not None:
                    target_height = float(block["height_cm"]) * cm
                    if target_height <= 0 or target_height > 70 * cm:
                        raise ValueError("image.height_cm 必须大于 0 且不超过 70")
                if target_height > available_height:
                    scale = available_height / target_height
                    target_width *= scale
                    target_height *= scale
                image.drawWidth, image.drawHeight = target_width, target_height
                align = str(block.get("align") or "center").lower()
                if align not in {"left", "center", "right"}:
                    raise ValueError("image.align 仅支持 left、center 或 right")
                image.hAlign = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[align]
                content = [image]
                caption = str(block.get("caption") or "").strip()
                if caption:
                    content.append(cls._paragraph(caption, styles["caption"]))
                story.append(KeepTogether(content))
                image_count += 1
            elif kind == "spacer":
                height = float(block.get("height_cm", 0.5))
                if not 0 <= height <= 10:
                    raise ValueError("spacer.height_cm 必须在 0 到 10 之间")
                story.append(Spacer(1, height * cm))
            elif kind == "page_break":
                story.append(PageBreak())
            else:
                raise ValueError(f"不支持的 PDF block: {kind}")
        return story, image_count

    @staticmethod
    def _asset_path(values: dict[str, Any], asset_paths: dict[str, Path] | None) -> Path:
        attachment_id = str(values.get("attachment_id") or "").strip()
        workspace_path = str(values.get("workspace_path") or "").strip()
        if bool(attachment_id) == bool(workspace_path):
            raise ValueError("image 必须且只能提供 attachment_id 或 workspace_path 之一")
        key = attachment_id or f"workspace:{workspace_path}"
        path = (asset_paths or {}).get(key)
        if path is None or not path.is_file():
            raise ValueError(f"当前执行现场没有可用图片: {attachment_id or workspace_path}")
        return path

    @classmethod
    def _page_callback(
        cls, *, page_size: Any, margins: Any, theme: dict[str, Any],
        properties: dict[str, str], header: dict[str, Any], footer: dict[str, Any],
    ):
        from reportlab.lib.colors import HexColor

        def draw(canvas: Any, document: Any) -> None:
            canvas.saveState()
            canvas.setTitle(properties["title"])
            canvas.setAuthor(properties["author"])
            canvas.setSubject(properties["subject"])
            canvas.setKeywords(properties["keywords"])
            canvas.setFont(theme["font"], max(7, theme["body_size_pt"] - 2))
            canvas.setFillColor(HexColor("#" + theme["muted_color"]))
            if header["text"]:
                canvas.drawString(margins[3], page_size[1] - margins[0] + 7, header["text"])
            footer_parts = []
            if footer["text"]:
                footer_parts.append(footer["text"])
            if footer["page_number"]:
                footer_parts.append(str(document.page))
            if footer_parts:
                canvas.drawRightString(
                    page_size[0] - margins[1], margins[2] - 11, " ".join(footer_parts),
                )
            canvas.restoreState()

        return draw
