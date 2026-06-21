# PLUGIN.md — 插件开发指南

xiaomei-brain 支持三类插件：工具、渠道、Provider。本文带你写出第一个插件。

---

## 插件类型

| 类型 | 作用 | 示例 |
|------|------|------|
| **工具插件** | 给 Agent 增加新能力 | 天气查询、日程管理、代码执行 |
| **渠道插件** | 接入新的消息平台 | Telegram、Slack、Discord |
| **Provider 插件** | 接入新的 LLM 提供商 | 新的 API provider |

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
    # 你的业务逻辑
    import requests
    resp = requests.get(f"https://api.weather.example.com/v1/now?city={city}")
    return resp.json()
```

### 工具注册

工具插件放在 `plugins/tools/` 下，一个插件一个目录：

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
    # 你的逻辑
    return "result"
```

### 工具函数的约定

1. **参数类型用 Python type hints**：`str`、`int`、`float`、`bool`、`list`、`dict`
2. **docstring 格式**：Google style（Args / Returns），Arg 说明会被提取为参数描述
3. **返回值**：字符串或 dict，不要太长（过长会被截断）
4. **不要做费时操作**：Agent 有 30 秒超时

---

## 渠道插件

渠道插件让 Agent 接入新的消息平台。

### 核心接口

```python
class ChannelAdapter:
    """渠道适配器。"""

    def start(self) -> None:
        """启动渠道连接（长连接/轮询/Webhook）。"""

    def stop(self) -> None:
        """断开连接，清理资源。"""

    def send(self, message: str, target: str) -> None:
        """发送消息到指定目标。"""

    @property
    def name(self) -> str:
        """渠道名称（如 'telegram'）。"""
```

### 接入流程

1. 用户配置渠道凭证（通过 `config.json` 或 CLI wizard）
2. Agent 启动时加载所有已启用的渠道适配器
3. 适配器 `start()` 建立连接
4. 收到消息 → `living.put_message(text, user_id, session_id)`
5. Agent 回复 → `adapter.send(reply, target)`

### 参考实现

- `plugins/channels/feishu/` — 飞书 adapter（WebSocket 长连接）
- `plugins/channels/cli/` — CLI adapter（stdin/stdout）
- `plugins/channels/p2p/` — Agent 间通信

---

## Provider 插件

Provider 插件接入新的 LLM 提供商。

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

    @property
    def name(self) -> str:
        """Provider 名称。"""
```

关键要求：输出必须是 **OpenAI 兼容格式**（xiaomei-brain 内部统一用 OpenAI 消息格式）。

### 参考实现

- `plugins/providers/deepseek/` — DeepSeek provider
- `plugins/providers/anthropic/` — Anthropic provider（Claude API → OpenAI 格式转换）

---

## 完整插件示例

一个带配置的工具插件：

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
    """列出所有提醒。"""
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
    """完成提醒。

    Args:
        content: 提醒内容（模糊匹配）
    """
    reminders = _load()
    for r in reminders:
        if content in r["content"]:
            r["done"] = True
            _save(reminders)
            return f"已完成：{r['content']}"
    return f"未找到：{content}"
```

---

## 测试

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
PYTHONPATH=src python3 -m pytest tests/plugins/
```

---

## 更多资源

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 系统架构
- [CONFIG.md](./CONFIG.md) — 配置系统
- [IDENTITY.md](./IDENTITY.md) — Agent 身份定制
