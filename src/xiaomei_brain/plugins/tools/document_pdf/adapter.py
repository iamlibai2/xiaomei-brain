from pathlib import Path

from .extractor import PdfExtractor
from .writer import PdfWriter


def register(ctx):
    ctx.register_document_extractor(PdfExtractor())
    ctx.register_document_writer(PdfWriter())
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "PDF read/write"
