"""CLIAdapter: 命令行输出适配器。"""

from __future__ import annotations

from xiaomei_brain.gateway.channel_adapter import ChannelAdapter


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
    def channel_type(self) -> str:
        return "cli"
