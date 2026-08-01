"""Generate committed Word theme previews from real Office-rendered documents.

This is a maintainer tool, not a runtime dependency. It requires Pillow and
PyMuPDF, plus Microsoft Word on Windows or LibreOffice on another platform.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from xiaomei_brain.documents.rendering import (
    _run_libreoffice,
    _run_windows_office_com,
)
from xiaomei_brain.plugins.tools.document_word.theme import WORD_THEME_PRESETS
from xiaomei_brain.plugins.tools.document_word.writer import WordWriter


THEME_LABELS = {
    "business-blue": "商务蓝",
    "modern-minimal": "现代简约",
    "warm-professional": "暖色专业",
    "technology": "科技风格",
}


def _sample_specification(preset: str) -> dict:
    label = THEME_LABELS[preset]
    return {
        "title": label,
        "subtitle": "小美 Word 内置主题 · 真实渲染预览",
        "theme": {"preset": preset},
        "page": {
            "size": "A4",
            "margins_cm": {"top": 2.1, "right": 2.2, "bottom": 2.1, "left": 2.2},
        },
        "header": {"text": "XIAOMEI · DOCUMENT"},
        "footer": {"text": label, "page_number": True},
        "blocks": [
            {"type": "heading", "level": 1, "text": "项目概览"},
            {
                "type": "paragraph",
                "text": "以清晰的信息层级、稳定的字体和克制的色彩，呈现专业文档内容。",
            },
            {"type": "heading", "level": 2, "text": "关键进展"},
            {
                "type": "list",
                "items": ["核心方案已经确认", "交付节点按计划推进", "风险与行动保持透明"],
            },
            {
                "type": "table",
                "headers": ["项目", "状态", "负责人"],
                "rows": [["需求分析", "完成", "小美"], ["方案设计", "进行中", "项目组"]],
                "column_widths_cm": [6.5, 4, 4],
            },
            {"type": "quote", "text": "让结构服务于内容，让视觉帮助理解。"},
        ],
    }


def _export_pdf(source: Path, output: Path) -> str:
    attempts: list[str] = []
    if sys.platform == "win32":
        try:
            _run_windows_office_com(source, output, 90.0)
            return "microsoft-office-com"
        except Exception as exc:  # noqa: BLE001 - report all rendering backends
            attempts.append(f"Microsoft Office COM: {exc}")
            output.unlink(missing_ok=True)
    try:
        _run_libreoffice(source, output, 90.0)
        return "libreoffice"
    except Exception as exc:  # noqa: BLE001 - maintainer CLI needs full diagnostics
        attempts.append(f"LibreOffice: {exc}")
    raise RuntimeError("；".join(attempts))


def _render_first_page(pdf_path: Path, png_path: Path) -> None:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("请先安装开发依赖 PyMuPDF") from exc
    document = fitz.open(str(pdf_path))
    try:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        pixmap.save(str(png_path))
    finally:
        document.close()


def _build_showcase(previews: list[tuple[str, Path]], output: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    card_width, page_height = 540, 764
    gap, margin, label_height = 36, 48, 54
    canvas = Image.new(
        "RGB",
        (margin * 2 + card_width * 2 + gap, margin * 2 + (page_height + label_height) * 2 + gap),
        "#EEF1F5",
    )
    draw = ImageDraw.Draw(canvas)
    font = None
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ):
        if candidate.is_file():
            font = ImageFont.truetype(str(candidate), size=22)
            break
    if font is None:
        font = ImageFont.load_default(size=22)
    for index, (preset, source) in enumerate(previews):
        row, column = divmod(index, 2)
        x = margin + column * (card_width + gap)
        y = margin + row * (page_height + label_height + gap)
        with Image.open(source) as opened:
            page = opened.convert("RGB")
        page.thumbnail((card_width, page_height))
        page_x = x + (card_width - page.width) // 2
        draw.rounded_rectangle(
            (x - 2, y - 2, x + card_width + 2, y + page_height + 2),
            radius=8,
            fill="#D9DEE6",
        )
        canvas.paste(page, (page_x, y))
        draw.text(
            (x + card_width / 2, y + page_height + 18),
            f"{THEME_LABELS[preset]} · {preset}",
            fill="#28323F",
            font=font,
            anchor="mm",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    writer = WordWriter()
    previews: list[tuple[str, Path]] = []
    with tempfile.TemporaryDirectory(prefix="xiaomei-word-themes-") as raw_root:
        root = Path(raw_root)
        for preset in WORD_THEME_PRESETS:
            docx_path = root / f"{preset}.docx"
            pdf_path = root / f"{preset}.pdf"
            writer.write(_sample_specification(preset), docx_path)
            backend = _export_pdf(docx_path, pdf_path)
            png_path = output_dir / f"{preset}.png"
            _render_first_page(pdf_path, png_path)
            previews.append((preset, png_path))
            print(f"generated {png_path.name} via {backend}")
        showcase = output_dir / "theme-showcase.png"
        _build_showcase(previews, showcase)
        print(f"generated {showcase.name}")
    return [path for _, path in previews] + [showcase]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_output = Path(__file__).resolve().parents[1] / "assets"
    parser.add_argument("--output-dir", type=Path, default=default_output)
    args = parser.parse_args()
    generate(args.output_dir.resolve())


if __name__ == "__main__":
    main()
