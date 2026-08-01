"""Optional local rendering for Office documents.

Rendering is a quality signal, never a hard dependency. On Windows we prefer
the user's existing Microsoft Office COM server; LibreOffice is the portable
fallback on every platform.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


_POWERSHELL_COM_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$source = [System.IO.Path]::GetFullPath($env:XIAOMEI_RENDER_SOURCE)
$output = [System.IO.Path]::GetFullPath($env:XIAOMEI_RENDER_OUTPUT)
$extension = [System.IO.Path]::GetExtension($source).ToLowerInvariant()

if ($extension -eq '.docx') {
    $application = $null
    $document = $null
    try {
        $application = New-Object -ComObject Word.Application
        $application.Visible = $false
        $application.DisplayAlerts = 0
        try { $application.AutomationSecurity = 3 } catch {}
        $document = $application.Documents.Open($source, $false, $true)
        $document.ExportAsFixedFormat($output, 17)
    }
    finally {
        if ($null -ne $document) {
            try { $document.Close($false) } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
        }
        if ($null -ne $application) {
            try { $application.Quit() } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}
elseif ($extension -eq '.pptx') {
    $application = $null
    $presentation = $null
    try {
        $application = New-Object -ComObject PowerPoint.Application
        $presentation = $application.Presentations.Open($source, $true, $false, $false)
        $presentation.SaveAs($output, 32)
    }
    finally {
        if ($null -ne $presentation) {
            try { $presentation.Close() } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
        }
        if ($null -ne $application) {
            try { $application.Quit() } catch {}
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}
else {
    throw "Unsupported Office extension: $extension"
}
"""


def _powershell_executable() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell")


def _libreoffice_executable() -> str | None:
    discovered = shutil.which("soffice") or shutil.which("libreoffice")
    if discovered:
        return discovered
    if sys.platform == "win32":
        for candidate in (
            Path(os.environ.get("ProgramFiles", "")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "LibreOffice" / "program" / "soffice.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _run_windows_office_com(source: Path, output: Path, timeout: float) -> None:
    executable = _powershell_executable()
    if not executable:
        raise RuntimeError("PowerShell 不可用")
    encoded = base64.b64encode(
        _POWERSHELL_COM_SCRIPT.encode("utf-16-le")
    ).decode("ascii")
    environment = os.environ.copy()
    environment["XIAOMEI_RENDER_SOURCE"] = str(source)
    environment["XIAOMEI_RENDER_OUTPUT"] = str(output)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        errors="replace",
        env=environment,
        timeout=timeout,
        check=False,
        creationflags=creation_flags,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "COM 导出失败").strip()
        raise RuntimeError(detail[-1200:])
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Office COM 未生成 PDF")


def _run_libreoffice(source: Path, output: Path, timeout: float) -> None:
    executable = _libreoffice_executable()
    if not executable:
        raise RuntimeError("LibreOffice 不可用")
    with tempfile.TemporaryDirectory(prefix="xiaomei-soffice-") as directory:
        root = Path(directory)
        converted = root / f"{source.stem}.pdf"
        profile = root / "profile"
        completed = subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(root),
                str(source),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0 or not converted.is_file():
            detail = (completed.stderr or completed.stdout or "LibreOffice 导出失败").strip()
            raise RuntimeError(detail[-1200:])
        shutil.copy2(converted, output)


def _inspect_pdf(path: Path, backend: str) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted or not reader.pages:
        raise RuntimeError("渲染后的 PDF 无法读取")
    blank_pages: list[int] = []
    page_sizes: list[dict[str, float]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        resources = page.get("/Resources") or {}
        has_xobject = bool(resources.get("/XObject"))
        if not text and not has_xobject:
            blank_pages.append(index)
        page_sizes.append({
            "width_pt": round(float(page.mediabox.width), 2),
            "height_pt": round(float(page.mediabox.height), 2),
        })
    return {
        "status": "warning" if blank_pages else "passed",
        "performed": True,
        "backend": backend,
        "page_count": len(reader.pages),
        "blank_pages": blank_pages,
        "page_sizes": page_sizes,
    }


def render_office_document(
    source_path: str | Path,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Render DOCX/PPTX to a temporary PDF and return local validation data."""
    source = Path(source_path).resolve(strict=True)
    if source.suffix.lower() not in {".docx", ".pptx"}:
        return {
            "status": "unsupported",
            "performed": False,
            "reason": f"不支持渲染 {source.suffix.lower()} 文件",
        }

    attempts: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="xiaomei-render-") as directory:
        output = Path(directory) / f"{source.stem}.pdf"
        backends: list[tuple[str, Any]] = []
        if sys.platform == "win32":
            backends.append(("microsoft-office-com", _run_windows_office_com))
        backends.append(("libreoffice", _run_libreoffice))
        for backend, renderer in backends:
            try:
                logger.info(
                    "[DocumentRender] start file=%s backend=%s",
                    source.name,
                    backend,
                )
                renderer(source, output, timeout)
                result = _inspect_pdf(output, backend)
                result["pdf_size_bytes"] = output.stat().st_size
                logger.info(
                    "[DocumentRender] completed file=%s backend=%s "
                    "status=%s pages=%s blank_pages=%s",
                    source.name,
                    backend,
                    result["status"],
                    result["page_count"],
                    result["blank_pages"],
                )
                return result
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                logger.info(
                    "[DocumentRender] unavailable file=%s backend=%s error=%s",
                    source.name,
                    backend,
                    str(exc)[-500:],
                )
                attempts.append({"backend": backend, "error": str(exc)[-500:]})
                output.unlink(missing_ok=True)
    return {
        "status": "unavailable",
        "performed": False,
        "reason": "没有可用的 Office 文档渲染后端",
        "attempts": attempts,
    }
