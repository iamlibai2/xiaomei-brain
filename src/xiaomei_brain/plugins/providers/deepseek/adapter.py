"""DeepSeek provider defaults expressed through generic thinking capabilities."""

from xiaomei_brain.llm.types import (
    ModelDefinition,
    ProviderProfile,
    resolve_provider_thinking_mapping,
    resolve_thinking_capabilities,
)


def register(ctx):
    thinking_format, effort_map = resolve_provider_thinking_mapping("deepseek")
    flash_thinking = resolve_thinking_capabilities(
        "deepseek",
        "deepseek-v4-flash",
        reasoning=True,
    )
    pro_thinking = resolve_thinking_capabilities(
        "deepseek",
        "deepseek-v4-pro",
        reasoning=True,
    )
    ctx.register_provider(ProviderProfile(
        provider_id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        env_vars=("DEEPSEEK_API_KEY",),
        thinking_format=thinking_format,
        thinking_effort_map=effort_map,
        models=[
            ModelDefinition(id="deepseek-v4-flash", name="DeepSeek V4 Flash",
                            context_window=128000, max_tokens=8192, reasoning=True,
                            **flash_thinking),
            ModelDefinition(id="deepseek-v4-pro", name="DeepSeek V4 Pro",
                            context_window=128000, max_tokens=8192, reasoning=True,
                            **pro_thinking),
        ],
    ))
