from pathlib import Path

from .extractor import WordExtractor
from .theme_preview import create_preview_word_themes_tool
from .writer import WordWriter


def register(ctx):
    ctx.register_document_extractor(WordExtractor())
    ctx.register_document_writer(WordWriter())
    preview_tool = create_preview_word_themes_tool()
    preview_tool.source = "plugin:document_word"
    ctx.register_agent_tool(preview_tool)
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "DOCX read/write and real theme previews"
