"""Build and persist a browser-previewable presentation project.

The project deliberately follows PPTD's useful idea -- a small manifest plus
self-contained page descriptions -- without depending on Kimi's bundled web
editor.  JSON is valid YAML, so the generated ``.pptd`` and ``.page`` files
remain easy for agents and implementation staff to inspect and revise.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Iterable


PROJECT_SCHEMA = "xiaomei.presentation.v1"
PROJECT_GENERATOR_VERSION = 4
CANVAS_WIDTH = 960.0


def presentation_project_directory(output_path: Path) -> Path:
    """Return the private companion-project directory for one PPTX output."""
    return output_path.parent / ".presentation" / output_path.stem


def build_presentation_project(pptx_path: Path, project_dir: Path) -> dict[str, Any]:
    """Convert a PPTX into a deterministic PPTD-style preview project."""
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover - writer already requires it
        raise ValueError("演示文稿预览依赖 python-pptx 未安装") from exc

    pptx_path = pptx_path.resolve(strict=True)
    project_dir = project_dir.resolve()
    if project_dir.parent.name != ".presentation":
        raise ValueError("演示文稿项目必须位于受控的 .presentation 目录")
    if project_dir.exists():
        shutil.rmtree(project_dir)
    pages_dir = project_dir / "pages"
    media_dir = project_dir / "media"
    pages_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    presentation = Presentation(str(pptx_path))
    slide_width = max(1, int(presentation.slide_width))
    slide_height = max(1, int(presentation.slide_height))
    canvas_width = CANVAS_WIDTH
    canvas_height = round(canvas_width * slide_height / slide_width, 3)
    scale_x = canvas_width / slide_width
    scale_y = canvas_height / slide_height
    title = str(presentation.core_properties.title or pptx_path.stem).strip() or pptx_path.stem
    source_revision = _source_revision(pptx_path)

    manifest_pages: list[str] = []
    preview_slides: list[dict[str, Any]] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        page_path = f"pages/{slide_index:03d}.page"
        manifest_pages.append(page_path)
        elements: list[dict[str, Any]] = []
        image_counter = [0]
        for shape in slide.shapes:
            elements.extend(_shape_elements(
                shape,
                slide_index=slide_index,
                shape_id_path=(int(shape.shape_id),),
                scale_x=scale_x,
                scale_y=scale_y,
                media_dir=media_dir,
                image_counter=image_counter,
            ))
        page = {
            "pageType": "content",
            "background": {"color": _slide_background(slide)},
            "elements": elements,
        }
        _write_json(project_dir / page_path, page)
        preview_slides.append({
            "path": page_path,
            "index": slide_index,
            **page,
        })

    manifest_name = f"{pptx_path.stem}.pptd"
    manifest = {
        "version": "v2",
        "schema": PROJECT_SCHEMA,
        "title": title,
        "size": [canvas_width, canvas_height],
        "pages": manifest_pages,
        "sourceRevision": source_revision,
    }
    _write_json(project_dir / manifest_name, manifest)
    project = {
        "schema": PROJECT_SCHEMA,
        "generatorVersion": PROJECT_GENERATOR_VERSION,
        "title": title,
        "size": [canvas_width, canvas_height],
        "manifest": manifest_name,
        "sourceRevision": source_revision,
        "slides": preview_slides,
    }
    _write_json(project_dir / "project.json", project)
    return {
        "path": str(project_dir),
        "manifest": manifest_name,
        "slide_count": len(preview_slides),
        "schema": PROJECT_SCHEMA,
        "source_revision": source_revision,
    }


def _source_revision(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_presentation_project(project_dir: Path) -> dict[str, Any]:
    value = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    if value.get("schema") != PROJECT_SCHEMA or not isinstance(value.get("slides"), list):
        raise ValueError("演示文稿项目格式无效")
    media: dict[str, dict[str, str]] = {}
    for path in sorted((project_dir / "media").glob("*")):
        if not path.is_file():
            continue
        import base64
        relative = path.relative_to(project_dir).as_posix()
        media[relative] = {
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    value["media"] = media
    return value


def _shape_elements(
    shape: Any,
    *,
    slide_index: int,
    shape_id_path: tuple[int, ...],
    scale_x: float,
    scale_y: float,
    media_dir: Path,
    image_counter: list[int],
) -> list[dict[str, Any]]:
    try:
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:  # pragma: no cover
        return []

    shape_type = shape.shape_type
    if shape_type == MSO_SHAPE_TYPE.GROUP:
        nested: list[dict[str, Any]] = []
        for child in shape.shapes:
            nested.extend(_shape_elements(
                child,
                slide_index=slide_index,
                shape_id_path=(*shape_id_path, int(child.shape_id)),
                scale_x=scale_x,
                scale_y=scale_y,
                media_dir=media_dir,
                image_counter=image_counter,
            ))
        return nested

    bounds = [
        round(float(shape.left) * scale_x, 3),
        round(float(shape.top) * scale_y, 3),
        round(float(shape.width) * scale_x, 3),
        round(float(shape.height) * scale_y, 3),
    ]
    element_id = (
        f"slide-{slide_index}-shape-id-"
        + ".".join(str(shape_id) for shape_id in shape_id_path)
    )

    if shape_type == MSO_SHAPE_TYPE.PICTURE:
        try:
            image_counter[0] += 1
            extension = str(shape.image.ext or "png").lower()
            filename = f"slide-{slide_index:03d}-{image_counter[0]:03d}.{extension}"
            (media_dir / filename).write_bytes(shape.image.blob)
            return [{
                "elementId": element_id,
                "elementType": "image",
                "bounds": bounds,
                "rotation": _shape_rotation(shape),
                "src": f"media/{filename}",
                "fit": {"mode": "cover"},
            }]
        except Exception:
            return []

    if getattr(shape, "has_chart", False):
        return _chart_elements(shape, element_id, bounds)

    if getattr(shape, "has_table", False):
        return _table_elements(shape, element_id, bounds)

    text = ""
    if getattr(shape, "has_text_frame", False):
        text = str(shape.text or "").strip()
    style = _text_style(shape)
    rich_text = _rich_text(shape.text_frame) if getattr(shape, "has_text_frame", False) else None
    if shape_type in {MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.FREEFORM}:
        fill = _shape_fill(shape)
        line = _shape_line(shape)
        return [{
            "elementId": element_id,
            "elementType": "shape",
            "bounds": bounds,
            "rotation": _shape_rotation(shape),
            "shapeName": _shape_name(shape),
            "fill": fill,
            "line": line,
            "text": text,
            "textStyle": style,
            "richText": rich_text,
        }]
    if text:
        return [{
            "elementId": element_id,
            "elementType": "text",
            "bounds": bounds,
            "rotation": _shape_rotation(shape),
            "content": {"text": text, **style},
            "richText": rich_text,
        }]
    return []


def _table_elements(shape: Any, element_id: str, bounds: list[float]) -> list[dict[str, Any]]:
    table = shape.table
    rows = len(table.rows)
    columns = len(table.columns)
    if rows <= 0 or columns <= 0:
        return []
    x, y, width, height = bounds
    cell_width = width / columns
    cell_height = height / rows
    values = []
    for row_index, row in enumerate(table.rows):
        for column_index, cell in enumerate(row.cells):
            values.append({
                "row": row_index,
                "column": column_index,
                "text": str(cell.text or ""),
                "fill": _fill_format(cell.fill),
                "textStyle": _text_frame_style(cell.text_frame),
                "columnSpan": int(getattr(cell, "span_width", 1) or 1),
                "rowSpan": int(getattr(cell, "span_height", 1) or 1),
                "hidden": bool(getattr(cell, "is_spanned", False)),
            })
    return [{
        "elementId": element_id,
        "elementType": "table",
        "bounds": bounds,
        "rows": rows,
        "columns": columns,
        "cellWidth": cell_width,
        "cellHeight": cell_height,
        "cells": values,
    }]


def _chart_elements(shape: Any, element_id: str, bounds: list[float]) -> list[dict[str, Any]]:
    chart = shape.chart
    title = ""
    try:
        if chart.has_title:
            title = str(chart.chart_title.text_frame.text or "").strip()
    except Exception:
        pass
    categories: list[str] = []
    try:
        categories = [
            " / ".join(str(part) for part in label if part is not None)
            for label in chart.plots[0].categories.flattened_labels
        ]
    except Exception:
        pass
    series_items: list[dict[str, Any]] = []
    for index, series in enumerate(chart.series):
        try:
            values = [_chart_value(value) for value in series.values]
        except Exception:
            values = []
        series_items.append({
            "name": str(series.name or f"Series {index + 1}"),
            "values": values,
            "color": _chart_series_color(series, index),
        })
    chart_type = str(chart.chart_type or "chart").split("(", 1)[0].strip().lower()
    return [{
        "elementId": element_id,
        "elementType": "chart",
        "bounds": bounds,
        "chartType": chart_type,
        "title": title,
        "titleStyle": _chart_title_style(chart),
        "fill": _chart_fill(chart),
        "categories": categories,
        "series": series_items,
        "hasLegend": bool(chart.has_legend),
    }]


def _chart_fill(chart: Any) -> dict[str, Any]:
    """Return the chart-area fill from ``c:chartSpace/c:spPr``."""
    try:
        from pptx.oxml.ns import qn

        properties = chart._chartSpace.find(qn("c:spPr"))
        if properties is None or properties.find(qn("a:noFill")) is not None:
            return {"type": "none", "color": "transparent"}
        solid = properties.find(qn("a:solidFill"))
        if solid is not None:
            color = solid.find(qn("a:srgbClr"))
            if color is not None and color.get("val"):
                return {"type": "solid", "color": f"#{color.get('val')}"}
    except Exception:
        pass
    return {"type": "unknown", "color": "transparent"}


def _chart_title_style(chart: Any) -> dict[str, Any]:
    try:
        if chart.has_title:
            return _text_frame_style(chart.chart_title.text_frame)
    except Exception:
        pass
    return {"fontSize": 18, "color": "#253047", "bold": False, "align": "center"}


def _chart_value(value: Any) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _chart_series_color(series: Any, index: int) -> str:
    palette = ("#4F6BED", "#16A085", "#F39C12", "#E15B64", "#7A5AF8", "#3498DB")
    for format_object in (getattr(series, "format", None),):
        try:
            rgb = format_object.fill.fore_color.rgb
            if rgb is not None:
                return f"#{rgb}"
        except Exception:
            pass
        try:
            rgb = format_object.line.color.rgb
            if rgb is not None:
                return f"#{rgb}"
        except Exception:
            pass
    return palette[index % len(palette)]


def _text_style(shape: Any) -> dict[str, Any]:
    try:
        return _text_frame_style(shape.text_frame)
    except Exception:
        return {"fontSize": 18, "color": "#253047", "bold": False, "align": "left"}


def _text_frame_style(text_frame: Any) -> dict[str, Any]:
    style: dict[str, Any] = {
        "fontSize": 18,
        "color": "#253047",
        "bold": False,
        "align": "left",
        "verticalAlign": _vertical_alignment(text_frame),
        "margins": _text_frame_margins(text_frame),
    }
    try:
        paragraphs: Iterable[Any] = text_frame.paragraphs
        paragraph = next(iter(paragraphs), None)
        if paragraph is None:
            return style
        alignment = str(paragraph.alignment or "").lower()
        if "center" in alignment:
            style["align"] = "center"
        elif "right" in alignment:
            style["align"] = "right"
        run = next(iter(paragraph.runs), None)
        font = run.font if run is not None else paragraph.font
        if font.size is not None:
            style["fontSize"] = round(float(font.size.pt), 2)
        family = _font_family(font)
        if family:
            style["fontFamily"] = family
        if font.bold is not None:
            style["bold"] = bool(font.bold)
        color = _font_color(font)
        if color:
            style["color"] = color
    except Exception:
        pass
    return style


def _rich_text(text_frame: Any) -> dict[str, Any]:
    """Preserve paragraph and run formatting instead of flattening a text box."""
    paragraphs: list[dict[str, Any]] = []
    try:
        for paragraph in text_frame.paragraphs:
            paragraph_item: dict[str, Any] = {
                "align": _paragraph_alignment(paragraph),
                "level": int(paragraph.level or 0),
                "bullet": _paragraph_has_bullet(paragraph),
                "runs": [],
            }
            for field, value in (
                ("spaceBefore", _length_points(paragraph.space_before)),
                ("spaceAfter", _length_points(paragraph.space_after)),
            ):
                if value is not None:
                    paragraph_item[field] = value
            line_height = _paragraph_line_height(paragraph)
            if line_height is not None:
                paragraph_item["lineHeight"] = line_height

            runs: list[dict[str, Any]] = []
            for run in paragraph.runs:
                if not run.text:
                    continue
                item: dict[str, Any] = {"text": str(run.text)}
                font = run.font
                if font.size is not None:
                    item["fontSize"] = round(float(font.size.pt), 2)
                family = _font_family(font)
                if family:
                    item["fontFamily"] = family
                if font.bold is not None:
                    item["bold"] = bool(font.bold)
                if font.italic is not None:
                    item["italic"] = bool(font.italic)
                color = _font_color(font)
                if color:
                    item["color"] = color
                runs.append(item)
            if not runs and paragraph.text:
                runs.append({"text": str(paragraph.text)})
            paragraph_item["runs"] = runs
            paragraphs.append(paragraph_item)
    except Exception:
        return {"paragraphs": []}
    return {"paragraphs": paragraphs}


def _paragraph_alignment(paragraph: Any) -> str:
    alignment = str(getattr(paragraph, "alignment", "") or "").lower()
    if "center" in alignment:
        return "center"
    if "right" in alignment:
        return "right"
    if "justify" in alignment or "distributed" in alignment:
        return "justify"
    return "left"


def _vertical_alignment(text_frame: Any) -> str:
    anchor = str(getattr(text_frame, "vertical_anchor", "") or "").lower()
    if "middle" in anchor:
        return "middle"
    if "bottom" in anchor:
        return "bottom"
    return "top"


def _text_frame_margins(text_frame: Any) -> list[float]:
    values = []
    for name in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
        value = _length_points(getattr(text_frame, name, None))
        values.append(value if value is not None else 0.0)
    return values


def _length_points(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value.pt), 2)
    except Exception:
        return None


def _paragraph_line_height(paragraph: Any) -> dict[str, float] | None:
    try:
        value = paragraph.line_spacing
        if value is None:
            return None
        if hasattr(value, "pt"):
            return {"points": round(float(value.pt), 2)}
        return {"multiple": round(float(value), 3)}
    except Exception:
        return None


def _paragraph_has_bullet(paragraph: Any) -> bool:
    try:
        properties = paragraph._p.pPr
        if properties is None:
            return False
        return any(
            child.tag.rsplit("}", 1)[-1] in {"buChar", "buAutoNum", "buBlip"}
            for child in properties
        )
    except Exception:
        return False


def _font_family(font: Any) -> str:
    try:
        properties = font._rPr
        if properties is not None:
            for tag in ("ea", "latin", "cs"):
                node = properties.find(f"{{http://schemas.openxmlformats.org/drawingml/2006/main}}{tag}")
                if node is not None and node.get("typeface"):
                    return str(node.get("typeface"))
    except Exception:
        pass
    try:
        return str(font.name) if font.name else ""
    except Exception:
        return ""


def _shape_rotation(shape: Any) -> float:
    try:
        return round(float(shape.rotation or 0), 3)
    except Exception:
        return 0.0


def _font_color(font: Any) -> str:
    try:
        rgb = font.color.rgb
        return f"#{rgb}" if rgb is not None else ""
    except Exception:
        return ""


def _shape_fill(shape: Any) -> dict[str, Any]:
    """Return the real fill without inventing a white background."""
    return _fill_format(shape.fill)


def _fill_format(fill: Any) -> dict[str, Any]:
    try:
        fill_type = fill.type
        if fill_type is None or "background" in str(fill_type).lower():
            return {"type": "none", "color": "transparent"}
        rgb = fill.fore_color.rgb
        if rgb is not None:
            return {"type": "solid", "color": f"#{rgb}"}
    except Exception:
        pass
    return {"type": "unknown", "color": "transparent"}


def _shape_line(shape: Any) -> dict[str, Any]:
    """Return only an explicitly visible line; never synthesize a border."""
    try:
        fill_type = shape.line.fill.type
        if fill_type is None or "background" in str(fill_type).lower():
            return {"type": "none", "color": "transparent", "width": 0}
        rgb = shape.line.color.rgb
        if rgb is not None:
            line_width = shape.line.width
            width = (
                max(0.0, round(float(line_width.pt), 2))
                if line_width is not None
                else 1.0
            )
            return {"type": "solid", "color": f"#{rgb}", "width": width}
    except Exception:
        pass
    return {"type": "unknown", "color": "transparent", "width": 0}


def _slide_background(slide: Any) -> str:
    try:
        rgb = slide.background.fill.fore_color.rgb
        return f"#{rgb}" if rgb is not None else "#FFFFFF"
    except Exception:
        return "#FFFFFF"


def _shape_name(shape: Any) -> str:
    try:
        name = str(shape.auto_shape_type or "").lower()
    except Exception:
        return "rect"
    if "ellipse" in name or "oval" in name:
        return "ellipse"
    if "round" in name:
        return "roundRect"
    return "rect"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
