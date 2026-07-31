from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.tools.builtin.documents import (
    create_read_document_tool,
    create_write_document_tool,
)


def register(ctx):
    brain_db = Path(ctx.agent_dir) / "memory" / "brain.db"
    read_tool = create_read_document_tool(
        ctx.registry,
        lambda: SimpleNamespace(db_path=brain_db),
    )
    read_tool.source = "plugin:document_io"
    write_tool = create_write_document_tool(ctx.registry)
    write_tool.source = "plugin:document_io"
    ctx.register_agent_tool(read_tool)
    ctx.register_agent_tool(write_tool)
    ctx.summary = "read_document / write_document"
