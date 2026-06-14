# WS CLI 重构设计（Hermes 对齐）

## 目标

将 `examples/ws_cli.py` 的展示和交互完全对齐 Hermes Agent CLI 的实现模式，实现专业的全屏 TUI 聊天终端。

## 当前状态

当前 `ws_cli.py`（~240 行）：
- asyncio + websockets + prompt_toolkit `PromptSession`
- 基本登录流程、流式输出、Event 同步
- 缺点：没有 Rich 渲染、没有状态栏、不区分对话浏览区和输入区、缺少多行输入

## 对齐 Hermes 的核心变更

### 1. prompt_toolkit 模式切换

**当前**：`PromptSession.prompt()` 在 thread executor 中运行

**目标**：`prompt_toolkit.Application(full_screen=False)` + `Layout(HSplit([...]))` + `TextArea`

这是最大的架构变更。Hermes 的 `full_screen=False` 模式让输出自然滚动在 widget 区上方，无需 Rich Live/Layout 做区域分割。

### 2. 输出通道：ChatConsole + _cprint

直接抄 Hermes 的两个核心函数：

- **`ChatConsole`**：Rich Console 适配器，渲染 Markdown 为 ANSI 字符串，通过 `_cprint` 输出
- **`_cprint`**：ANSI 文本通过 `prompt_toolkit.print_formatted_text(ANSI(text))` 输出，在 `patch_stdout` 上下文中正确处理

### 3. 流式输出：_stream_delta

借鉴 Hermes 的行缓冲模式：
- `text_chunk` 到达 → 追加到 buffer
- buffer 中遇到 `\n` → 拆分完整行 → Rich Markdown → ANSI → `_cprint`
- `text` 消息到达 → flush 剩余 buffer → 最终渲染

### 4. 输入：TextArea + KeyBindings

- `TextArea(height=Dimension(min=1, max=8, preferred=1), multiline=True)`
- Enter → 提交输入（发送 WS 消息）
- Alt+Enter (escape enter) → 插入换行
- 历史：FileHistory（`~/.cache/xiaomei-brain/ws_cli_history`）

### 5. 状态栏

参照 Hermes 的 `_get_status_bar_fragments`，显示：
- agent 名字、连接状态、消息计数、延迟、时间、快捷键提示

## 布局

```
终端窗口
┌────────────────────────────────────────┐
│  [历史消息区域 — 自然滚动]              │
│  [agent] 回复内容 (Rich Markdown)       │
│                                        │
│  ──────── spinner (thinking...) ─────── │
│  ──────── status_bar ───────────────── │
│  ──────── input_rule_top ───────────── │
│  [user]> _                             │
│  ──────── input_rule_bot ───────────── │
│  ──────── completions_menu ─────────── │
└────────────────────────────────────────┘
```

`full_screen=False` + `erase_when_done=True` 确保退出时不留下 chrome 残留。

## 数据流

```
WebSocket recv (asyncio task on Application event loop)
  │
  ├─ text_chunk → _stream_delta() → 行缓冲 → _cprint(ANSI)
  │
  ├─ text → _flush_stream() → _cprint(ANSI) → response_done.set()
  │
  └─ error → _cprint(error) → response_done.set()

TextArea Enter handler:
  1. 取 text, 检查 /quit 等命令
  2. response_done.clear()
  3. ws.send(chat message)
  4. await response_done.wait(timeout=120)
  5. app.invalidate()
```

关键：WebSocket 的 asyncio recv task 和 prompt_toolkit Application 的事件循环是同一个，无需 thread executor。

## 核心组件清单

| 组件 | 来源 | 说明 |
|------|------|------|
| `ChatConsole` | 抄 Hermes | Rich → ANSI → _cprint |
| `_cprint` | 抄 Hermes | ANSI → prompt_toolkit print_formatted_text |
| `_stream_delta` | 借鉴 Hermes | 行缓冲流式渲染 |
| `TextArea` | 同 Hermes | 多行输入控件 |
| `KeyBindings` | 同 Hermes | Enter/Alt+Enter/Ctrl+C 处理 |
| `Layout(HSplit([...]))` | 同 Hermes | widget 布局 |
| `status_bar` | 同 Hermes | ConditionalContainer |
| `_login()` | 保持现有 | 登录流程不变 |

## 不做（简化项 vs Hermes）

- Hermes 的交互式 modal（clarify/sudo/approval/secret/model_picker）— 不需要
- Hermes 的 agent/skills/tools 系统 — WS CLI 只是客户端
- Hermes 的 voice mode — 不需要
- Hermes 的 skin/theme 系统 — 硬编码配色
- Hermes 的 background tasks / goal continuation — 不需要
- `StreamingMarkdownRenderer`（470行）— 用 Rich 的 `Markdown` 替代
- `SlashCommandCompleter` — 只支持 `/quit` 不需要补全

## 依赖

- `rich` 13.7.1（已安装）
- `prompt_toolkit` 3.0.52（已安装）
- `websockets`（已安装）

## 文件变更

- `examples/ws_cli.py` — 从 ~240 行完全重写到 ~500 行
- 服务端：不变
