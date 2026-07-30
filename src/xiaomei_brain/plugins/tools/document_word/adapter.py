from .extractor import WordExtractor


def register(ctx):
    ctx.register_document_extractor(WordExtractor())
    ctx.summary = "DOCX"
