"""Anthropic Messages API provider — 非 OpenAI 协议，需 api_mode 指定 transport。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


anthropic = ProviderProfile(
    provider_id="anthropic",
    name="Anthropic",
    api_mode="anthropic-messages",
    base_url="https://api.anthropic.com",
    env_vars=("ANTHROPIC_API_KEY",),
    models=[
        ModelDefinition(id="claude-opus-4-6", name="Claude Opus 4.6",
                        context_window=200000, max_tokens=32768),
        ModelDefinition(id="claude-sonnet-4-6", name="Claude Sonnet 4.6",
                        context_window=200000, max_tokens=32768),
        ModelDefinition(id="claude-haiku-4-5-20251001", name="Claude Haiku 4.5",
                        context_window=200000, max_tokens=32768),
    ],
)


def register(ctx):
    ctx.register_provider(anthropic)
