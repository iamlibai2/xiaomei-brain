"""Register deterministic quotation tools."""

from .tool import AUTOMATIC_QUOTATION_TOOLS


def register(ctx):
    for registered_tool in AUTOMATIC_QUOTATION_TOOLS:
        registered_tool.source = "plugin:automatic_quotation"
        registered_tool.optional = True
        registered_tool.emoji = "🧾"
        registered_tool.category = "business"
        ctx.register_agent_tool(registered_tool)
