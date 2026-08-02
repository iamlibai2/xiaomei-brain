"""Validation and durable preparation of inbound chat attachments."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from pathlib import Path
from typing import Any

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_REFERENCED_ARTIFACT_BYTES = 20 * 1024 * 1024

IMAGE_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}
AUDIO_MIMES = {
    "audio/webm": ".webm",
    "audio/opus": ".opus",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/amr": ".amr",
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".csv", ".tsv", ".xml", ".html", ".htm", ".css",
    ".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".kts",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".rb", ".php", ".swift", ".sql", ".sh", ".bash", ".zsh",
    ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".conf", ".log",
}
DOCUMENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


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
    *,
    max_item_bytes: int = MAX_ATTACHMENT_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
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
            if len(data) > max_item_bytes:
                raise AttachmentError(
                    f"附件 {name} 超过 {max_item_bytes // (1024 * 1024)} MB"
                )
            total += len(data)
            if total > max_total_bytes:
                raise AttachmentError(
                    f"单条消息的附件合计不能超过 {max_total_bytes // (1024 * 1024)} MB"
                )

            suffix = Path(name).suffix.lower()
            if mime_type in IMAGE_MIMES:
                kind = "image"
                suffix = IMAGE_MIMES[mime_type]
                text_content = None
            elif mime_type in AUDIO_MIMES:
                kind = "audio"
                suffix = AUDIO_MIMES[mime_type]
                text_content = None
            elif suffix in DOCUMENT_TYPES and mime_type in {DOCUMENT_TYPES[suffix], "application/octet-stream"}:
                kind = "document"
                text_content = None
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
            elif kind == "image":
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
    keys = (
        "id",
        "name",
        "mime_type",
        "size",
        "kind",
        "source_artifact",
        "annotation",
    )
    return [{key: item[key] for key in keys if key in item} for item in attachments]


def read_stored_attachment(
    agent_id: str,
    session_id: str,
    attachment: dict[str, Any],
) -> dict[str, Any]:
    """Read a session-owned attachment without accepting a filesystem path."""
    attachment_id = str(attachment.get("id", ""))
    name = Path(str(attachment.get("name", ""))).name
    mime_type = str(attachment.get("mime_type", "")).lower()
    kind = str(attachment.get("kind", ""))
    declared_size = int(attachment.get("size", 0))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", attachment_id):
        raise AttachmentError("附件标识无效")
    max_bytes = (
        MAX_REFERENCED_ARTIFACT_BYTES
        if isinstance(attachment.get("source_artifact"), dict)
        else MAX_ATTACHMENT_BYTES
    )
    if not name or declared_size <= 0 or declared_size > max_bytes:
        raise AttachmentError("附件元数据无效")

    if kind == "image" and mime_type in IMAGE_MIMES:
        suffix = IMAGE_MIMES[mime_type]
    elif kind == "audio" and mime_type in AUDIO_MIMES:
        suffix = AUDIO_MIMES[mime_type]
    elif kind == "document" and Path(name).suffix.lower() in DOCUMENT_TYPES:
        suffix = Path(name).suffix.lower()
    elif kind == "text" and (
        mime_type.startswith("text/") or Path(name).suffix.lower() in TEXT_EXTENSIONS
    ):
        suffix = Path(name).suffix.lower()
    else:
        raise AttachmentError("附件类型无效")

    attachment_path = _stored_attachment_path(agent_id, session_id, attachment_id, suffix)
    try:
        data = attachment_path.read_bytes()
    except FileNotFoundError as exc:
        raise AttachmentError("附件文件不存在或已被移除") from exc
    if len(data) != declared_size or len(data) > max_bytes:
        raise AttachmentError("附件文件与会话记录不一致")

    return {
        **public_attachment_metadata([attachment])[0],
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def restore_attachment_refs(
    agent_id: str,
    session_id: str,
    attachments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Restore Agent-owned attachments for a new turn without rewriting files."""
    if len(attachments) > 4:
        raise AttachmentError("一次最多引用 4 个附件")
    prepared: list[dict[str, Any]] = []
    image_paths: list[str] = []
    total = 0
    seen: set[str] = set()
    max_total_bytes = (
        MAX_REFERENCED_ARTIFACT_BYTES
        if any(isinstance(item.get("source_artifact"), dict) for item in attachments)
        else MAX_TOTAL_BYTES
    )
    for attachment in attachments:
        attachment_id = str(attachment.get("id", ""))
        if attachment_id in seen:
            raise AttachmentError("附件引用不能重复")
        seen.add(attachment_id)
        stored = read_stored_attachment(agent_id, session_id, attachment)
        data = base64.b64decode(stored["data_base64"], validate=True)
        total += len(data)
        if total > max_total_bytes:
            raise AttachmentError(
                f"引用附件合计不能超过 {max_total_bytes // (1024 * 1024)} MB"
            )

        name = str(stored["name"])
        mime_type = str(stored["mime_type"])
        kind = str(stored["kind"])
        if kind == "image":
            suffix = IMAGE_MIMES[mime_type]
        elif kind == "audio":
            suffix = AUDIO_MIMES[mime_type]
        else:
            suffix = Path(name).suffix.lower()
        local_path = _stored_attachment_path(
            agent_id, session_id, attachment_id, suffix,
        )
        item = {
            **public_attachment_metadata([stored])[0],
            "local_path": str(local_path),
        }
        if kind == "image":
            image_paths.append(str(local_path))
        elif kind == "audio":
            pass
        elif kind == "text":
            try:
                item["text_content"] = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AttachmentError(f"文本附件 {name} 不是 UTF-8 编码") from exc
        prepared.append(item)
    return prepared, image_paths


def _stored_attachment_path(
    agent_id: str,
    session_id: str,
    attachment_id: str,
    suffix: str,
) -> Path:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id or "default")
    session_key = hashlib.sha256((session_id or "main").encode("utf-8")).hexdigest()[:16]
    file_key = hashlib.sha256(attachment_id.encode("utf-8")).hexdigest()[:24]
    return (
        Path.home() / ".xiaomei-brain" / safe_agent / "attachments"
        / session_key / f"{file_key}{suffix}"
    )


def append_text_attachments(content: str, attachments: list[dict[str, Any]]) -> str:
    context_items = [
        item for item in attachments
        if item.get("kind") in {"text", "document", "image"}
    ]
    if not context_items:
        return content
    sections = [content] if content else ["请阅读以下附件并根据其内容作答。"]
    for item in context_items:
        safe_name = html.escape(str(item["name"]), quote=True)
        managed_relative_path = html.escape(
            str(item.get("managed_artifact_relative_path", "")),
            quote=True,
        )
        path_attribute = (
            f' workspace_path="{managed_relative_path}"'
            if managed_relative_path else ""
        )
        annotation = item.get("annotation")
        annotation_context = ""
        if isinstance(annotation, dict):
            annotation_kind = str(annotation.get("kind", ""))
            selected_text = html.escape(
                str(annotation.get("selected_text", "")),
                quote=False,
            )
            if annotation_kind == "spreadsheet" and selected_text:
                sheet = html.escape(str(annotation.get("sheet", "")), quote=True)
                cell_range = html.escape(str(annotation.get("range", "")), quote=True)
                annotation_context = (
                    f'\n<document_annotation kind="spreadsheet" sheet="{sheet}" '
                    f'range="{cell_range}">\n'
                    f"<selected_cells>{selected_text}</selected_cells>\n"
                    "Treat the user's message as an instruction for this exact cell range. "
                    "Update this Agent-owned artifact in place, preserve formulas and formatting outside the range, "
                    "and update dependent totals when required.\n"
                    "</document_annotation>"
                )
            elif annotation_kind == "html" and annotation.get("outer_html"):
                selector = html.escape(str(annotation.get("selector", "")), quote=True)
                tag = html.escape(str(annotation.get("tag", "")), quote=True)
                outer_html = html.escape(str(annotation.get("outer_html", "")), quote=False)
                context_before = html.escape(str(annotation.get("context_before", "")), quote=False)
                context_after = html.escape(str(annotation.get("context_after", "")), quote=False)
                annotation_context = (
                    f'\n<document_annotation kind="html" selector="{selector}" tag="{tag}">\n'
                    f"<context_before>{context_before}</context_before>\n"
                    f"<selected_text>{selected_text}</selected_text>\n"
                    f"<selected_html>{outer_html}</selected_html>\n"
                    f"<context_after>{context_after}</context_after>\n"
                    "Treat the user's message as an instruction for this exact HTML element or text selection. "
                    "Use the attached_file workspace_path exactly. Update the Agent-owned HTML artifact in place, "
                    "preserve unrelated markup and styling, "
                    "then present the same artifact again.\n"
                    "</document_annotation>"
                )
            elif selected_text:
                page = annotation.get("page")
                page_attribute = f' page="{int(page)}"' if isinstance(page, int) else ""
                context_before = html.escape(str(annotation.get("context_before", "")), quote=False)
                context_after = html.escape(str(annotation.get("context_after", "")), quote=False)
                annotation_context = (
                    f'\n<document_annotation kind="text"{page_attribute}>\n'
                    f"<context_before>{context_before}</context_before>\n"
                    f"<selected_text>{selected_text}</selected_text>\n"
                    f"<context_after>{context_after}</context_after>\n"
                    "Treat the user's message as an instruction for this exact selection. "
                    "Use the attached_file workspace_path exactly. Update this Agent-owned artifact in place, "
                    "preserve unrelated content and formatting, then present the same artifact again.\n"
                    "</document_annotation>"
                )
        if item.get("kind") == "document":
            safe_id = html.escape(str(item.get("id", "")), quote=True)
            safe_mime = html.escape(str(item.get("mime_type", "")), quote=True)
            sections.append(
                f'\n<attached_document id="{safe_id}" name="{safe_name}" mime_type="{safe_mime}">\n'
                "Use the read_document tool with this attachment id to inspect its content.\n"
                f"{annotation_context}\n"
                "</attached_document>"
            )
        elif item.get("kind") == "image":
            safe_id = html.escape(str(item.get("id", "")), quote=True)
            safe_mime = html.escape(str(item.get("mime_type", "")), quote=True)
            sections.append(
                f'\n<attached_image id="{safe_id}" name="{safe_name}" mime_type="{safe_mime}">\n'
                "This image id can be used as attachment_id in a document specification.\n"
                "</attached_image>"
            )
        else:
            sections.append(
                f'\n<attached_file name="{safe_name}"{path_attribute}>\n'
                f'{item.get("text_content", "")}\n'
                f"{annotation_context}\n"
                "</attached_file>"
            )
    return "\n".join(sections)
