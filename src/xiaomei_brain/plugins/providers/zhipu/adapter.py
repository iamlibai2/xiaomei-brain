"""智谱AI provider — 简单 chat-completions 兼容，不需要 hook。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


zhipu = ProviderProfile(
    provider_id="zhipu",
    name="智谱AI",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    env_vars=("ZHIPU_API_KEY",),
    models=[
        ModelDefinition(id="glm-5.1", name="GLM-5.1",
                        context_window=128000, max_tokens=8192, reasoning=True),
        ModelDefinition(id="glm-5", name="GLM-5",
                        context_window=128000, max_tokens=4096),
    ],
)


def register(ctx):
    ctx.register_provider(zhipu)
