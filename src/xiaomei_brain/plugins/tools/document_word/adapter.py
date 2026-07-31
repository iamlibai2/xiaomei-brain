from pathlib import Path

from .extractor import WordExtractor
from .writer import WordWriter


def register(ctx):
    ctx.register_document_extractor(WordExtractor())
    ctx.register_document_writer(WordWriter())
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "DOCX read/write"
