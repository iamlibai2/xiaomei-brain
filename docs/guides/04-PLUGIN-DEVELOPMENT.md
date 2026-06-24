# 插件开发指南

> 插件是最灵活的扩展方式——不修改核心代码，就能给 Agent 添加新能力。

---

## 插件类型

xiaomei-brain 支持三种插件类型：

| 类型 | 用途 | 目录 |
|------|------|------|
| Channel | 新消息渠道接入 | `plugins/channels/` |
| Tool | 新工具/能力 | `plugins/tools/` |
| Provider | 新 LLM 服务商 | `plugins/providers/` |

## 插件结构

每个插件是一个独立的 Python 包，放在 `plugins/` 的子目录下：

```
plugins/
├── channels/              # 渠道插件
│   ├── feishu/
│   ├── dingtalk/
│   └── cli/
├── tools/                 # 工具插件
│   ├── tts_minimax/
│   └── image_minimax/
└── providers/             # LLM Provider 插件
    ├── deepseek/
    └── anthropic/
```

## 开发工具插件

参考 [工具开发指南](02-TOOL-DEVELOPMENT.md)。

## 开发 Provider 插件

Provider 插件适配新的 LLM 服务商。所有 Provider 必须实现 OpenAI 兼容接口：

```python
# plugins/providers/my_provider/__init__.py
from xiaomei_brain.llm import BaseProvider

class MyProvider(BaseProvider):
    """我的自定义 LLM Provider"""
    
    @property
    def name(self) -> str:
        return "my_provider"
    
    @property
    def models(self) -> list[str]:
        return ["my-model-v1", "my-model-v2"]
    
    def chat(self, messages: list[dict], model: str, **kwargs) -> dict:
        """调用 LLM 并返回响应"""
        # 实现 OpenAI 兼容的 chat completion 接口
        response = requests.post(
            "https://api.myprovider.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                **kwargs
            }
        )
        return response.json()
    
    def stream_chat(self, messages: list[dict], model: str, **kwargs):
        """流式调用 LLM"""
        response = requests.post(
            "https://api.myprovider.com/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                **kwargs
            },
            stream=True
        )
        for line in response.iter_lines():
            if line:
                yield json.loads(line[6:])  # 跳过 "data: "
```

## 插件自动发现

xiaomei-brain 使用文件系统扫描自动发现插件，无需手动注册。

工作原理：

1. 启动时，系统扫描 `plugins/channels/`, `plugins/tools/`, `plugins/providers/`
2. 每个子目录被识别为一个插件
3. 加载 `__init__.py` 中的 Adapter/Tool/Provider 类
4. 注册到对应的注册表

## 插件配置

插件可以在 `config.json` 中声明自己的配置：

```json
{
  "plugins": {
    "tools": {
      "tts_minimax": {
        "api_key": "your-tts-api-key",
        "voice": "female-1"
      },
      "image_minimax": {
        "api_key": "your-image-api-key"
      }
    },
    "channels": {
      "feishu": {
        "app_id": "cli_xxx",
        "app_secret": "xxx"
      }
    },
    "providers": {
      "deepseek": {
        "api_key": "sk-xxx"
      }
    }
  }
}
```

插件通过 `config_class` 声明配置结构，系统自动校验。
