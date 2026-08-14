from pathlib import Path

from .tool import create_build_capability_tool


def register(ctx):
    """Register capability authoring without coupling it to AgentManager."""
    ctx.register_skill_directory(Path(__file__).parent)
    tool = create_build_capability_tool(
        agent_id=ctx.agent_id,
        agent_dir=ctx.agent_dir,
    )
    tool.source = "plugin:capability_development"
    ctx.register_agent_tool(tool)
    ctx.summary = "build_capability plus capability authoring guidance"

