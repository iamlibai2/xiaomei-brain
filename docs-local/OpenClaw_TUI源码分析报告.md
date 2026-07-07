# OpenClaw TUI 源码分析报告

## 1. 文件结构（29个源文件）

```
src/tui/
├── tui.ts                    # 主入口，场景图构建，生命周期
├── tui-types.ts              # 类型定义
├── tui-event-handlers.ts     # Gateway 事件分发
├── tui-command-handlers.ts   # 斜杠命令、选择器UI、发送逻辑
├── tui-session-actions.ts    # 会话生命周期
├── tui-stream-assembler.ts   # 增量LLM输出组装
├── tui-formatters.ts         # 文本清洗、token格式化
├── tui-submit.ts             # 编辑器提交、粘贴合并
├── tui-overlays.ts           # 覆盖层管理
├── tui-local-shell.ts        # ! 前缀本地shell
├── tui-waiting.ts            # 等待动画
├── tui-status-summary.ts     # Gateway 状态格式化
├── osc8-hyperlinks.ts        # OSC 8 终端超链接
├── commands.ts               # 斜杠命令注册+自动补全
├── gateway-chat.ts           # Gateway WebSocket 客户端
├── theme/
│   ├── theme.ts              # 双调色板（自动明/暗检测）
│   └── syntax-theme.ts       # 代码语法高亮
└── components/
    ├── chat-log.ts           # 核心：消息容器，生命周期管理
    ├── assistant-message.ts  # 助手消息（HyperlinkMarkdown）
    ├── user-message.ts       # 用户消息
    ├── markdown-message.ts   # Markdown消息基类
    ├── tool-execution.ts     # 工具执行卡片（3态）
    ├── hyperlink-markdown.ts # OSC 8 终端超链接
    ├── btw-inline-message.ts # BTW 侧结果展示
    ├── custom-editor.ts      # 快捷键编辑器
    ├── selectors.ts          # 选择列表工厂
    ├── filterable-select-list.ts # 可过滤选择列表
    ├── searchable-select-list.ts # 可搜索选择列表
    └── fuzzy-filter.ts       # 模糊过滤
```

UI框架：**`@mariozechner/pi-tui`** — 保留模式组件树，渲染到 ProcessTerminal（raw mode 终端）。

## 2. 组件树架构（保留模式）

```
TUI (root)
  Container (root)
    Text (header)                  # openclaw tui - url - agent - session
    ChatLog                        # 滚动聊天历史
    Container (statusContainer)    # 动态: idle=Text / busy=Loader(spinner)
    Text (footer)                  # agent | session | model | tokens | thinking | verbose
    CustomEditor                   # 输入编辑器
```

**核心理念：保留模式 UI**。组件树构建一次，原地突变（mutate in place），按需重新渲染。不是每次重绘整棵树。

## 3. ChatLog 消息生命周期（最关键的设计）

`ChatLog` 内部维护三个 Map 追踪动态组件：

```
Map<runId, AssistantMessageComponent>     # 流式消息追踪
Map<toolCallId, ToolExecutionComponent>   # 工具卡片追踪
BtwInlineMessage                          # BTW 侧结果（单例）
```

**生命周期操作：**

| 方法 | 行为 |
|------|------|
| `addSystem(text)` | 追加 `Spacer(1)` + styled `Text` |
| `addUser(text)` | 追加 `UserMessageComponent` |
| `startAssistant(text, runId)` | 创建或复用流式组件 |
| `updateAssistant(text, runId)` | 原地更新文本（按 runId 查找） |
| `finalizeAssistant(text, runId)` | 设置最终文本，从 streaming Map 移除 |
| `dropAssistant(runId)` | 移除组件（用于空输出） |
| `startTool(toolCallId, ...)` | 创建 pending 态卡片 |
| `updateTool(toolCallId, result)` | pending → success/error 状态转换 |

**溢出剪枝**：最多 180 个子组件，超出时移除最旧的。

**组件层级按消息类型：**
- System: `Spacer(1)` + `Text(theme.system(text), 1, 0)`
- User: `UserMessageComponent` = `MarkdownMessageComponent` + `theme.userBg` / `theme.userText`
- Assistant: `AssistantMessageComponent` = Container + `HyperlinkMarkdown`
- Tool: `Spacer(1)` + `Box` (pending/success/error 背景) → `Text(header)`, `Text(args)`, `Markdown(output)`
- BTW: Container(`BTW: <question>`) + 可选的错误文本 + `AssistantMessageComponent`

## 4. StreamAssembler

**核心数据结构：**
```
Map<runId, { thinkingBlocks, contentBlocks, finalText }>
```

**处理流程：**
1. Delta 摄入 → thinking/content block 分离
2. 边界 drop 检测：最终 full content 是流式子集时，保留流式版本（避免视觉跳动）
3. Finalize 回退链：最终组合文本 → 流式文本 → 错误格式 → `"(no output)"`

这个设计解决了：流式输出与最终消息之间的不一致（某些模型 provider 的 final content 不包含流式部分）、thinking 与 content 的分离追踪。

## 5. Tool Execution 三态卡片

```typescript
class ToolExecutionComponent {
  state: "pending" | "success" | "error"
  // Box background 随 state 变化
}
```

| 状态 | 背景色 | 图标 | 说明 |
|------|--------|------|------|
| pending（运行中） | `#1F2A2F`（深蓝灰） | `⋯` | 显示 tool name + args |
| success（完成） | `#1E2D23`（深绿） | `✓` | 显示完整 header + result |
| error（失败） | `#2F1F1F`（深红） | `✗` | 显示 header + 错误 |

**全局折叠控制：** `Ctrl+O` 切换 `toolsExpanded`，折叠时限 12 行输出。

**内容提取：** 从 `result.content[]` 提取 `text` 类型（清洗后渲染）、`image` 类型（替换为 `[image/mime Nkb (omitted)]`）。

## 6. Footer 两层设计

### Footer（固定底部）
管道分隔显示，仅显示非默认值：

```
agent <name> | session <key> | provider/model | think <level> | fast | verbose | tokens <used>/<max> (<pct>%)
```

### Status Container（动态）
根据状态切换渲染：

- **idle**: 普通 Text — `connectionStatus | activityStatus`
- **busy**: Loader(spinner) + 动画文字
  - `sending` / `streaming` / `running`: 彩色 spinner + 经过时间 + 连接状态（1s 刷新）
  - `waiting`: shimmer 动画文字 + 俏皮短语（120ms 刷新，10 tick 循环）

**活动状态机：**
```
idle → sending → waiting → streaming → idle
  ↑       ↓          ↓          ↓
  └── aborted ───────┘          |
  └── error ←───────────────────┘
```

## 7. 色彩系统：双调色板 + 自动检测

优先级链决定明/暗模式：
1. `OPENCLAW_THEME` 环境变量（`light` / `dark`）
2. `COLORFGBG` 终端变量 → 解析 256 色 → 对比度测试
3. 默认暗色

**关键设计：** 助手文本用终端默认前景色（`text => text`），用户消息用强制颜色。这意味着助手消息跟随用户终端主题。

**完整调色板（暗色模式）：**

| Token | 颜色 | 用途 |
|-------|------|------|
| `text` | `#E8E3D5` | 默认文本 |
| `dim` | `#7B7F87` | 辅助文本 |
| `accent` | `#F6C453`（金色） | 标题、强调 |
| `userBg` | `#2B2F36` | 用户消息背景 |
| `userText` | `#F3EEE0` | 用户消息文本 |
| `systemText` | `#9BA3B2` | 系统消息 |
| `toolPendingBg` | `#1F2A2F` | 工具运行中背景 |
| `toolSuccessBg` | `#1E2D23` | 工具成功背景 |
| `toolErrorBg` | `#2F1F1F` | 工具失败背景 |
| `error` | `#F97066` | 错误消息 |
| `success` | `#7DD3A5` | 成功消息 |
| `link` | `#7DD3A5` | 超链接 |
| `code` | `#F0C987` | 内联代码 |
| `quote` | `#8CC8FF` | 引用块 |

**语法高亮：** 两套 `HighlightTheme`（VS Code Dark+ / Light+），通过 `cli-highlight` 渲染代码块。

**选择列表主题：** 多个组合主题 —— `selectListTheme`（基础）、`searchableSelectListTheme`（+搜索匹配高亮）、`filterableSelectListTheme`（+过滤标签）。

## 8. 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送 |
| `Esc` | 中断当前生成 |
| `Ctrl+C` | 三级：清空输入 → 警告 → 退出 |
| `Ctrl+D` | 退出 |
| `Ctrl+O` | 切换工具展开/折叠 |
| `Ctrl+L` | 选择模型 |
| `Ctrl+G` | 选择 Agent |
| `Ctrl+P` | 选择会话 |
| `Ctrl+T` | 切换 thinking 显示 |
| `Alt+Enter` | 插入换行 |
| `Up/Down` | 历史导航 |
| `Ctrl+N/P` | 自动补全导航 |

**输入预处理：** 全局 input listener 在 8ms 窗口内去重 Backspace（修复某些终端双击删除问题）。

## 9. 命令处理三路分发

```
输入文本
  ├── ! 开头 → 本地 shell 执行
  ├── / 开头 → 斜杠命令处理
  └── 其他 → 发送聊天消息
```

**粘贴突发合并：** `createSubmitBurstCoalescer` 在 50ms 窗口内合并多次提交为单个多行消息（解决 Git Bash/iTerm2 等终端的多行粘贴问题）。

## 10. 关键设计模式

### 10.1 工厂函数 + 显式依赖注入
所有子系统通过工厂函数创建，接受显式依赖对象：
```typescript
createCommandHandlers(context)  → { handleCommand, sendMessage, ... }
createEventHandlers(context)   → { handleChatEvent, ... }
createSessionActions(context)  → { refreshAgents, loadHistory, ... }
```
此模式提供：显式依赖追踪、易测试性、清晰接口。

### 10.2 时间戳防陈旧
`applySessionInfo()` 检查 `updatedAt` 时间戳，防止旧数据覆盖新数据。Session 切换时清除 `updatedAt` 为 `null`。

### 10.3 串行化刷新
```typescript
refreshSessionInfoPromise = refreshSessionInfoPromise.then(
  runRefreshSessionInfo,
  runRefreshSessionInfo,  // rejection 也用同一处理器
);
```
并发调用自动串行化，失败不中断链。

### 10.4 Session 隔离
`/new` 创建 session 时用 `tui-{UUID}` 隔离，防止广播到其他连接的 TUI 客户端。

### 10.5 Local Run ID 追踪
区分本地发起和外部触发的 runs，历史重载时根据来源决定是否立即刷新。

## 11. 文本清洗管道

`sanitizeRenderableText()` 按顺序执行：
1. 剥离现有 ANSI 转义码
2. 移除控制字符（保留 tab/换行/CR）
3. 二进执行替换（≥12 个替换字符且覆盖 ≥50% 行的 → `[binary data omitted]`）
4. 长 token 分割（≥33 字符的非 URL/路径 → 空格分隔，URL/路径/凭证保留）
5. RTL 隔离（Unicode bidi isolation 包裹含 RTL 脚本的行）

## 12. OSC 8 终端超链接

`HyperlinkMarkdown` 组件在 Markdown 渲染后重新匹配 URL 并插入 OSC 8 控制序列，支持：
- `[text](url)` 格式和裸 URL
- 跨行 URL 拆分处理（pi-tui 自动换行导致的 URL 断开）
- ANSI SGR 序列穿透（在颜色代码中正确插入超链接边界）

## 对比：我们 TUI vs OpenClaw TUI

| 维度 | OpenClaw | 我们当前 tui.py |
|------|----------|-----------------|
| UI框架 | pi-tui (保留模式) | prompt_toolkit (全屏应用) |
| 消息渲染 | Component 树，原地突变 | `print()` + `_cprint()` ANSI 输出 |
| 流式追踪 | `Map<runId>` + StreamAssembler | `_stream_buf` 行缓冲 |
| Tool 卡片 | 三态 Box（pending/success/error）| 无 |
| Footer | 两层：固定 footer + 动态 status | 单层状态栏 |
| 快捷键 | 9 个功能键 | 6 个基础键 |
| 覆盖层 | Overlay 系统（选择器/确认框）| 无 |
| 主题 | 双调色板 + 自动明暗检测 | Catppuccin Mocha 暗色 |
| 超链接 | OSC 8 终端超链接 | 无 |
| 命令分发 | `!` / `/` / 聊天 三路 | `/` 前缀，四层分发 |
| 会话管理 | 搜索/筛选选择器 | `/sessions` + `/switch` 命令 |
| 文本清洗 | 5 步管道 | 无 |
| 粘贴处理 | 50ms 窗口合并 | `select.select()` 多行检测 |

---

分析日期：2026-06-15
