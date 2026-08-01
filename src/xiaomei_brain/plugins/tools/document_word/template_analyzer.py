"""Deterministic structure analysis for reusable DOCX templates."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from xiaomei_brain.documents.office_xml import read_xml


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.:-]+)\s*\}\}")


def _text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_W}t"))


def _location_placeholder(
    placeholders: dict[str, dict[str, Any]],
    raw_key: str,
    location: str,
) -> None:
    key = raw_key.strip()
    is_block = key.upper().startswith("BLOCK:")
    normalized = key.split(":", 1)[1] if is_block else key
    target = placeholders.setdefault(normalized, {
        "key": normalized,
        "label": normalized.replace("_", " "),
        "type": "blocks" if is_block else "text",
        "required": True,
        "locations": [],
    })
    if is_block:
        target["type"] = "blocks"
    if location not in target["locations"]:
        target["locations"].append(location)


class WordTemplateAnalyzer:
    """Read only the OOXML needed to describe safe template filling."""

    format_id = "word"
    suffixes = (".docx",)
    analyzer_version = "1.0.0"

    def analyze(self, path: Path) -> dict[str, Any]:
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                if "word/document.xml" not in names:
                    raise ValueError("DOCX 缺少 word/document.xml")
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise ValueError("第一版模板库不接受包含宏的 Word 文件")
                document = read_xml(archive, "word/document.xml")
                related_parts = [
                    name for name in names
                    if re.fullmatch(r"word/(header|footer)\d+\.xml", name)
                ]
                roots = [("body", document)] + [
                    (
                        "header" if "/header" in name else "footer",
                        read_xml(archive, name),
                    )
                    for name in sorted(related_parts)
                ]

                placeholders: dict[str, dict[str, Any]] = {}
                headings: list[dict[str, Any]] = []
                tables: list[dict[str, Any]] = []
                style_counts: Counter[str] = Counter()

                for location, root in roots:
                    parent_map = {
                        child: parent
                        for parent in root.iter()
                        for child in parent
                    }
                    for paragraph in root.iter(f"{_W}p"):
                        value = _text(paragraph).strip()
                        for raw_key in _PLACEHOLDER.findall(value):
                            paragraph_location = location
                            parent = parent_map.get(paragraph)
                            while parent is not None:
                                if parent.tag == f"{_W}tc":
                                    paragraph_location = "table"
                                    break
                                parent = parent_map.get(parent)
                            _location_placeholder(
                                placeholders,
                                raw_key,
                                paragraph_location,
                            )
                        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
                        style_id = style.get(f"{_W}val", "") if style is not None else ""
                        if style_id:
                            style_counts[style_id] += 1
                        if value and style_id.lower().startswith(("heading", "title")):
                            level_match = re.search(r"(\d+)$", style_id)
                            headings.append({
                                "level": int(level_match.group(1)) if level_match else 1,
                                "text": value[:300],
                                "style": style_id,
                            })

                body = document.find(f"{_W}body")
                if body is not None:
                    for index, table in enumerate(body.iter(f"{_W}tbl")):
                        rows = list(table.findall(f"{_W}tr"))
                        columns = max(
                            (len(row.findall(f"{_W}tc")) for row in rows),
                            default=0,
                        )
                        tables.append({"index": index, "rows": len(rows), "columns": columns})

                sections = list(document.iter(f"{_W}sectPr"))
                page: dict[str, Any] = {"sections": max(1, len(sections))}
                if sections:
                    size = sections[-1].find(f"{_W}pgSz")
                    if size is not None:
                        page.update({
                            "width_twips": int(size.get(f"{_W}w", "0") or 0),
                            "height_twips": int(size.get(f"{_W}h", "0") or 0),
                            "orientation": size.get(f"{_W}orient", "portrait"),
                        })

                return {
                    "analyzer": self.__class__.__name__,
                    "analyzer_version": self.analyzer_version,
                    "placeholders": sorted(placeholders.values(), key=lambda item: item["key"]),
                    "headings": headings[:100],
                    "tables": tables[:100],
                    "page": page,
                    "styles": [
                        {"id": style_id, "paragraphs": count}
                        for style_id, count in style_counts.most_common(50)
                    ],
                    "features": {
                        "header": any("/header" in name for name in related_parts),
                        "footer": any("/footer" in name for name in related_parts),
                        "images": len([name for name in names if name.startswith("word/media/")]),
                        "page_number": any(
                            any(
                                node.tag == f"{_W}instrText"
                                and "PAGE" in (node.text or "").upper()
                                for node in root.iter()
                            )
                            for _, root in roots
                        ),
                    },
                }
        except (BadZipFile, KeyError, ValueError) as exc:
            raise ValueError(f"无法分析 Word 模板 {path.name}: {exc}") from exc

    def unresolved_placeholders(self, path: Path) -> list[str]:
        manifest = self.analyze(path)
        return [
            str(item["key"])
            for item in manifest.get("placeholders", [])
            if item.get("required") is True
        ]
