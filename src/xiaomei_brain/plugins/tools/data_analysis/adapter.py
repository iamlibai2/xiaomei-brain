from pathlib import Path

from .tool import create_analyze_data_tool


def register(ctx):
    tool = create_analyze_data_tool()
    tool.source = "plugin:data_analysis"
    ctx.register_agent_tool(tool)
    ctx.register_skill_directory(Path(__file__).parent)
    ctx.summary = "CSV/XLSX profile, summary and charts"
