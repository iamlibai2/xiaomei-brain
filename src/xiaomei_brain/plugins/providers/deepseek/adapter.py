"""DeepSeek provider — 需要 override thinking hook。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


class DeepSeekProfile(ProviderProfile):
    """DeepSeek provider — 子类化以提供 V4 thinking hooks。"""

    def build_extra_body(self, model, *, stream: bool, **context) -> dict:
        if model.reasoning:
            return {"thinking": {"type": "enabled"}}
        return {}

    def build_api_kwargs_extras(self, model, **context) -> dict:
        if model.reasoning:
            return {"reasoning_effort": "medium"}
        return {}


def register(ctx):
    ctx.register_provider(DeepSeekProfile(
        provider_id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        env_vars=("DEEPSEEK_API_KEY",),
        models=[
            ModelDefinition(id="deepseek-v4-flash", name="DeepSeek V4 Flash",
                            context_window=128000, max_tokens=8192, reasoning=True),
            ModelDefinition(id="deepseek-v4-pro", name="DeepSeek V4 Pro",
                            context_window=128000, max_tokens=8192, reasoning=True),
        ],
    ))
