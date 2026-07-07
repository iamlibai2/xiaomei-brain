# 插件开发指南

> xiaomei-brain 支持三类插件：工具、渠道、Provider。本文教你从零开始写插件。

---

## 插件类型

| 类型 | 作用 | 示例 |
|------|------|------|
| **工具插件** | 给 Agent 增加新能力 | 天气查询、日程管理 |
| **渠道插件** | 接入新的消息平台 | Telegram、Slack、Discord |
| **Provider 插件** | 接入新的 LLM 提供商 | Google Gemini、Cohere |

---

## 工具插件

### 最简示例（10 行）

```python
# plugins/tools/weather/plugin.py

from xiaomei_brain.tools.base import tool

@tool(
    name="get_weather",
    description="查询指定城市的实时天气信息",
)
def get_weather(city: str) -> dict:
    """查询天气。

    Args:
        city: 城市名称，如 "北京"、"上海"
    """
    import requests
    resp = requests.get(f"https://api.weather.example.com/v1/now?city={city}")
    return resp.json()
```

### 目录结构

```
plugins/tools/
└── weather/
    ├── __init__.py
    └── plugin.py          # 核心：用 @tool 装饰器注册
```

### @tool 装饰器

```python
@tool(
    name="tool_name",           # 工具名（供 Agent 调用）
    description="工具的描述",    # Agent 根据描述决定何时使用
)
def my_tool(param1: str, param2: int = 10) -> str:
    """函数的 docstring 会被解析为参数说明。

    Args:
        param1: 第一个参数的说明
        param2: 第二个参数的说明（可选，默认 10）
    """
    return "result"
```

### 工具函数约定

1. **参数类型用 Python type hints**：`str`、`int`、`float`、`bool`、`list`、`dict`
2. **docstring 格式**：Google style（Args / Returns），Arg 说明会被提取为参数描述
3. **返回值**：字符串或 dict，不要太长（过长会被截断）
4. **不要做费时操作**：Agent 有 30 秒超时
5. **异步工具**：如果需要长时间操作，使用回调模式

### 完整示例：提醒工具

```python
# plugins/tools/reminder/plugin.py

import json
from pathlib import Path
from xiaomei_brain.tools.base import tool

REMINDERS_FILE = Path.home() / ".xiaomei-brain" / "reminders.json"

def _load():
    if REMINDERS_FILE.exists():
        return json.loads(REMINDERS_FILE.read_text())
    return []

def _save(reminders):
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_FILE.write_text(json.dumps(reminders, ensure_ascii=False, indent=2))

@tool(
    name="add_reminder",
    description="添加一个提醒，到时间会通知",
)
def add_reminder(content: str, time: str) -> str:
    """添加提醒。

    Args:
        content: 提醒内容
        time: 提醒时间，格式 "HH:MM"，如 "14:30"
    """
    reminders = _load()
    reminders.append({"content": content, "time": time, "done": False})
    _save(reminders)
    return f"已添加提醒：{time} — {content}"

@tool(
    name="list_reminders",
    description="列出所有未完成的提醒",
)
def list_reminders() -> str:
    reminders = _load()
    active = [r for r in reminders if not r["done"]]
    if not active:
        return "暂无提醒"
    lines = [f"- {r['time']} {r['content']}" for r in active]
    return "\n".join(lines)

@tool(
    name="complete_reminder",
    description="标记提醒为已完成",
)
def complete_reminder(content: str) -> str:
    reminders = _load()
    for r in reminders:
        if content in r["content"]:
            r["done"] = True
            _save(reminders)
            return f"已完成：{r['content']}"
    return f"未找到：{content}"
```

---

## 渠道插件

参见 [渠道接入指南](./channel-integration.md)。

```python
class ChannelAdapter:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send(self, message: str, target: str) -> None: ...
    @property
    def name(self) -> str: ...
```

---

## Provider 插件

### 核心接口

```python
class ProviderAdapter:
    """LLM Provider 适配器。"""

    def chat_completion(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict | Generator:
        """发送聊天请求，返回 OpenAI 兼容格式的响应。"""
```

关键要求：输出必须是 **OpenAI 兼容格式**（xiaomei-brain 内部统一用 OpenAI 消息格式）。

### 参考实现

```python
# plugins/providers/my_provider/adapter.py

from xiaomei_brain.llm.transport.base import BaseTransport

class MyProviderAdapter(BaseTransport):
    def __init__(self, config: dict):
        self.api_key = config["apiKey"]
        self.base_url = config.get("baseUrl", "https://api.example.com/v1")

    def chat_completion(self, messages, model, tools=None, stream=False, **kwargs):
        # 1. 转换为 provider 的请求格式
        # 2. 发送 HTTP 请求
        # 3. 返回 OpenAI 兼容格式
        return {
            "choices": [{
                "message": {"role": "assistant", "content": "..."},
                "finish_reason": "stop"
            }]
        }
```

### 已有的 Provider

| Provider | 位置 |
|----------|------|
| DeepSeek | `plugins/providers/deepseek/` |
| Anthropic | `plugins/providers/anthropic/` |

---

## 插件加载机制

> `plugin/loader.py`, `plugin/bootstrap.py`

插件在 Agent 启动时自动加载：

```python
# 启动时调用一次
from xiaomei_brain.plugin.bootstrap import boot_plugins

boot_plugins(agent_id)  # 扫描 plugins/ 目录下的所有插件
```

**加载顺序**：
1. 扫描 `plugins/` 目录
2. 按类型加载（tools / channels / providers）
3. 注册到相应的注册表
4. 渠道插件自动启动连接

---

## 测试插件

```python
# tests/plugins/test_reminder.py

def test_add_and_list():
    from plugins.tools.reminder.plugin import add_reminder, list_reminders

    result = add_reminder("测试提醒", "14:30")
    assert "已添加" in result

    result = list_reminders()
    assert "测试提醒" in result
```

```bash
PYTHONPATH=src python3 -m pytest tests/plugins/ -v
```

---

## 代码路径

| 功能 | 位置 |
|------|------|
| 工具基类 | `tools/base.py` |
| 工具注册表 | `tools/registry.py` |
| 插件加载器 | `plugin/loader.py` |
| 插件启动 | `plugin/bootstrap.py` |
| 插件注册表 | `plugin/registry.py` |
| 插件上下文 | `plugin/context.py` |
| 插件清单 | `plugin/manifest.py` |
| 工具集 | `plugin/toolsets.py` |
