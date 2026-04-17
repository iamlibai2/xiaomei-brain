# xiaomei-brain 开发日志：WebSocket 服务、工具增强与系统检查

> 本教程记录 2026-04-14 的开发工作。读者可以通过本文了解 xiaomei-brain 项目的开发思路、代码组织方式，以及如何渐进式添加新功能。

---

## 目录

1. [项目概述](#1-项目概述)
2. [问题修复：KeyboardInterrupt 处理](#2-问题修复keyboardinterrupt-处理)
3. [问题修复：TextEncodeError 输入过滤](#3-问题修复textencodeerror-输入过滤)
4. [功能增强：百度搜索](#4-功能增强百度搜索)
5. [功能增强：网页抓取（web_get）](#5-功能增强网页抓取web_get)
6. [功能增强：WebSocket 服务](#6-功能增强websocket-服务)
7. [工具：轻量级 doctor 检查](#7-工具轻量级-doctor-检查)
8. [开发经验总结](#8-开发经验总结)

---

## 1. 项目概述

**xiaomei-brain** 是一个 Python AI Agent 项目，核心是一个支持工具调用、记忆系统、TTS 语音合成的对话智能体。

核心技术栈：
- **LLM**：通过 OpenAI 兼容 API 调用（支持智谱、火山引擎、OpenAI、Minimax）
- **工具系统**：Registry 模式，支持 shell、文件读写、搜索、TTS、图生图等
- **记忆系统**：本地向量索引（sentence-transformers）+ 主题文件存储
- **TTS**：流式语音合成，支持边生成边播放
- **WebSocket**：将能力对外提供服务（新增）

项目结构：
```
src/xiaomei_brain/
├── agent.py          # Agent 核心，stream() 生成器
├── llm.py             # LLM 客户端
├── config.py          # 配置管理（YAML + dataclass）
├── session.py         # 会话持久化
├── context.py         # 上下文管理
├── memory/            # 记忆系统
│   ├── store.py       # MemoryStore
│   ├── search.py      # Embedder + VectorIndex
│   └── ...
├── tools/
│   ├── base.py        # @tool 装饰器
│   ├── registry.py    # ToolRegistry
│   └── builtin/       # 内置工具
├── speech/
│   ├── tts.py        # TTS Provider
│   └── music.py       # 音乐生成
├── ws/                # WebSocket 服务（新增）
│   ├── server.py
│   ├── protocol.py
│   ├── session.py
│   └── connection.py
└── doctor.py          # 健康检查（新增）
```

---

## 2. 问题修复：KeyboardInterrupt 处理

### 问题现象

在 `basic_agent.py` 中使用 Ctrl+C 退出时，出现了 traceback：

```
Traceback (most recent call last):
  ...
  File "examples/basic_agent.py", line 302, in main
    user_input = input("You: ").strip()
KeyboardInterrupt
```

### 问题根因

`input()` 抛出 `KeyboardInterrupt` 后，只有 `except EOFError` 捕获了它（line 303），而 `EOFError != KeyboardInterrupt`，所以异常继续向上传播到 `finally` 块。

### 修复方案

把内层 `try/except` 的 `except EOFError` 改为 `except (KeyboardInterrupt, EOFError)`，让 Ctrl+C 在 `input()` 层面就被捕获：

```python
# 修复前
try:
    user_input = input("You: ").strip()
except EOFError:
    break

# 修复后
try:
    user_input = input("You: ").strip()
except (KeyboardInterrupt, EOFError):
    print("\nBye!")
    break
```

同时删除了外层多余的 `except KeyboardInterrupt`（因为现在已经被内层捕获了）。

**经验**：异常处理要有层次感，`input()` 的异常应该在 `input()` 这一层捕获，不要指望外层来处理。

---

## 3. 问题修复：TextEncodeError 输入过滤

### 问题现象

用户输入包含特殊字符时（如控制字符、非标准 Unicode），Agent 的 embedding 步骤会抛出 `TextEncodeError`。

### 问题根因

`sentence-transformers` 的 `model.encode()` 对输入有严格校验，不接受控制字符（0x00-0x1f 范围内的非 `\t\n\r`）、无效 Unicode 序列等。

### 修复方案

在 `memory/search.py` 中添加 `sanitize_text()` 函数，在 embedding 之前过滤输入：

```python
import unicodedata

def sanitize_text(text: str) -> str:
    """Clean text to prevent encoding errors in embedding models."""
    # NFKC 归一化
    text = unicodedata.normalize("NFKC", text)
    # 移除控制字符（保留 tab/newline/cr）
    text = "".join(c for c in text if unicodedata.category(c) != "Cc" or c in "\t\n\r")
    # 将其他不可打印字符替换为空格
    text = "".join(c if unicodedata.category(c)[0] != "C" else " " for c in text)
    # 折叠多余空格
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

在 `Embedder.embed()` 和 `embed_batch()` 中调用：

```python
def embed(self, text: str) -> list[float]:
    text = sanitize_text(text)  # ← 过滤
    model = self._load_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()
```

在 `MemoryStore.search()` 的 query 入口也加上过滤：

```python
query_vector = self.embedder.embed(sanitize_text(query))
```

**经验**：对外部输入（用户输入、文件内容）做过滤是个好习惯，特别是在调用底层库之前。这次修复只加了一个函数 + 两行调用，影响范围小，却解决了高频崩溃。

---

## 4. 功能增强：百度搜索

### 需求

将 OpenClaw 的 baidu-search skill 迁移到 xiaomei-brain 项目中，实现联网搜索能力。

### 实现

**Provider**：`websearch.py`

```python
class BaiduSearchProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://qianfan.baidubce.com/v2/ai_search/web_search"

    def search(self, query: str, count: int = 10,
              freshness: str | None = None) -> list[SearchResult]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "count": count}
        if freshness:
            payload["freshness"] = freshness

        resp = requests.post(self.endpoint, json=payload,
                             headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("result", {}).get("items", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                time=item.get("timestamp"),
            ))
        return results
```

**Tool**：`tools/builtin/websearch.py`

```python
@tool(
    name="web_search",
    description="使用百度搜索实时信息、文档或研究主题..."
)
def web_search(query: str, count: int = 10,
                freshness: str | None = None) -> str:
    if _search_provider is None:
        return "百度搜索未启用..."
    results = _search_provider.search(query=query, count=count,
                                      freshness=freshness)
    output = f"找到 {len(results)} 条结果:\n\n"
    for i, r in enumerate(results, 1):
        time_str = f" ({r.time})" if r.time else ""
        output += f"{i}. {r.title}{time_str}\n   {r.url}\n\n"
    return output.strip()
```

**配置集成**：

- `config.py` 添加 `web_search_enabled`、`baidu_api_key` 字段
- `config.yaml` 添加 `web_search` section
- `basic_agent.py` 中创建 Provider、注册工具

**经验**：迁移 OpenClaw 功能到 xiaomei-brain 的模式是固定的：
1. 创建 `*Provider` 类封装 API 调用
2. 创建 `*Tool` 函数用 `@tool` 装饰器
3. 在 `Config` 中加配置字段
4. 在 Agent 示例中注册

---

## 5. 功能增强：网页抓取（web_get）

### 需求

实现类似 OpenClaw `web_fetch` 的工具，可以抓取任意 URL 并提取可读内容（markdown 或纯文本）。

### 实现

**Provider**：`webget.py`

核心逻辑分三层：

1. **HTTP 请求**：用 `requests` 抓取，设置 User-Agent、Accept 头
2. **内容检测**：根据 `Content-Type` 或 HTML 特征判断类型
3. **内容提取**：
   - HTML → `_html_to_markdown()` 转成 markdown（提取标题、链接转 `[text](url)`、headers、列表）
   - Markdown → 直接返回
   - JSON → `json.dumps(..., indent=2)` 格式化
   - 纯文本 → 归一化 whitespace

```python
def _html_to_markdown(html: str) -> tuple[str, str | None]:
    """HTML 转 markdown，提取标题"""
    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>",
                            html, re.IGNORECASE)
    title = None
    if title_match:
        title = _normalize_whitespace(_strip_tags(title_match.group(1)))

    text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>",
                  lambda m: f"[{_normalize_whitespace(_strip_tags(m.group(2)))}]({m.group(1)})",
                  text, flags=re.IGNORECASE)
    # ... headers, lists, block elements ...
    return _normalize_whitespace(_strip_tags(text)), title
```

**Tool**：`tools/builtin/webget.py`

```python
@tool(name="web_get", description="抓取网页内容并提取可读文本...")
def web_get(url: str, extract_mode: str = "markdown",
            max_chars: int = 40000) -> str:
    result = _get_provider.fetch(url, extract_mode, max_chars)
    lines = [
        f"# {result.title}" if result.title else "网页内容",
        f"URL: {result.final_url}",
        f"状态: {result.status}",
        f"类型: {result.content_type}",
        f"提取方式: {result.extractor}",
        "",
        "---",
        "",
        result.text,
    ]
    output = "\n".join(lines)
    if result.truncated:
        output += "\n\n> 内容已截断"
    return output
```

**命名说明**：最初叫 `web_fetch`，应用户要求改为 `web_get`。重命名涉及：
- `webfetch.py` → `webget.py`
- `WebFetchProvider` → `WebGetProvider`
- `FetchResult` → `GetResult`
- `web_fetch` tool → `web_get`
- `set_fetch_provider` → `set_get_provider`
- `config.yaml` 中 `web_fetch` section → `web_get`
- `config.py` 中 `web_fetch_enabled` → `web_get_enabled`

**经验**：模块/函数重命名时，用 `grep -r` 全局搜索所有引用，一次性全部替换。

---

## 6. 功能增强：WebSocket 服务

### 需求

将 Agent 能力（对话流、工具调用、TTS）通过 WebSocket 对外提供服务，支持实时流式响应。

### 架构设计

```
ws/
├── __init__.py      # 导出 create_app
├── protocol.py      # 消息类型定义
├── session.py       # ClientSession（会话状态）
├── connection.py    # ConnectionManager（连接管理）
└── server.py        # FastAPI + WebSocket 主服务
```

### 协议设计

采用 JSON over WebSocket 双向通信：

**客户端 → 服务端：**

| type | 说明 | 字段 |
|------|------|------|
| `chat` | 聊天消息 | `content`, `session_id` |
| `tool_call` | 显式工具调用 | `name`, `params` |
| `session_start` | 开始/恢复会话 | `session_id`（可选） |
| `session_end` | 结束会话 | — |
| `ping` | 心跳 | — |

**服务端 → 客户端：**

| type | 说明 | 字段 |
|------|------|------|
| `chat_start` | 开始响应 | `session_id`, `message_id` |
| `text_chunk` | 流式文本片段 | `content` |
| `text_done` | 响应完成 | `content` |
| `tool_call_start` | 工具开始 | `call_id`, `name`, `params` |
| `tool_call_result` | 工具结果 | `call_id`, `result`, `error` |
| `audio_chunk` | TTS 音频（base64） | `data` |
| `audio_done` | 音频流结束 | — |
| `session_started` | 会话已启动 | `session_id`, `resumed` |
| `error` | 错误 | `message`, `code` |

### 核心实现：server.py

**关键设计决策**：Agent 是同步阻塞的（`Agent.stream()` 是同步生成器），而 WebSocket 需要异步读写。

解决方案：用 `ThreadPoolExecutor` 把同步调用扔到线程池：

```python
executor = ThreadPoolExecutor(max_workers=10)

async def handle_chat(ws: WebSocket, msg: dict):
    loop = asyncio.get_event_loop()
    # run_in_executor 把同步的 agent.stream() 放到线程池执行
    # 避免阻塞事件循环
    await loop.run_in_executor(
        executor,
        lambda: stream_chunks(client_session, ws, msg["content"])
    )
```

**工具调用拦截**：用 monkey-patch 方式拦截 `tools.execute()`，在执行前后发送事件：

```python
original_execute = agent.tools.execute

def tracked_execute(name: str, **kwargs):
    call_id = str(uuid.uuid4())
    asyncio.create_task(ws.send_json({
        "type": "tool_call_start",
        "call_id": call_id, "name": name, "params": kwargs
    }))
    result = original_execute(name, **kwargs)
    asyncio.create_task(ws.send_json({
        "type": "tool_call_result",
        "call_id": call_id, "result": result, "error": None
    }))
    return result

agent.tools.execute = tracked_execute
```

**TTS 流式传输**：TTS Provider 使用回调模式，在回调里把音频 chunk base64 编码后发送：

```python
def on_audio_chunk(chunk: bytes):
    encoded = base64.b64encode(chunk).decode()
    asyncio.create_task(ws.send_json({
        "type": "audio_chunk", "data": encoded
    }))

loop.run_in_executor(executor,
    lambda: tts_provider.speak_streaming(text, on_audio_chunk))
```

### session.py — 会话状态管理

```python
@dataclass
class ClientSession:
    id: str                          # 会话 ID
    agent: Any                       # 共享 Agent 实例
    session_manager: SessionManager  # 持久化
    messages: list[dict] = field(default_factory=list)

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def save(self) -> str:
        return self.agent.save_session(self.session_manager, self.id,
                                       messages=self.messages)

    def restore(self, session_id: str) -> bool:
        return self.agent.load_session(self.session_manager, session_id)
```

### 启动入口：examples/ws_server.py

和 `basic_agent.py` 几乎一样，只是最后用 uvicorn 启动 WebSocket 服务：

```python
app = create_app(agent, tts=tts_provider, session_manager=session_manager)
uvicorn.run(app, host="0.0.0.0", port=8765)
```

### 依赖

```toml
# pyproject.toml
websocket = [
    "fastapi>=0.109.0",
    "websockets>=12.0",
    "uvicorn[standard]>=0.27.0",
]
```

**经验**：
1. **同步转异步**：用 `ThreadPoolExecutor` + `run_in_executor`，不改变原 Agent 代码
2. **事件拦截**：用 monkey-patch 是最小侵入的方式，不需要改 Registry
3. **连接管理**：ConnectionManager 维护 `conn_id → WebSocket` 映射，支持广播

---

## 7. 工具：轻量级 doctor 检查

### 需求

提供类似 `openclaw doctor` 的健康检查，帮助用户快速定位配置问题、API 连通性问题、依赖缺失等。

### 设计原则

参考 OpenClaw doctor 的思路，但保持精简：
- **非破坏性**：只读检查，不自动修改文件
- **模块化**：每个检查项是独立的 `Section`
- **优雅输出**：彩色 ANSI + 简洁表格，无噪音

### 实现

`doctor.py` 核心结构：

```python
class Status(Enum):
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"
    WARN = "warn"

@dataclass
class Check:
    name: str
    status: Status
    message: str = ""
    detail: str = ""

class Doctor:
    def check_config(self) -> Section: ...
    def check_provider_connectivity(self) -> Section: ...
    def check_tts(self) -> Section: ...
    def check_web_search(self) -> Section: ...
    def check_web_get(self) -> Section: ...
    def check_memory_dir(self) -> Section: ...
    def check_sessions_dir(self) -> Section: ...

    def run(self) -> bool: ...
    def print_report(self) -> None: ...
```

**检查项列表：**

| Section | Check | 说明 |
|---------|-------|------|
| Config | api_key | 是否配置 |
| Config | base_url | 是否有值 |
| Config | model | 是否有值 |
| Provider | connectivity | 实际发 /chat/completions 请求验证 |
| TTS | tts_api_key | 是否配置 |
| TTS | tts_connectivity | 发 TTS API stream 请求验证 |
| Web Search | baidu_api_key | 是否配置 |
| Web Search | baidu_search | 实际执行搜索 |
| Web Get | web_get | 抓取 baidu.com 测试 |
| Memory | memory_dir | 目录存在/可写 |
| Memory | embedding | 测试 embedder（依赖未装则 skip） |
| Sessions | sessions | 已有会话数量 |

**输出示例：**

```
─────────────────────────── xiaomei-brain doctor ──────────

  Config
    ✓  api_key   configured
    ✓  base_url  https://api.minimaxi.com/v1
    ✓  model     MiniMax-M2.7

  Provider
    ✓  connectivity  status 200

  TTS
    ✓  tts_api_key      configured
    ✓  tts_connectivity  status 200

  Web Search
    ✓  baidu_api_key  configured
    ✓  baidu_search   1 result(s)

  Web Get
    ✓  web_get  status 200, 500 chars

  Memory
    ✓  memory_dir  ~/.xiaomei-brain/memory (4 topics)
    ·  embedding   sentence_transformers not installed

  Sessions
    ✓  sessions  2 saved session(s)

  ───────────────────────────────────────────
  ✓ 12 passed

  ✓ All checks passed
```

### 关键代码：输出格式化

```python
SYMBOLS = {
    Status.OK:   "✓",
    Status.FAIL: "✗",
    Status.SKIP: "·",
    Status.WARN: "!",
}

def _color(self, status: Status, text: str) -> str:
    codes = {Status.OK: "32", Status.FAIL: "31",
              Status.SKIP: "90", Status.WARN: "33"}
    return f"\033[{codes[status]}m{text}\033[0m"
```

**集成到 basic_agent.py**：在交互循环中添加 `doctor` 命令，输入时直接运行检查。

**经验**：
- 彩色输出用 ANSI 转义码实现，不依赖外部库
- `SKIP` 用灰色 `.` 表示，中立状态，不算失败也不算通过
- verbose 模式下才显示 detail，避免信息过载

---

## 8. 开发经验总结

### 代码组织

1. **Provider + Tool 分离**：Provider 封装 API 调用逻辑，Tool 封装工具定义和参数校验。Provider 可以独立测试，Tool 依赖 Provider。

2. **模块级单例 Provider**：用全局变量 `_provider = None` + `set_*_provider()` 函数，工具延迟获取 Provider，避免循环导入。

3. **配置驱动**：所有能力默认关闭（`enabled: bool = False`），用户在 `config.yaml` 中按需启用。

### 重构技巧

- **全局搜索重命名**：用 `grep -r` 找到所有引用，一次性替换
- **代码复用**：OpenClaw 的设计模式（doctor 模块化、prompter 交互接口）可以借鉴但不模仿

### 调试技巧

- **网络问题**：用 `requests.post(..., stream=True)` 看原始响应
- **Python 缓存**：`sys.path.insert(0, 'src')` 强制重新加载模块
- **YAML 解析**：`yaml.safe_load()` 直接看解析后的 dict，找到重复 key 问题

### 健壮性

- **输入过滤**：`sanitize_text()` 清理控制字符和无效 Unicode
- **异常处理**：工具函数返回错误信息字符串，不抛异常给 Agent
- **超时控制**：所有 HTTP 请求设置 `timeout=15`
- **静默失败**：TTS 流式播放失败不中断主流程，只 log 错误

---

## 附录：运行命令

```bash
# WebSocket 服务
python examples/ws_server.py
# 或
uvicorn xiaomei_brain.ws:app --host 0.0.0.0 --port 8765

# Doctor 检查
python3 -c "import sys; sys.path.insert(0,'src'); from xiaomei_brain.doctor import Doctor; d=Doctor(); d.run(); d.print_report()"

# WebSocket 客户端测试（需要 websocat）
websocat ws://localhost:8765/ws
# 然后发送：
# {"type": "session_start", "session_id": null}
# {"type": "chat", "content": "你好", "session_id": "ws-xxx"}
```
