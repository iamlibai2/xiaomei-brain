"""百度搜索 Provider 插件。

Baidu AI Search (Qianfan) 作为内置保底后端。
外部搜索 provider 可通过相同模式注册，设置更高 priority 覆盖。
"""

def register(ctx):
    from .baidu import BaiduSearchProvider

    if ctx.config.get("enabled") is False:
        ctx.logger.info("百度搜索未启用，跳过注册")
        return

    api_key = str(ctx.config.get("api_key", "")).strip()
    if not api_key:
        ctx.logger.info("百度搜索 API key 未配置，跳过注册")
        return

    provider = BaiduSearchProvider(
        api_key=api_key,
        base_url=str(
            ctx.config.get("base_url")
            or "https://qianfan.baidubce.com/v2/ai_search"
        ),
    )
    ctx.register_web_search_provider(provider)
    ctx.summary = f"qianfan.baidubce.com"
