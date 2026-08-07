"""Register the Feishu office managed runtime."""

from .runtime import create_runtime


def register(ctx):
    ctx.register_runtime("feishu_office", create_runtime)
    ctx.summary = "lark-cli install, configuration, authorization, and identity isolation"
