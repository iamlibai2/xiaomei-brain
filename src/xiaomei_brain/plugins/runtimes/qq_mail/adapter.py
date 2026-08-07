"""Register QQ Mail without adding provider-specific branches to Core."""

from __future__ import annotations

from pathlib import Path

from xiaomei_brain.capabilities import DeferredCapabilityRuntime

from .runtime import QQMailRuntime
from .tools import create_qq_mail_tools


def register(ctx):
    runtime_reference = DeferredCapabilityRuntime[QQMailRuntime]("QQ 邮箱")

    def create_runtime(
        *,
        capability_id: str,
        agent_dir: str | Path,
        external_accounts,
        **_dependencies,
    ):
        if capability_id != QQMailRuntime.capability_id:
            raise ValueError(f"Unexpected capability id: {capability_id}")
        runtime = QQMailRuntime(agent_dir=agent_dir, account_store=external_accounts)
        runtime_reference.bind(runtime)
        return runtime

    ctx.register_runtime(QQMailRuntime.capability_id, create_runtime)
    for tool in create_qq_mail_tools(runtime_reference):
        tool.source = "plugin:qq_mail"
        ctx.register_agent_tool(tool)
    ctx.register_skill_directory(Path(__file__).parent / "skills")
    ctx.summary = "QQ Mail authorization-code access through IMAP and SMTP"

