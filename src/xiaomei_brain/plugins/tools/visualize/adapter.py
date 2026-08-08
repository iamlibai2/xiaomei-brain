from pathlib import Path

from .tool import write_visualization_tool


def register(ctx):
    """Expose the bundled visualization working method to this Agent."""
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.register_agent_tool(write_visualization_tool)
    ctx.summary = "write_visualization plus interactive visualization working method"
