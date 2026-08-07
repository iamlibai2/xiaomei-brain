"""Register the complete Gmail capability from one cohesive plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime import GmailRuntime
from .tools import create_gmail_tools


class _RuntimeReference:
    """Let tools resolve the runtime after Agent dependencies are injected."""

    def __init__(self) -> None:
        self._runtime: GmailRuntime | None = None

    def bind(self, runtime: GmailRuntime) -> None:
        self._runtime = runtime

    def __getattr__(self, name: str) -> Any:
        if self._runtime is None:
            raise RuntimeError("Gmail 运行组件尚未完成初始化")
        return getattr(self._runtime, name)


def register(ctx):
    runtime_reference = _RuntimeReference()

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
