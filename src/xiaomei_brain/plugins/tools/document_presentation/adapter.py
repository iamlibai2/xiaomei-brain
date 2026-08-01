from pathlib import Path

from .extractor import PresentationExtractor
from .writer import PresentationWriter


def register(ctx):
    ctx.register_document_extractor(PresentationExtractor())
    ctx.register_document_writer(PresentationWriter())
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "PPTX read/write"
