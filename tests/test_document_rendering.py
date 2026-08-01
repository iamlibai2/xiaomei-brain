from __future__ import annotations

from pathlib import Path

from xiaomei_brain.documents import rendering


def test_render_office_document_reports_unsupported_file(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("hello", encoding="utf-8")

    result = rendering.render_office_document(source)

    assert result["status"] == "unsupported"
    assert result["performed"] is False


def test_render_office_document_falls_back_after_backend_failure(
    tmp_path, monkeypatch
):
    source = tmp_path / "report.docx"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(rendering.sys, "platform", "win32")

    def fail_com(source_path: Path, output_path: Path, timeout: float) -> None:
        raise RuntimeError("COM unavailable")

    def render_with_libreoffice(
        source_path: Path, output_path: Path, timeout: float
    ) -> None:
        output_path.write_bytes(b"pdf")

    monkeypatch.setattr(rendering, "_run_windows_office_com", fail_com)
    monkeypatch.setattr(rendering, "_run_libreoffice", render_with_libreoffice)
    monkeypatch.setattr(
        rendering,
        "_inspect_pdf",
        lambda path, backend: {
            "status": "passed",
            "performed": True,
            "backend": backend,
            "page_count": 1,
            "blank_pages": [],
        },
    )

    result = rendering.render_office_document(source)

    assert result["status"] == "passed"
    assert result["backend"] == "libreoffice"
    assert result["pdf_size_bytes"] == 3


def test_render_office_document_reports_all_unavailable_backends(
    tmp_path, monkeypatch
):
    source = tmp_path / "report.docx"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(rendering.sys, "platform", "win32")

    def unavailable(source_path: Path, output_path: Path, timeout: float) -> None:
        raise RuntimeError("not installed")

    monkeypatch.setattr(rendering, "_run_windows_office_com", unavailable)
    monkeypatch.setattr(rendering, "_run_libreoffice", unavailable)

    result = rendering.render_office_document(source)

    assert result["status"] == "unavailable"
    assert result["performed"] is False
    assert [item["backend"] for item in result["attempts"]] == [
        "microsoft-office-com",
        "libreoffice",
    ]


def test_render_office_preview_exports_first_page(tmp_path, monkeypatch):
    source = tmp_path / "template.docx"
    source.write_bytes(b"placeholder")
    output = tmp_path / "preview.png"
    monkeypatch.setattr(rendering.sys, "platform", "win32")

    def render_pdf(source_path: Path, output_path: Path, timeout: float) -> None:
        output_path.write_bytes(b"pdf")

    monkeypatch.setattr(rendering, "_run_windows_office_com", render_pdf)
    def rasterize(pdf_path: Path, png_path: Path) -> dict:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
        return {"width": 800, "height": 1100, "page_count": 2}

    monkeypatch.setattr(rendering, "_render_pdf_first_page", rasterize)

    result = rendering.render_office_preview(source, output)

    assert result == {
        "status": "passed",
        "performed": True,
        "backend": "microsoft-office-com",
        "width": 800,
        "height": 1100,
        "page_count": 2,
    }
    assert output.read_bytes().startswith(b"\x89PNG")
