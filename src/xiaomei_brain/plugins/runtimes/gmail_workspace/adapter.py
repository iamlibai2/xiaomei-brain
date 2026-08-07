"""Register the complete Gmail capability from one cohesive plugin."""

from __future__ import annotations

from pathlib import Path

from xiaomei_brain.capabilities import DeferredCapabilityRuntime

from .runtime import GmailRuntime
from .tools import create_gmail_tools


def register(ctx):
    runtime_reference = DeferredCapabilityRuntime[GmailRuntime]("Gmail")

    def create_runtime(
        *,
        capability_id: str,
        agent_dir: str | Path,
        external_accounts,
        **_dependencies,
    ):
        if capability_id != GmailRuntime.capability_id:
            raise ValueError(f"Unexpected capability id: {capability_id}")
        runtime = GmailRuntime(
            agent_dir=agent_dir,
            account_store=external_accounts,
        )
        runtime_reference.bind(runtime)
        return runtime

    ctx.register_runtime(GmailRuntime.capability_id, create_runtime)
    for tool in create_gmail_tools(runtime_reference):
        tool.source = "plugin:gmail_workspace"
        ctx.register_agent_tool(tool)
    ctx.register_skill_directory(Path(__file__).parent / "skills")
    ctx.summary = "Gmail OAuth, MCP mailbox access, drafts, replies, and delivery"
