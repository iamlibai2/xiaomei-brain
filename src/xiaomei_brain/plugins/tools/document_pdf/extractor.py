"""Text-layer PDF extraction. OCR is deliberately a later capability."""

from __future__ import annotations

from pathlib import Path

from xiaomei_brain.documents.models import DocumentExtraction, DocumentSection
from xiaomei_brain.documents.office_xml import bounded_text


class PdfExtractor:
    extractor_id = "document_pdf"
    extractor_version = "1.0.0"
    suffixes = (".pdf",)
    mime_types = ("application/pdf",)

    def extract(self, path: Path) -> DocumentExtraction:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise ValueError("PDF 已加密，当前不能读取")
            sections = tuple(
                DocumentSection(
                    key=f"page:{index}",
                    title=f"第 {index} 页",
                    content=bounded_text((page.extract_text() or "").strip() or "[本页没有文本层]"),
                    metadata={"page": index},
                )
                for index, page in enumerate(reader.pages, start=1)
            )
        except ImportError as exc:
            raise ValueError("PDF 解析依赖 pypdf 未安装") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"无法解析 PDF: {path.name}") from exc
        scanned = bool(sections) and all(section.content == "[本页没有文本层]" for section in sections)
        return DocumentExtraction(
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            sections=sections,
            metadata={
                "format": "pdf",
                "page_count": len(sections),
                "requires_ocr": scanned,
                "notice": "该 PDF 可能是扫描件，需要 OCR" if scanned else "",
            },
        )
