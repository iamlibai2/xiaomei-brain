from .extractor import PresentationExtractor


def register(ctx):
    ctx.register_document_extractor(PresentationExtractor())
    ctx.summary = "PPTX"
