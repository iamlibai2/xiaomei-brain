"""PPTX slide and speaker-note extraction."""

from __future__ import annotations

import re
from posixpath import dirname, join, normpath
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from xiaomei_brain.documents.models import DocumentExtraction, DocumentSection
from xiaomei_brain.documents.office_xml import bounded_text, read_xml


_DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_PRESENTATION_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_OFFICE_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _member_number(member: str) -> int:
    match = re.search(r"(\d+)\.xml$", member)
    return int(match.group(1)) if match else 0


def _lines(root) -> list[str]:
    return [
        node.text.strip()
        for node in root.iter(f"{_DRAWING_NS}t")
        if node.text and node.text.strip()
    ]


def _relationships(archive: ZipFile, member: str) -> dict[str, tuple[str, str]]:
    if member not in archive.namelist():
        return {}
    root = read_xml(archive, member)
    return {
        str(node.get("Id")): (str(node.get("Target") or ""), str(node.get("Type") or ""))
        for node in root.iter(f"{_PACKAGE_REL_NS}Relationship")
        if node.get("Id")
    }


def _ordered_slides(archive: ZipFile, members: list[str]) -> list[str]:
    presentation_member = "ppt/presentation.xml"
    relationships_member = "ppt/_rels/presentation.xml.rels"
    if presentation_member in members and relationships_member in members:
        relations = _relationships(archive, relationships_member)
        root = read_xml(archive, presentation_member)
        ordered = []
        for node in root.iter(f"{_PRESENTATION_NS}sldId"):
            relation_id = node.get(f"{_OFFICE_REL_NS}id")
            target = relations.get(str(relation_id), ("", ""))[0]
            if not target:
                continue
            member = normpath(join(dirname(presentation_member), target))
            if member in members:
                ordered.append(member)
        if ordered:
            return ordered
    return sorted(
        (name for name in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
        key=_member_number,
    )


def _notes_member(archive: ZipFile, slide_member: str) -> str | None:
    slide_name = slide_member.rsplit("/", 1)[-1]
    relationships_member = (
        f"{dirname(slide_member)}/_rels/{slide_name}.rels"
    )
    for target, relation_type in _relationships(archive, relationships_member).values():
        if relation_type.endswith("/notesSlide"):
            return normpath(join(dirname(slide_member), target))
    return None


class PresentationExtractor:
    extractor_id = "document_presentation"
    extractor_version = "1.1.0"
    suffixes = (".pptx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    def extract(self, path: Path) -> DocumentExtraction:
        try:
            with ZipFile(path) as archive:
                members = archive.namelist()
                slides = _ordered_slides(archive, members)
                if not slides:
                    raise ValueError("演示文稿没有幻灯片")
                sections = []
                for index, member in enumerate(slides, start=1):
                    content = _lines(read_xml(archive, member))
                    note_member = _notes_member(archive, member)
                    if note_member is None:
                        # Keep best-effort support for minimal or damaged PPTX
                        # archives that omit slide relationship files.
                        note_member = (
                            "ppt/notesSlides/notesSlide"
                            f"{_member_number(member)}.xml"
                        )
                    if note_member and note_member in members:
                        note_lines = _lines(read_xml(archive, note_member))
                        if note_lines:
                            content.extend(["", "[备注]", *note_lines])
                    sections.append(DocumentSection(
                        key=f"slide:{index}",
                        title=f"第 {index} 页",
                        content=bounded_text("\n".join(content) or "[没有可提取的文字]"),
                        metadata={"slide": index},
                    ))
        except (BadZipFile, KeyError, ValueError) as exc:
            raise ValueError(f"无法解析演示文稿: {path.name}") from exc
        return DocumentExtraction(
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            sections=tuple(sections),
            metadata={"format": "pptx", "slide_count": len(sections)},
        )
