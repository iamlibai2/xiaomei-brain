"""Deterministic presentation quality checks for Agent-authored PPTX files.

The validator consumes the companion presentation project because that is the
same normalized element model used by Desktop preview and precise revisions.
Checks deliberately remain conservative: structural defects block delivery,
while visual heuristics are reported as warnings for the Agent to review.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


MIN_FONT_SIZE_PT = 9.0
MIN_CONTRAST_RATIO = 3.0
BOUNDS_TOLERANCE = 1.0
OVERLAP_RATIO = 0.35
MAX_CONTENT_ELEMENTS = 18
MAX_TEXT_CHARACTERS = 800


def validate_presentation_project(project_dir: Path) -> dict[str, Any]:
    """Return a structured, stable validation report for one PPT project."""
    project_path = project_dir / "project.json"
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _report([_issue(
            page=0,
            element_id="presentation",
            severity="error",
            code="project_unavailable",
            reason=f"无法读取演示文稿验收数据：{exc}",
            suggestion="重新生成演示文稿后再次验收。",
        )])

    size = project.get("size")
    slides = project.get("slides")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or not all(_positive_number(value) for value in size)
        or not isinstance(slides, list)
    ):
        return _report([_issue(
            page=0,
            element_id="presentation",
            severity="error",
            code="project_invalid",
            reason="演示文稿验收数据缺少有效的页面尺寸或页面列表。",
            suggestion="重新生成演示文稿后再次验收。",
        )])

    width, height = float(size[0]), float(size[1])
    issues: list[dict[str, Any]] = []
    for fallback_page, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        page = _integer(slide.get("index"), fallback_page)
        elements = [
            element
            for element in slide.get("elements", [])
            if isinstance(element, dict)
        ]
        background = _solid_color(slide.get("background"))
        issues.extend(_check_bounds(page, elements, width, height))
        issues.extend(_check_empty_data(page, elements))
        issues.extend(_check_text(page, elements, background))
        issues.extend(_check_overlaps(page, elements))
        issues.extend(_check_density(page, elements))
    return _report(_deduplicate(issues))


def _check_bounds(
    page: int,
    elements: list[dict[str, Any]],
    slide_width: float,
    slide_height: float,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for element in elements:
        bounds = _bounds(element)
        if bounds is None:
            continue
        x, y, width, height = bounds
        left, right = sorted((x, x + width))
        top, bottom = sorted((y, y + height))
        overflow = {
            "left": max(0.0, -left),
            "top": max(0.0, -top),
            "right": max(0.0, right - slide_width),
            "bottom": max(0.0, bottom - slide_height),
        }
        overflow = {
            side: round(value, 1)
            for side, value in overflow.items()
            if value > BOUNDS_TOLERANCE
        }
        if not overflow:
            continue
        detail = "、".join(f"{_side_label(side)} {value}px" for side, value in overflow.items())
        issues.append(_issue(
            page=page,
            element_id=_element_id(element, page),
            severity="error",
            code="out_of_bounds",
            reason=f"元素超出页面范围：{detail}。",
            suggestion="调整元素位置或尺寸，使其完整位于页面范围内。",
        ))
    return issues


def _check_empty_data(page: int, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for element in elements:
        element_type = str(element.get("elementType") or "")
        element_id = _element_id(element, page)
        if element_type == "table":
            cells = [cell for cell in element.get("cells", []) if isinstance(cell, dict)]
            rows = _integer(element.get("rows"), 0)
            columns = _integer(element.get("columns"), 0)
            visible = [cell for cell in cells if not cell.get("hidden")]
            nonempty = [cell for cell in visible if str(cell.get("text") or "").strip()]
            if rows <= 0 or columns <= 0 or not visible or not nonempty:
                issues.append(_issue(
                    page=page,
                    element_id=element_id,
                    severity="error",
                    code="empty_table",
                    reason="表格没有可展示的数据。",
                    suggestion="补充表头和数据行，或删除这个空表格。",
                ))
            elif len(visible) < rows * columns:
                issues.append(_issue(
                    page=page,
                    element_id=element_id,
                    severity="error",
                    code="table_data_length_mismatch",
                    reason=f"表格声明为 {rows}×{columns}，但只有 {len(visible)} 个有效单元格。",
                    suggestion="补齐单元格数据，确保行列数量一致。",
                ))
        elif element_type == "chart":
            categories = element.get("categories")
            series = [item for item in element.get("series", []) if isinstance(item, dict)]
            chart_type = str(element.get("chartType") or "").strip().lower()
            is_scatter = "scatter" in chart_type or chart_type.startswith("xy")
            if not series or (
                not is_scatter
                and (not isinstance(categories, list) or not categories)
            ):
                issues.append(_issue(
                    page=page,
                    element_id=element_id,
                    severity="error",
                    code="empty_chart",
                    reason="图表缺少分类或数据系列。",
                    suggestion="补充图表分类与至少一个非空数据系列，或删除这个空图表。",
                ))
                continue
            for series_index, item in enumerate(series, start=1):
                values = item.get("values")
                x_values = item.get("xValues")
                if not isinstance(values, list) or not values:
                    issues.append(_issue(
                        page=page,
                        element_id=element_id,
                        severity="error",
                        code="empty_chart_series",
                        reason=f"图表第 {series_index} 个数据系列为空。",
                        suggestion="补充该系列的数据，或删除空系列。",
                    ))
                elif is_scatter and (
                    not isinstance(x_values, list)
                    or not x_values
                    or len(values) != len(x_values)
                ):
                    issues.append(_issue(
                        page=page,
                        element_id=element_id,
                        severity="error",
                        code="chart_data_length_mismatch",
                        reason=(
                            f"散点图第 {series_index} 个系列有 {len(values)} 个 Y 值，"
                            f"但有 {len(x_values) if isinstance(x_values, list) else 0} 个 X 值。"
                        ),
                        suggestion="让散点图每个系列的 x_values 与 values 非空且数量完全一致。",
                    ))
                elif not is_scatter and len(values) != len(categories):
                    issues.append(_issue(
                        page=page,
                        element_id=element_id,
                        severity="error",
                        code="chart_data_length_mismatch",
                        reason=(
                            f"图表第 {series_index} 个系列有 {len(values)} 个值，"
                            f"但分类有 {len(categories)} 项。"
                        ),
                        suggestion="让每个数据系列的值数量与分类数量完全一致。",
                    ))
    return issues


def _check_text(
    page: int,
    elements: list[dict[str, Any]],
    slide_background: str | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for element in elements:
        element_id = _element_id(element, page)
        element_type = str(element.get("elementType") or "")
        if element_type == "table":
            for cell in element.get("cells", []):
                if not isinstance(cell, dict) or not str(cell.get("text") or "").strip():
                    continue
                style = cell.get("textStyle") if isinstance(cell.get("textStyle"), dict) else {}
                font_size = _number(style.get("fontSize"), 18.0)
                issues.extend(_small_font_issue(page, element_id, font_size, "表格单元格"))
                foreground = _color(style.get("color"))
                background = _solid_color(cell.get("fill")) or slide_background
                issues.extend(_contrast_issue(page, element_id, foreground, background, "表格文字"))
            continue

        text, style = _element_text_and_style(element)
        if not text:
            continue
        font_sizes = _font_sizes(element, style)
        minimum_size = min(font_sizes) if font_sizes else _number(style.get("fontSize"), 18.0)
        issues.extend(_small_font_issue(page, element_id, minimum_size, "文字"))

        bounds = _bounds(element)
        if bounds is not None and _likely_text_overflow(text, bounds, minimum_size, style):
            issues.append(_issue(
                page=page,
                element_id=element_id,
                severity="warning",
                code="possible_text_overflow",
                reason="按文本框尺寸、字号和文字量估算，文字可能无法完整显示。",
                suggestion="增大文本框、缩短文字，或适度减小字号并重新验收。",
            ))

        foreground = _color(style.get("color"))
        background = _solid_color(element.get("fill")) or slide_background
        issues.extend(_contrast_issue(page, element_id, foreground, background, "文字"))
    return issues


def _check_overlaps(page: int, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    candidates = [
        element
        for element in elements
        if str(element.get("elementType") or "") in {"text", "table", "chart", "formula", "media"}
        and _bounds(element) is not None
    ]
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            first_bounds = _bounds(first)
            second_bounds = _bounds(second)
            if first_bounds is None or second_bounds is None:
                continue
            ratio = _overlap_ratio(first_bounds, second_bounds)
            if ratio < OVERLAP_RATIO:
                continue
            first_id = _element_id(first, page)
            second_id = _element_id(second, page)
            issues.append(_issue(
                page=page,
                element_id=second_id,
                severity="warning",
                code="possible_unintended_overlap",
                reason=f"该元素与 {first_id} 的重叠面积约占较小元素的 {ratio:.0%}。",
                suggestion="确认是否为刻意叠放；否则调整两个元素的位置或尺寸。",
            ))
    return issues


def _check_density(page: int, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content_elements = [
        element
        for element in elements
        if str(element.get("elementType") or "") not in {"line"}
    ]
    character_count = sum(len(_element_text_and_style(element)[0]) for element in elements)
    if len(content_elements) <= MAX_CONTENT_ELEMENTS and character_count <= MAX_TEXT_CHARACTERS:
        return []
    reasons = []
    if len(content_elements) > MAX_CONTENT_ELEMENTS:
        reasons.append(f"包含 {len(content_elements)} 个内容元素")
    if character_count > MAX_TEXT_CHARACTERS:
        reasons.append(f"包含约 {character_count} 个文字字符")
    return [_issue(
        page=page,
        element_id=f"slide-{page}",
        severity="warning",
        code="dense_slide",
        reason="页面内容可能过密：" + "，".join(reasons) + "。",
        suggestion="拆分页面、减少次要信息，或强化信息层级与留白。",
    )]


def _element_text_and_style(element: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    element_type = str(element.get("elementType") or "")
    if element_type == "text":
        content = element.get("content") if isinstance(element.get("content"), dict) else {}
        return str(content.get("text") or "").strip(), content
    if element_type == "shape":
        style = element.get("textStyle") if isinstance(element.get("textStyle"), dict) else {}
        return str(element.get("text") or "").strip(), style
    if element_type == "chart":
        style = element.get("titleStyle") if isinstance(element.get("titleStyle"), dict) else {}
        return str(element.get("title") or "").strip(), style
    if element_type == "formula":
        return str(element.get("fallbackText") or "").strip(), {"fontSize": 18}
    return "", {}


def _font_sizes(element: dict[str, Any], fallback: dict[str, Any]) -> list[float]:
    sizes: list[float] = []
    rich_text = element.get("richText")
    if isinstance(rich_text, dict):
        for paragraph in rich_text.get("paragraphs", []):
            if not isinstance(paragraph, dict):
                continue
            for run in paragraph.get("runs", []):
                if isinstance(run, dict) and _positive_number(run.get("fontSize")):
                    sizes.append(float(run["fontSize"]))
    if not sizes and _positive_number(fallback.get("fontSize")):
        sizes.append(float(fallback["fontSize"]))
    return sizes


def _small_font_issue(
    page: int,
    element_id: str,
    font_size: float,
    label: str,
) -> list[dict[str, Any]]:
    if font_size >= MIN_FONT_SIZE_PT:
        return []
    return [_issue(
        page=page,
        element_id=element_id,
        severity="warning",
        code="font_too_small",
        reason=f"{label}最小字号约为 {font_size:g}pt，演示时可能难以阅读。",
        suggestion=f"将字号提高到至少 {MIN_FONT_SIZE_PT:g}pt，或减少页面内容。",
    )]


def _contrast_issue(
    page: int,
    element_id: str,
    foreground: str | None,
    background: str | None,
    label: str,
) -> list[dict[str, Any]]:
    if foreground is None or background is None:
        return []
    ratio = _contrast_ratio(foreground, background)
    if ratio >= MIN_CONTRAST_RATIO:
        return []
    return [_issue(
        page=page,
        element_id=element_id,
        severity="warning",
        code="low_contrast",
        reason=f"{label}与背景的估算对比度为 {ratio:.2f}:1，可能不易辨认。",
        suggestion="加深文字颜色、减淡背景，或改用更高对比度的配色。",
    )]


def _likely_text_overflow(
    text: str,
    bounds: tuple[float, float, float, float],
    font_size: float,
    style: dict[str, Any],
) -> bool:
    _, _, width, height = bounds
    margins = style.get("margins") if isinstance(style.get("margins"), dict) else {}
    usable_width = max(1.0, abs(width) - _number(margins.get("left"), 0.0) - _number(margins.get("right"), 0.0))
    usable_height = max(1.0, abs(height) - _number(margins.get("top"), 0.0) - _number(margins.get("bottom"), 0.0))
    line_height = max(1.0, font_size * 1.25)
    line_capacity = max(1, math.floor(usable_height / line_height))
    width_capacity = max(1.0, usable_width / max(1.0, font_size * 0.55))
    required_lines = 0
    for line in text.splitlines() or [text]:
        units = sum(1.0 if ord(character) > 127 else 0.55 for character in line)
        required_lines += max(1, math.ceil(units / width_capacity))
    return required_lines > line_capacity * 1.2


def _overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    a_left, a_right = sorted((ax, ax + aw))
    a_top, a_bottom = sorted((ay, ay + ah))
    b_left, b_right = sorted((bx, bx + bw))
    b_top, b_bottom = sorted((by, by + bh))
    overlap_width = max(0.0, min(a_right, b_right) - max(a_left, b_left))
    overlap_height = max(0.0, min(a_bottom, b_bottom) - max(a_top, b_top))
    overlap_area = overlap_width * overlap_height
    smaller_area = min(abs(aw * ah), abs(bw * bh))
    return overlap_area / smaller_area if smaller_area > 0 else 0.0


def _bounds(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = element.get("bounds")
    if not isinstance(values, list) or len(values) != 4:
        return None
    try:
        numbers = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    return numbers if all(math.isfinite(value) for value in numbers) else None


def _solid_color(fill: Any) -> str | None:
    if not isinstance(fill, dict) or str(fill.get("type") or "") != "solid":
        return None
    return _color(fill.get("color"))


def _color(value: Any) -> str | None:
    text = str(value or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        return None
    return f"#{text.upper()}"


def _contrast_ratio(first: str, second: str) -> float:
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _report(issues: list[dict[str, Any]]) -> dict[str, Any]:
    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "valid": error_count == 0,
        "delivery_ready": error_count == 0,
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }


def _issue(
    *,
    page: int,
    element_id: str,
    severity: str,
    code: str,
    reason: str,
    suggestion: str,
) -> dict[str, Any]:
    return {
        "page": page,
        "element_id": element_id,
        "severity": severity,
        "code": code,
        "reason": reason,
        "suggestion": suggestion,
    }


def _deduplicate(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result = []
    for issue in issues:
        key = (issue["page"], issue["element_id"], issue["code"], issue["reason"])
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _element_id(element: dict[str, Any], page: int) -> str:
    return str(element.get("elementId") or f"slide-{page}")


def _side_label(side: str) -> str:
    return {"left": "左侧", "top": "上侧", "right": "右侧", "bottom": "下侧"}[side]


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive_number(value: Any) -> bool:
    return _number(value, 0.0) > 0
