"""CLIAdapter: 命令行输出适配器。"""

from __future__ import annotations

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter, ChannelCapabilities


def register(ctx):
    """插件入口：注册 CLI 频道。"""
    ctx.register_channel("cli", CLIAdapter())


class CLIAdapter(ChannelAdapter):
    """CLI 通道适配器：stdin/stdout。

    输入由主线程的 input() 处理，不通过 receive()。
    输出直接 print 到 stdout。
    """

    def send(self, target: str, text: str, msg_type: str = "text") -> None:
        if text.strip():
            print(f"\n{text}", flush=True)

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            streaming=True,
            clarify=True,
            action_approval=True,
            synchronous_action_approval=True,
            attachments=True,
        )

    def request_action_decision(self, payload: dict) -> str | None:
        from xiaomei_brain.tools.builtin.clarify import _cli_callback

        summary = str(payload.get("summary", "需要确认操作"))
        reason = str(payload.get("reason", "")).strip()
        question = summary if not reason else f"{summary}\n原因：{reason}"
        response = _cli_callback(question, ["允许", "拒绝"]).strip().lower()
        if response in {"1", "允许", "allow", "yes", "y"}:
            return "allow"
        return "deny"

    @property
    def channel_type(self) -> str:
        return "cli"
