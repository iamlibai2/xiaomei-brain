from .extractor import PdfExtractor


def register(ctx):
    ctx.register_document_extractor(PdfExtractor())
    ctx.summary = "PDF"
