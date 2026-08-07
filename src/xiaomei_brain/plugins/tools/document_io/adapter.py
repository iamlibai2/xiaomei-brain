from pathlib import Path
from types import SimpleNamespace

from .tool import (
    create_read_document_tool,
    create_write_document_tool,
)
from .template_tool import create_manage_document_template_tool
from xiaomei_brain.documents.templates import DocumentTemplateService


def register(ctx):
    brain_db = Path(ctx.agent_dir) / "memory" / "brain.db"
    template_service = DocumentTemplateService(
        ctx.registry,
        ctx.agent_dir,
        brain_db,
    )
    read_tool = create_read_document_tool(
        ctx.registry,
        lambda: SimpleNamespace(db_path=brain_db),
    )
    read_tool.source = "plugin:document_io"
    write_tool = create_write_document_tool(
        ctx.registry,
        template_service=template_service,
    )
    template_tool = create_manage_document_template_tool(template_service)
    write_tool.source = "plugin:document_io"
    template_tool.source = "plugin:document_io"
    ctx.register_agent_tool(read_tool)
    ctx.register_agent_tool(write_tool)
    ctx.register_agent_tool(template_tool)
    ctx.summary = "read_document / write_document / conversational templates"
