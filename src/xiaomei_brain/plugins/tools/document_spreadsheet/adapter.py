from .extractor import SpreadsheetExtractor


def register(ctx):
    ctx.register_document_extractor(SpreadsheetExtractor())
    ctx.summary = "XLSX"
