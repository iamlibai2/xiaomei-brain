"""Bounded OOXML helpers used by the Word and Presentation plugins."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from zipfile import ZipFile


MAX_XML_MEMBER_BYTES = 20 * 1024 * 1024
MAX_SECTION_CHARS = 120_000


def read_xml(archive: ZipFile, member: str) -> ET.Element:
    info = archive.getinfo(member)
    if info.file_size > MAX_XML_MEMBER_BYTES:
        raise ValueError(f"Office XML member is too large: {member}")
    return ET.fromstring(archive.read(info))


def bounded_text(text: str, limit: int = MAX_SECTION_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[Section truncated]"
