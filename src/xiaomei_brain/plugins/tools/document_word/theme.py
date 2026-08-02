"""Deterministic professional themes for generated Word documents."""

from __future__ import annotations

import re
from typing import Any


_HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")


WORD_THEME_PRESETS: dict[str, dict[str, Any]] = {
    "business-blue": {
        "heading_font": "Microsoft YaHei",
        "body_font": "Microsoft YaHei",
        "primary_color": "17365D",
        "accent_color": "2F75B5",
        "text_color": "263238",
        "muted_color": "6B7280",
        "surface_color": "EAF1F8",
        "alternate_row_color": "F5F8FC",
    },
    "modern-minimal": {
        "heading_font": "Microsoft YaHei",
        "body_font": "Microsoft YaHei",
        "primary_color": "202124",
        "accent_color": "5F6368",
        "text_color": "303134",
        "muted_color": "74777C",
        "surface_color": "ECEFF1",
        "alternate_row_color": "F7F8F9",
    },
    "warm-professional": {
        "heading_font": "Microsoft YaHei",
        "body_font": "Microsoft YaHei",
        "primary_color": "6B3F2A",
        "accent_color": "B86F45",
        "text_color": "352F2B",
        "muted_color": "786B63",
        "surface_color": "F4E9E1",
        "alternate_row_color": "FBF7F4",
    },
    "technology": {
        "heading_font": "Microsoft YaHei",
        "body_font": "Microsoft YaHei",
        "primary_color": "123B5D",
        "accent_color": "008C95",
        "text_color": "20313D",
        "muted_color": "60727D",
        "surface_color": "E3F1F3",
        "alternate_row_color": "F3F9FA",
    },
}


_DEFAULT_METRICS: dict[str, Any] = {
    "title_size_pt": 28.0,
    "subtitle_size_pt": 12.0,
    "body_size_pt": 10.5,
    "heading_1_size_pt": 17.0,
    "heading_2_size_pt": 13.5,
    "heading_3_size_pt": 11.5,
    "line_spacing": 1.45,
    "paragraph_space_after_pt": 6.0,
}


def resolve_word_theme(values: Any) -> dict[str, Any]:
    """Resolve one preset plus safe per-document overrides."""
    if values is not None and not isinstance(values, dict):
        raise ValueError("theme 必须是对象")
    values = values or {}
    preset = str(values.get("preset") or "business-blue").strip().lower()
    if preset not in WORD_THEME_PRESETS:
        available = "、".join(WORD_THEME_PRESETS)
        raise ValueError(f"未知 Word 主题: {preset}；可用主题: {available}")
    theme = {
        "preset": preset,
        **WORD_THEME_PRESETS[preset],
        **_DEFAULT_METRICS,
    }
    allowed = set(theme) - {"preset"}
    for key, value in values.items():
        if key in allowed:
            theme[key] = value

    for key in (
        "primary_color",
        "accent_color",
        "text_color",
        "muted_color",
        "surface_color",
        "alternate_row_color",
    ):
        color = str(theme[key]).lstrip("#")
        if not _HEX_COLOR.fullmatch(color):
            raise ValueError(f"theme.{key} 必须是六位十六进制颜色")
        theme[key] = color.upper()
    for key in ("heading_font", "body_font"):
        font = str(theme[key]).strip()
        if not font:
            raise ValueError(f"theme.{key} 不能为空")
        theme[key] = font
    for key in (
        "title_size_pt",
        "subtitle_size_pt",
        "body_size_pt",
        "heading_1_size_pt",
        "heading_2_size_pt",
        "heading_3_size_pt",
    ):
        size = float(theme[key])
        if not 6 <= size <= 72:
            raise ValueError(f"theme.{key} 必须在 6 到 72 之间")
        theme[key] = size
    line_spacing = float(theme["line_spacing"])
    if not 1 <= line_spacing <= 3:
        raise ValueError("theme.line_spacing 必须在 1 到 3 之间")
    theme["line_spacing"] = line_spacing
    paragraph_spacing = float(theme["paragraph_space_after_pt"])
    if not 0 <= paragraph_spacing <= 36:
        raise ValueError("theme.paragraph_space_after_pt 必须在 0 到 36 之间")
    theme["paragraph_space_after_pt"] = paragraph_spacing
    return theme


def _set_style_font(
    style: Any,
    *,
    name: str,
    size_pt: float,
    color: str,
    bold: bool | None = None,
) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    style.font.name = name
    style.font.size = Pt(size_pt)
    style.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        style.font.bold = bold
    fonts = style._element.get_or_add_rPr().rFonts
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{attribute}"), name)
    # Built-in Word styles commonly retain theme font attributes. OOXML
    # consumers may prefer those over the explicit family and silently render
    # a different font, so remove them whenever a concrete family is chosen.
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        qualified = qn(f"w:{attribute}")
        if qualified in fonts.attrib:
            del fonts.attrib[qualified]


def _set_run_font(run: Any, name: str) -> None:
    from docx.oxml.ns import qn

    run.font.name = name
    fonts = run._element.get_or_add_rPr().rFonts
    for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{attribute}"), name)
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        qualified = qn(f"w:{attribute}")
        if qualified in fonts.attrib:
            del fonts.attrib[qualified]


def _set_style_border(style: Any, *, edge: str, color: str, size: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = style._element.get_or_add_pPr()
    borders = properties.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        properties.append(borders)
    border = borders.find(qn(f"w:{edge}"))
    if border is None:
        border = OxmlElement(f"w:{edge}")
        borders.append(border)
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), str(size))
    border.set(qn("w:space"), "4")
    border.set(qn("w:color"), color)


def _set_style_shading(style: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = style._element.get_or_add_pPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), color)
    shading.set(qn("w:val"), "clear")


def apply_word_theme(document: Any, theme: dict[str, Any]) -> None:
    """Apply typography, spacing and hierarchy to built-in Word styles."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    styles = document.styles
    normal = styles["Normal"]
    _set_style_font(
        normal,
        name=theme["body_font"],
        size_pt=theme["body_size_pt"],
        color=theme["text_color"],
    )
    normal.paragraph_format.line_spacing = theme["line_spacing"]
    normal.paragraph_format.space_after = Pt(theme["paragraph_space_after_pt"])

    title = styles["Title"]
    _set_style_font(
        title,
        name=theme["heading_font"],
        size_pt=theme["title_size_pt"],
        color=theme["primary_color"],
        bold=True,
    )
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.paragraph_format.space_before = Pt(8)
    title.paragraph_format.space_after = Pt(10)
    title.paragraph_format.keep_with_next = True

    subtitle = styles["Subtitle"]
    _set_style_font(
        subtitle,
        name=theme["body_font"],
        size_pt=theme["subtitle_size_pt"],
        color=theme["muted_color"],
    )
    subtitle.font.italic = False
    subtitle.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    subtitle.paragraph_format.space_after = Pt(20)
    subtitle.paragraph_format.keep_with_next = True

    heading_sizes = {
        1: theme["heading_1_size_pt"],
        2: theme["heading_2_size_pt"],
        3: theme["heading_3_size_pt"],
    }
    for level in range(1, 10):
        style = styles[f"Heading {level}"]
        size = heading_sizes.get(level, max(theme["body_size_pt"], 10.0))
        color = theme["primary_color"] if level == 1 else theme["accent_color"]
        _set_style_font(
            style,
            name=theme["heading_font"],
            size_pt=size,
            color=color,
            bold=True,
        )
        style.paragraph_format.space_before = Pt(16 if level == 1 else 11)
        style.paragraph_format.space_after = Pt(6 if level <= 2 else 4)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.keep_together = True
        if level == 1:
            _set_style_border(
                style,
                edge="bottom",
                color=theme["accent_color"],
                size=8,
            )

    for style_name in ("List Bullet", "List Number"):
        style = styles[style_name]
        _set_style_font(
            style,
            name=theme["body_font"],
            size_pt=theme["body_size_pt"],
            color=theme["text_color"],
        )
        style.paragraph_format.left_indent = Cm(0.75)
        style.paragraph_format.first_line_indent = Cm(-0.35)
        style.paragraph_format.space_after = Pt(3)

    quote = styles["Quote"]
    _set_style_font(
        quote,
        name=theme["body_font"],
        size_pt=theme["body_size_pt"],
        color=theme["muted_color"],
    )
    quote.paragraph_format.left_indent = Cm(0.6)
    quote.paragraph_format.right_indent = Cm(0.3)
    quote.paragraph_format.space_before = Pt(6)
    quote.paragraph_format.space_after = Pt(8)
    _set_style_border(
        quote,
        edge="left",
        color=theme["accent_color"],
        size=18,
    )
    _set_style_shading(quote, theme["surface_color"])

    caption = styles["Caption"]
    _set_style_font(
        caption,
        name=theme["body_font"],
        size_pt=max(8.0, theme["body_size_pt"] - 1.5),
        color=theme["muted_color"],
    )


def _set_cell_shading(cell: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), color)
    shading.set(qn("w:val"), "clear")


def _set_table_borders(table: Any, color: str = "D5DCE4") -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table._tbl.tblPr
    borders = properties.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        properties.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), color)


def _set_table_cell_margins(table: Any, twips: int = 90) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table._tbl.tblPr
    margins = properties.find(qn("w:tblCellMar"))
    if margins is None:
        margins = OxmlElement("w:tblCellMar")
        properties.append(margins)
    for edge in ("top", "left", "bottom", "right"):
        element = margins.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            margins.append(element)
        element.set(qn("w:w"), str(twips))
        element.set(qn("w:type"), "dxa")


def _repeat_table_header(row: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = row._tr.get_or_add_trPr()
    header = properties.find(qn("w:tblHeader"))
    if header is None:
        header = OxmlElement("w:tblHeader")
        properties.append(header)
    header.set(qn("w:val"), "true")


def style_word_table(
    table: Any,
    theme: dict[str, Any],
    *,
    has_header: bool,
    column_widths_cm: Any = None,
) -> None:
    """Create a readable enterprise table with header and zebra hierarchy."""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.shared import Cm, Pt, RGBColor

    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(table)
    _set_table_cell_margins(table)

    widths: list[float] | None = None
    if column_widths_cm is not None:
        if not isinstance(column_widths_cm, list) or len(column_widths_cm) != len(table.columns):
            raise ValueError("table.column_widths_cm 必须与表格列数一致")
        widths = [float(value) for value in column_widths_cm]
        if any(value <= 0 or value > 50 for value in widths):
            raise ValueError("table.column_widths_cm 每列必须大于 0 且不超过 50")
        table.autofit = False

    for row_index, row in enumerate(table.rows):
        is_header = has_header and row_index == 0
        if is_header:
            _repeat_table_header(row)
        for column_index, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if widths:
                cell.width = Cm(widths[column_index])
            if is_header:
                _set_cell_shading(cell, theme["primary_color"])
            elif row_index % 2 == (0 if has_header else 1):
                _set_cell_shading(cell, theme["alternate_row_color"])
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.2
                for run in paragraph.runs:
                    _set_run_font(run, theme["body_font"])
                    run.font.size = Pt(theme["body_size_pt"])
                    run.font.bold = is_header
                    run.font.color.rgb = RGBColor.from_string(
                        "FFFFFF" if is_header else theme["text_color"]
                    )


def style_table_cells(table: Any, values: dict[str, Any]) -> int:
    """Apply a bounded visual patch to existing table cells."""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    def selected_indexes(raw: Any, count: int, field: str) -> list[int]:
        if raw in (None, "all"):
            return list(range(count))
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"style_table_cells.{field} 必须是非空的 1-based 整数数组或 all")
        indexes: list[int] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > count:
                raise ValueError(
                    f"style_table_cells.{field} 超出范围；当前表格共有 {count} 个"
                )
            index = value - 1
            if index not in indexes:
                indexes.append(index)
        return indexes

    style_fields = {
        "fill_color", "text_color", "bold", "font_size_pt",
        "horizontal_alignment", "vertical_alignment",
    }
    if not any(field in values for field in style_fields):
        raise ValueError("style_table_cells 至少需要一个样式字段")

    fill_color = values.get("fill_color")
    text_color = values.get("text_color")
    for field, color in (("fill_color", fill_color), ("text_color", text_color)):
        if color is not None and not _HEX_COLOR.fullmatch(str(color)):
            raise ValueError(f"style_table_cells.{field} 必须是 6 位十六进制颜色")
    bold = values.get("bold")
    if bold is not None and not isinstance(bold, bool):
        raise ValueError("style_table_cells.bold 必须是布尔值")
    font_size = values.get("font_size_pt")
    if font_size is not None:
        font_size = float(font_size)
        if font_size < 6 or font_size > 72:
            raise ValueError("style_table_cells.font_size_pt 必须在 6 到 72 之间")

    horizontal = values.get("horizontal_alignment")
    horizontal_values = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }
    if horizontal is not None and horizontal not in horizontal_values:
        raise ValueError("style_table_cells.horizontal_alignment 仅支持 left、center 或 right")
    vertical = values.get("vertical_alignment")
    vertical_values = {
        "top": WD_CELL_VERTICAL_ALIGNMENT.TOP,
        "center": WD_CELL_VERTICAL_ALIGNMENT.CENTER,
        "bottom": WD_CELL_VERTICAL_ALIGNMENT.BOTTOM,
    }
    if vertical is not None and vertical not in vertical_values:
        raise ValueError("style_table_cells.vertical_alignment 仅支持 top、center 或 bottom")

    row_indexes = selected_indexes(values.get("rows"), len(table.rows), "rows")
    column_indexes = selected_indexes(values.get("columns"), len(table.columns), "columns")
    styled_cells = 0
    seen_cells: set[int] = set()
    for row_index in row_indexes:
        row = table.rows[row_index]
        for column_index in column_indexes:
            cell = row.cells[column_index]
            cell_key = id(cell._tc)
            if cell_key in seen_cells:
                continue
            seen_cells.add(cell_key)
            styled_cells += 1
            if fill_color is not None:
                _set_cell_shading(cell, str(fill_color).upper())
            if vertical is not None:
                cell.vertical_alignment = vertical_values[str(vertical)]
            for paragraph in cell.paragraphs:
                if horizontal is not None:
                    paragraph.alignment = horizontal_values[str(horizontal)]
                for run in paragraph.runs:
                    if text_color is not None:
                        run.font.color.rgb = RGBColor.from_string(str(text_color).upper())
                    if bold is not None:
                        run.font.bold = bold
                    if font_size is not None:
                        run.font.size = Pt(font_size)
    return styled_cells


def style_header_footer(paragraph: Any, theme: dict[str, Any], *, footer: bool) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    paragraph.alignment = (
        WD_ALIGN_PARAGRAPH.CENTER if footer else WD_ALIGN_PARAGRAPH.RIGHT
    )
    paragraph.paragraph_format.space_after = Pt(0)
    for run in paragraph.runs:
        _set_run_font(run, theme["body_font"])
        run.font.size = Pt(max(8.0, theme["body_size_pt"] - 2))
        run.font.color.rgb = RGBColor.from_string(theme["muted_color"])
