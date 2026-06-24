# 工具开发指南

> 给 Agent 添加新能力。

---

## 概述

Tools 是 Agent 可以调用的外部能力——执行命令、读写文件、搜索网络、生成图片等。xiaomei-brain 内置了一套工具系统，也支持自定义工具。

## 内置工具列表

| 工具 | 说明 | 源代码 |
|------|------|--------|
| `shell` | 执行 Shell 命令 | `tools/builtin/shell.py` |
| `read_file` | 读取文件 | `tools/builtin/file_ops.py` |
| `write_file` | 写入文件 | `tools/builtin/file_ops.py` |
| `edit_file` | 编辑文件 | `tools/builtin/file_ops.py` |
| `web_search` | 网络搜索 | `tools/builtin/web.py` |
| `web_get` | 抓取网页 | `tools/builtin/web.py` |
| `memory_search` | 搜索记忆 | `tools/builtin/memory.py` |
| `generate_image` | 生成图片（需 MiniMax） | `plugins/tools/image_minimax/` |
| `generate_music` | 生成音乐 | `plugins/tools/music/` |
| `speak` | 文本转语音 | `plugins/tools/tts_minimax/` |

## 开发一个自定义工具

### 最简单的工具

创建一个 Python 文件，用 `@tool` 装饰器注册：

```python
# plugins/tools/weather/__init__.py
from xiaomei_brain.tools import tool

@tool(
    name="get_weather",
    description="获取指定城市的天气信息",
    parameters={
        "city": {
            "type": "string",
            "description": "城市名，如'北京'、'上海'"
        }
    }
)
def get_weather(city: str) -> str:
    """查询天气（示例实现）"""
    # 这里调用真实天气 API
    return f"{city}今日天气：晴，25-30°C，空气质量：良"
```

### 带配置的工具

```python
# plugins/tools/weather/__init__.py
from xiaomei_brain.tools import tool, ToolConfig

class WeatherConfig(ToolConfig):
    api_key: str
    api_base_url: str = "https://api.weather.com"

@tool(
    name="get_weather",
    description="获取指定城市的天气信息",
    config_class=WeatherConfig,
    parameters={
        "city": {"type": "string", "description": "城市名"}
    }
)
def get_weather(city: str, config: WeatherConfig) -> str:
    """查询天气"""
    # 使用 config.api_key 调用 API
    response = requests.get(
        f"{config.api_base_url}/weather",
        params={"city": city, "key": config.api_key}
    )
    return response.text
```

### 有状态工具

```python
# plugins/tools/counter/__init__.py
from xiaomei_brain.tools import tool

class CounterTool:
    def __init__(self):
        self.count = 0
    
    @tool(name="increment", description="计数+1")
    def increment(self) -> str:
        self.count += 1
        return f"当前计数：{self.count}"
    
    @tool(name="reset_counter", description="重置计数")
    def reset(self) -> str:
        self.count = 0
        return "计数已重置"
```

## 自动注册

工具放在 `plugins/tools/` 目录下，系统自动发现并注册：

```
plugins/tools/
├── weather/           ← 自动发现
│   ├── __init__.py
│   └── config.py
├── tts_minimax/       ← 内置
│   ├── __init__.py
│   └── ...
└── image_minimax/     ← 内置
    ├── __init__.py
    └── ...
```

## 工具调用流程

```
Agent 决定调用一个工具
    │
    ▼
Agent 生成工具调用请求（function calling）
    │
    ▼
xiaomei-brain 验证参数（类型检查 + 权限检查）
    │
    ▼
执行工具函数
    │
    ├── 成功 → 返回结果给 LLM
    └── 失败 → 返回错误信息给 LLM（元认知层监控）
```

## 最佳实践

1. **明确的命名**：`get_weather` 比 `weather` 好，工具名应该描述行为
2. **详细的 description**：LLM 通过 description 判断何时调用工具，描述越详细，调用越准确
3. **参数校验**：用 Python type hints + pydantic 做参数校验
4. **错误处理**：工具应该返回友好的错误信息，不要让 LLM 拿到裸异常
5. **幂等性**：如果可能，工具调用应该是幂等的（多次调用结果一致）
6. **超时处理**：网络请求设置超时，防止工具卡死 Agent
