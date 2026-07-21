"""Validation and durable preparation of inbound chat attachments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_OFFICE_XML_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 120_000

IMAGE_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".csv", ".tsv", ".xml", ".html", ".htm", ".css",
    ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".kts",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".rb", ".php", ".swift", ".sql", ".sh", ".bash", ".zsh",
    ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".conf", ".log",
}
OFFICE_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class AttachmentError(ValueError):
    pass


def attachment_fingerprint(attachments: list[Any]) -> str:
    digest = hashlib.sha256()
    for item in attachments:
        values = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for key in ("id", "name", "mime_type", "size", "data_base64"):
            digest.update(str(values.get(key, "")).encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def prepare_attachments(
    agent_id: str,
    session_id: str,
    attachments: list[Any],
) -> tuple[list[dict[str, Any]], list[str], list[Path]]:
    """Decode, validate and persist attachments in the receiving Agent's home."""
    prepared: list[dict[str, Any]] = []
    image_paths: list[str] = []
    saved_paths: list[Path] = []
    total = 0

    safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id or "default")
    session_key = hashlib.sha256((session_id or "main").encode("utf-8")).hexdigest()[:16]
    target_dir = Path.home() / ".xiaomei-brain" / safe_agent / "attachments" / session_key

    try:
        for item in attachments:
            values = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            name = Path(str(values["name"])).name
            mime_type = str(values["mime_type"]).lower().split(";", 1)[0].strip()
            declared_size = int(values["size"])
            try:
                data = base64.b64decode(values["data_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise AttachmentError(f"附件 {name} 的数据无效") from exc

            if len(data) != declared_size:
                raise AttachmentError(f"附件 {name} 的大小与声明不一致")
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise AttachmentError(f"附件 {name} 超过 5 MB")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise AttachmentError("单条消息的附件合计不能超过 8 MB")

            suffix = Path(name).suffix.lower()
            if mime_type in IMAGE_MIMES:
                kind = "image"
                suffix = IMAGE_MIMES[mime_type]
                text_content = None
            elif suffix in OFFICE_TYPES and mime_type in {OFFICE_TYPES[suffix], "application/octet-stream"}:
                kind = "document"
                text_content = extract_office_text(data, suffix, name)
            elif mime_type.startswith("text/") or suffix in TEXT_EXTENSIONS:
                kind = "text"
                try:
                    text_content = data.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise AttachmentError(f"文本附件 {name} 不是 UTF-8 编码") from exc
            else:
                raise AttachmentError(f"暂不支持附件类型：{name} ({mime_type})")

            target_dir.mkdir(parents=True, exist_ok=True)
            file_key = hashlib.sha256(str(values["id"]).encode("utf-8")).hexdigest()[:24]
            local_path = target_dir / f"{file_key}{suffix}"
            local_path.write_bytes(data)
            saved_paths.append(local_path)

            public = {
                "id": str(values["id"]),
                "name": name,
                "mime_type": mime_type,
                "size": len(data),
                "kind": kind,
            }
            prepared_item = {**public, "local_path": str(local_path)}
            if text_content is not None:
                prepared_item["text_content"] = text_content
            else:
                image_paths.append(str(local_path))
            prepared.append(prepared_item)
    except Exception:
        cleanup_attachments(saved_paths)
        raise

    return prepared, image_paths, saved_paths


def cleanup_attachments(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def public_attachment_metadata(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("id", "name", "mime_type", "size", "kind")
    return [{key: item[key] for key in keys if key in item} for item in attachments]


def append_text_attachments(content: str, attachments: list[dict[str, Any]]) -> str:
    text_items = [item for item in attachments if item.get("kind") in {"text", "document"}]
    if not text_items:
        return content
    sections = [content] if content else ["请阅读以下附件并根据其内容作答。"]
    for item in text_items:
        safe_name = html.escape(str(item["name"]), quote=True)
        sections.append(
            f'\n<attached_file name="{safe_name}">\n'
            f'{item.get("text_content", "")}\n'
            "</attached_file>"
        )
    return "\n".join(sections)


def extract_office_text(data: bytes, suffix: str, name: str) -> str:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            if suffix == ".docx":
                return _extract_docx(archive, name)
            if suffix == ".pptx":
                return _extract_pptx(archive, name)
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise AttachmentError(f"无法解析 Office 附件 {name}") from exc
    raise AttachmentError(f"暂不支持 Office 附件 {name}")


def _read_xml(archive: ZipFile, member: str) -> ET.Element:
    info = archive.getinfo(member)
    if info.file_size > MAX_OFFICE_XML_BYTES:
        raise AttachmentError(f"Office 文档内部 XML 过大：{member}")
    return ET.fromstring(archive.read(info))


def _truncate_extracted_text(text: str) -> str:
    if len(text) <= MAX_EXTRACTED_TEXT_CHARS:
        return text
    return text[:MAX_EXTRACTED_TEXT_CHARS] + "\n\n[附件内容过长，已截断]"


def _word_paragraph_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_WORD_NS}t")).strip()


def _extract_docx(archive: ZipFile, name: str) -> str:
    root = _read_xml(archive, "word/document.xml")
    body = root.find(f"{_WORD_NS}body")
    if body is None:
        raise AttachmentError(f"DOCX 附件 {name} 没有正文")
    blocks: list[str] = []
    for child in body:
        if child.tag == f"{_WORD_NS}p":
            text = _word_paragraph_text(child)
            if text:
                blocks.append(text)
        elif child.tag == f"{_WORD_NS}tbl":
            rows: list[str] = []
            for row in child.findall(f"{_WORD_NS}tr"):
                cells = [_word_paragraph_text(cell) for cell in row.findall(f"{_WORD_NS}tc")]
                if any(cells):
                    rows.append("\t".join(cells))
            if rows:
                blocks.append("[表格]\n" + "\n".join(rows))
    return _truncate_extracted_text("\n\n".join(blocks) or "[文档中没有可提取的文字]")


def _numbered_member_key(member: str) -> tuple[int, str]:
    match = re.search(r"(\d+)\.xml$", member)
    return (int(match.group(1)) if match else 0, member)


def _drawing_text(root: ET.Element) -> list[str]:
    return [node.text.strip() for node in root.iter(f"{_DRAWING_NS}t") if node.text and node.text.strip()]


def _extract_pptx(archive: ZipFile, name: str) -> str:
    members = archive.namelist()
    slides = sorted(
        (member for member in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", member)),
        key=_numbered_member_key,
    )
    if not slides:
        raise AttachmentError(f"PPTX 附件 {name} 没有幻灯片")
    note_members = {
        _numbered_member_key(member)[0]: member
        for member in members
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", member)
    }
    sections: list[str] = []
    for index, member in enumerate(slides, start=1):
        lines = _drawing_text(_read_xml(archive, member))
        section = [f"[幻灯片 {index}]", *lines]
        note_member = note_members.get(_numbered_member_key(member)[0])
        if note_member:
            notes = _drawing_text(_read_xml(archive, note_member))
            if notes:
                section.extend(["[备注]", *notes])
        sections.append("\n".join(section))
    return _truncate_extracted_text("\n\n".join(sections))
