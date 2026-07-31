from pathlib import Path

from .extractor import SpreadsheetExtractor
from .writer import SpreadsheetWriter


def register(ctx):
    ctx.register_document_extractor(SpreadsheetExtractor())
    ctx.register_document_writer(SpreadsheetWriter())
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "XLSX read/write"
