"""Select format plugins, cache extraction results and return bounded sections."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .models import DocumentExtraction
from .store import DocumentStore


class DocumentService:
    MAX_READ_CHARS = 20_000

    def __init__(self, registry: Any, db_path: str | Path | None = None) -> None:
        self.registry = registry
        self.db_path = Path(db_path) if db_path else None

    def read(
        self,
        attachment: dict[str, Any],
        *,
        session_id: str,
        section: str = "",
        offset: int = 0,
        limit: int = 12_000,
    ) -> dict[str, Any]:
        path = Path(str(attachment.get("local_path") or ""))
        if not path.is_file():
            raise ValueError("Attachment file is unavailable")
        extractor = self.registry.resolve_document_extractor(
            name=str(attachment.get("name") or path.name),
            mime_type=str(attachment.get("mime_type") or ""),
        )
        if extractor is None:
            raise ValueError("No document extractor supports this attachment")

        digest = self._sha256(path)
        extraction = self._load_cached(
            session_id=session_id,
            attachment_id=str(attachment.get("id") or ""),
            digest=digest,
            extractor=extractor,
        )
        if extraction is None:
            extraction = extractor.extract(path)
            self._save_cached(
                session_id=session_id,
                attachment_id=str(attachment.get("id") or ""),
                digest=digest,
                extraction=extraction,
            )
        return self._project(extraction, attachment, section, offset, limit)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_cached(
        self,
        *,
        session_id: str,
        attachment_id: str,
        digest: str,
        extractor: Any,
    ) -> DocumentExtraction | None:
        if self.db_path is None:
            return None
        store = DocumentStore(self.db_path)
        try:
            return store.load(
                session_id=session_id,
                attachment_id=attachment_id,
                content_sha256=digest,
                extractor_id=extractor.extractor_id,
                extractor_version=extractor.extractor_version,
            )
        finally:
            store.close()

    def _save_cached(
        self,
        *,
        session_id: str,
        attachment_id: str,
        digest: str,
        extraction: DocumentExtraction,
    ) -> None:
        if self.db_path is None:
            return
        store = DocumentStore(self.db_path)
        try:
            store.save(
                session_id=session_id,
                attachment_id=attachment_id,
                content_sha256=digest,
                extraction=extraction,
            )
        finally:
            store.close()

    def _project(
        self,
        extraction: DocumentExtraction,
        attachment: dict[str, Any],
        section_key: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), self.MAX_READ_CHARS))
        sections = list(extraction.sections)
        selected = next((item for item in sections if item.key == section_key), None) if section_key else (sections[0] if sections else None)
        result: dict[str, Any] = {
            "attachment_id": str(attachment.get("id") or ""),
            "name": str(attachment.get("name") or ""),
            "extractor": extraction.extractor_id,
            "metadata": extraction.metadata,
            "sections": [
                {"key": item.key, "title": item.title, "chars": len(item.content), "metadata": item.metadata}
                for item in sections
            ],
        }
        if selected is None:
            if section_key:
                result["error"] = f"Unknown section: {section_key}"
            return result
        content = selected.content[offset:offset + limit]
        next_offset = offset + len(content)
        result["current_section"] = selected.key
        result["content"] = content
        result["offset"] = offset
        result["next_offset"] = next_offset if next_offset < len(selected.content) else None
        return result
