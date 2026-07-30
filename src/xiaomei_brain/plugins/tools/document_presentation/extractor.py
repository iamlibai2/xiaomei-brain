"""PPTX slide and speaker-note extraction."""

from __future__ import annotations

import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from xiaomei_brain.documents.models import DocumentExtraction, DocumentSection
from xiaomei_brain.documents.office_xml import bounded_text, read_xml


_DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _member_number(member: str) -> int:
    match = re.search(r"(\d+)\.xml$", member)
    return int(match.group(1)) if match else 0


def _lines(root) -> list[str]:
    return [
        node.text.strip()
        for node in root.iter(f"{_DRAWING_NS}t")
        if node.text and node.text.strip()
    ]


class PresentationExtractor:
    extractor_id = "document_presentation"
    extractor_version = "1.0.0"
    suffixes = (".pptx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    def extract(self, path: Path) -> DocumentExtraction:
        try:
            with ZipFile(path) as archive:
                members = archive.namelist()
                slides = sorted(
                    (name for name in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=_member_number,
                )
                if not slides:
                    raise ValueError("演示文稿没有幻灯片")
                notes = {
                    _member_number(name): name
                    for name in members
                    if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
                }
                sections = []
                for index, member in enumerate(slides, start=1):
                    content = _lines(read_xml(archive, member))
                    note_member = notes.get(_member_number(member))
                    if note_member:
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
