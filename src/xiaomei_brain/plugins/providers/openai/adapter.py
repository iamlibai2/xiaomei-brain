"""OpenAI provider — 零子类化，直接 ProviderProfile 实例。"""

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition


openai = ProviderProfile(
    provider_id="openai",
    name="OpenAI",
    base_url="https://api.openai.com/v1",
    env_vars=("OPENAI_API_KEY",),
    models=[
        ModelDefinition(id="gpt-4o", name="GPT-4o",
                        context_window=128000, max_tokens=16384,
                        supports_vision=True),
        ModelDefinition(id="gpt-5-mini", name="GPT-5 Mini",
                        context_window=256000, max_tokens=16384),
    ],
)


def register(ctx):
    ctx.register_provider(openai)
