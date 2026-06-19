"""百度搜索 Provider 插件。

Baidu AI Search (Qianfan) 作为内置保底后端。
外部搜索 provider 可通过相同模式注册，设置更高 priority 覆盖。
"""

import os


def register(ctx):
    from .baidu import BaiduSearchProvider

    # 优先从插件配置获取 key，其次从环境变量
    api_key = ctx.config.get("api_key", "")
    if not api_key:
        api_key = os.getenv("BAIDU_API_KEY", "")

    if not api_key:
        ctx.logger.info("百度搜索 API key 未配置，跳过注册")
        return

    provider = BaiduSearchProvider(api_key=api_key)
    ctx.register_web_search_provider(provider)
