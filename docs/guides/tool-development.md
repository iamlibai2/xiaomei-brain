# 工具开发指南

> 本文详细讲解如何开发 Agent 可用的工具（Tools）。

---

## 工具系统架构

```
Agent 决定调用工具
    │
    ▼
ToolRegistry（工具注册表）
    │
    ├─ execute(name, args) → 调用对应的工具函数
    │
    ▼
工具函数执行 → 返回结果 → Agent 处理结果
    │
    ▲
LLM 读到工具描述 → 决定调用哪个工具
```

工具分为两类：

| 类型 | 位置 | 说明 |
|------|------|------|
| **内置工具** | `tools/builtin/` | 核心工具，随框架一起发布 |
| **插件工具** | `plugins/tools/` | 第三方工具，按需安装 |

---

## 内置工具

### 列表

| 工具名 | 说明 | 代码位置 |
|--------|------|---------|
| `shell` | 执行 shell 命令 | `tools/builtin/shell.py` |
| `read_file` | 读取文件内容 | `tools/builtin/file_ops.py` |
| `write_file` | 写入文件 | `tools/builtin/file_ops.py` |
| `edit_file` | 编辑文件 | `tools/builtin/file_ops.py` |
| `web_search` | 搜索引擎搜索 | `tools/builtin/websearch.py` |
| `web_get` | 抓取网页内容 | `tools/builtin/webget.py` |
| `memory_search` | 记忆搜索 | `tools/builtin/memory_search.py` |
| `dag_expand` | DAG 节点展开 | `tools/builtin/dag_expand.py` |
| `thought_search` | 原始念头搜索 | `tools/builtin/thought_search.py` |
| `send_message` | 发送消息给其他 Agent | `tools/builtin/send_message.py` |
| `manage_session` | 会话管理 | `tools/builtin/manage_session.py` |
| `clarify` | 向用户提问澄清 | `tools/builtin/clarify.py` |
| `goal` | 目标管理 | `tools/builtin/goal.py` |
| `pleasure` | 快乐杠杆 | `tools/builtin/pleasure.py` |

### 内置工具规范

```python
# tools/builtin/file_ops.py — 示例

from xiaomei_brain.tools.base import tool

@tool(
    name="read_file",
    description="读取文件的全部内容",
)
def read_file(path: str) -> str:
    """读取指定路径的文件内容。

    Args:
        path: 文件路径（相对路径或绝对路径）
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
```

---

## Provider 工具（第三方 API 工具）

> `tools/provider/`

调用外部 API 的工具（如 TTS、图片生成、音乐生成）。

```python
# tools/provider/image.py

class ImageProvider:
    """图片生成工具。包装第三方 API。"""

    def generate(self, prompt: str, **kwargs) -> str:
        """调用图片生成 API，返回图片 URL。"""
        response = requests.post(
            "https://api.example.com/generate",
            json={"prompt": prompt, **kwargs}
        )
        return response.json()["url"]
```

### 已有 Provider 工具

| 工具 | 位置 | 依赖 |
|------|------|------|
| TTS | `tools/provider/tts.py` | MiniMax TTS API |
| Image | `tools/provider/image.py` | MiniMax / Seedream API |
| Music | `tools/provider/music.py` | MiniMax Music API |
| Web Search | `tools/provider/websearch.py` | Baidu / 通用搜索 API |
| Web Get | `tools/provider/webget.py` | 网页抓取 |

---

## 工具注册

### 工具集（Tool Profiles）

Agent 通过 `tools.profile` 选择可用的工具集：

| Profile | 包含的工具 |
|---------|-----------|
| `assistant` | 全部内置工具 + Provider 工具 |
| `coding` | shell + file_ops + web_search |
| `minimal` | 仅聊天相关工具 |

### 动态注册

```python
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.base import tool

registry = ToolRegistry()

@tool(name="my_tool", description="我的自定义工具")
def my_tool(param: str) -> str:
    return f"Hello {param}"

registry.register(my_tool)  # 手动注册
```

---

## 工具开发规范

### 命名规范

1. **工具名**：小写 + 下划线，如 `get_weather`、`send_email`
2. **文件名**：与工具名对应，如 `get_weather.py`
3. **函数名**：与工具名一致

### 参数规范

```python
@tool(name="search_documents", description="搜索文档库")
def search_documents(
    query: str,                    # 必填参数
    limit: int = 10,               # 可选参数，有默认值
    category: str | None = None,   # 可选参数，可为 None
) -> list[dict]:
    """搜索文档库。

    Args:
        query: 搜索关键词
        limit: 返回结果数量上限（默认 10）
        category: 筛选分类（可选）
    """
    ...
```

### 返回值规范

- **成功**：返回字符串或 dict（Agent 能理解即可）
- **失败**：返回描述性错误信息，不要抛异常
- **超时**：工具最多执行 30 秒，超时会被终止

### 错误处理

```python
@tool(name="safe_divide", description="安全除法")
def safe_divide(a: float, b: float) -> str:
    try:
        result = a / b
        return f"{a} ÷ {b} = {result}"
    except ZeroDivisionError:
        return "错误：除数不能为零"
```

---

## 工具执行流程

```
Agent 的 ReAct 循环:
1. Think: "用户想查天气，我应该调用 get_weather"
2. Act: ToolRegistry.execute("get_weather", {"city": "北京"})
3. Observe: 工具返回结果 → Agent 处理
4. 重复 1-3，或输出最终回复
```

**缓冲机制**：工具调用有 `ToolCallBuffer` 缓冲，避免连续调用阻塞。

---

## 测试工具

```bash
# 单独测试工具函数
PYTHONPATH=src python3 -c "
from xiaomei_brain.tools.builtin.shell import shell
print(shell('echo hello'))
"

# 使用 pytest
PYTHONPATH=src python3 -m pytest tests/test_tools.py -v
```

---

## 代码路径

| 功能 | 位置 |
|------|------|
| 工具基类 | `tools/base.py` |
| 工具注册表 | `tools/registry.py` |
| 内置工具 | `tools/builtin/` |
| Provider 工具 | `tools/provider/` |
| 工具缓冲 | `agent/tool_call_buffer.py` |
| 插件工具 | `plugins/tools/` |
