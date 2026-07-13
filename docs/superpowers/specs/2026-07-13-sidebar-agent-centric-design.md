# Sidebar Agent 优先设计

## 1. 背景与动机

### 1.1 项目定位

xiaomei-brain 是多 Agent 大脑框架。每个 Agent 是独立进程——拥有自己的身份、记忆、欲望、目标。桌面端是同时连接多个 Agent 大脑的窗口，所有 Agent 保持常连接（连接池），切换 = 切换显示的消息源，不断连。

### 1.2 当前 Sidebar 布局

```
SidebarTopbar (logo + 操作按钮)
─────────────────────────────
NewTaskButton
─────────────────────────────
NavTabs (助理/项目/专家/自动化/更多)  ← 无功能，纯视觉
─────────────────────────────
Agent List Header + Add Button
Agent Items (状态点 + 未读徽章)
─────────────────────────────
CollapsibleSection: 任务
CollapsibleSection: 空间
─────────────────────────────
Footer (用户头像)
```

### 1.3 问题

1. **NavTabs 没有功能** — 点击只更新 `activeNav` 到 Store，没有任何 UI 组件读取它来决定显示什么。它是从 WorkBuddy 抄来的视觉占位
2. **NavTabs 和 Agent 列表的关系模糊** — 谁是谁的上级？Agent 列表一直显示，不受 Tab 切换影响
3. **层级过多（7层）** — 信息密度大但实际可用信息少
4. **HomePage 已有 SceneTabs**（工作/编码/设计）— 两套 Tab 并存，功能定位重复

### 1.4 核心洞察

侧栏的职责是**上下文切换**（"我在跟哪个大脑对话？"），主内容区的职责是**功能操作**（"我在做什么类型的任务？"）。在侧栏里同时塞上下文切换和功能导航，导致两者的定位都模糊。

---

## 2. 设计方案

### 2.1 原则

| 原则 | 说明 |
|------|------|
| 单一职责 | 侧栏 = Agent 上下文切换 + 快速入口。功能导航放到主内容区 |
| YAGNI | NavTabs 无功能 → 移除。需要时明确目的再加 |
| Agent 优先 | 所有侧栏内容以选中的 Agent 为上下文 |
| 扁平化 | 5层（Topbar → NewTask → Agent List → 会话/空间 → Footer） |

### 2.2 目标布局

```
┌──────────────────────────────┐
│  🤖 xiaomei-brain  [🔍][🔄][>_]│  ← SidebarTopbar
├──────────────────────────────┤
│  [+ 新建任务]                  │  ← NewTaskButton → 清空当前 Agent 消息
├──────────────────────────────┤
│  Agents (3)            [+]   │  ← agent-list-header
│  ┌──────────────────────────┐│
│  │ 🟢 小美                   ││  ← 当前选中 = 高亮背景
│  │    localhost:19766       ││
│  │                          ││
│  │ 🟢 小明           [2]    ││  ← 2条未读
│  │    localhost:19767       ││
│  │                          ││
│  │ 🔴 法小助                 ││  ← 断连
│  │    192.168.1.10         ││
│  └──────────────────────────┘│
├──────────────────────────────┤
│  ▼ 任务 (1)                  │  ← 已连接 → 显示当前会话名称
│    小美 · 当前会话            │     未连接 → 显示"暂无任务"
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │
│  ▼ 空间 (0)                  │  ← 后续迭代实现
│    暂无                       │
├──────────────────────────────┤
│  👤 用户                       │  ← Footer
└──────────────────────────────┘
```

### 2.3 NavTabs 去留

**一期：移除。** 从 `ConversationList.tsx` 中删除 `<NavTabs>` 渲染，保留 `NavTabs` 组件文件不动（后续可能用于主内容区功能导航）。

**后续方向（不在本次范围）：**
- 如果未来需要"助理 / 项目 / 专家"等功能切换，在主内容区顶部加 Tab 栏
- NavTabs 组件可能复用到那里，但交互逻辑完全不同——点击会切换主区域内容，不影响侧栏

### 2.4 折叠模式

折叠模式不变：Agent 首字母圆形按钮 + 添加按钮 + Footer 头像。

---

## 3. 组件结构

```
ConversationList (容器)
├── SidebarTopbar
│   ├── 展开：Logo + 版本号 + 刷新/搜索/终端/折叠按钮
│   └── 折叠：展开按钮
├── [展开模式]
│   ├── NewTaskButton          ← onClick → newTask()
│   ├── AgentListHeader        ← "Agents (N)" + [+] 按钮
│   ├── AddAgentForm           ← 条件渲染，showAddForm
│   ├── AgentItem[]            ← 每个 Agent 的卡片
│   │   ├── AgentAvatar        ← 首字母
│   │   ├── AgentInfo          ← name + host:port
│   │   ├── StatusDot          ← green/yellow/gray
│   │   ├── UnreadBadge        ← 条件渲染，unread > 0
│   │   ├── NewConvBtn         ← hover 可见
│   │   └── RemoveBtn          ← hover 可见
│   ├── CollapsibleSection[任务]      ← 行为不变，显示当前 Agent 会话
│   ├── CollapsibleSection[空间]      ← 行为不变
│   └── SidebarFooter
├── [折叠模式]
│   ├── AgentAvatarBtn[]       ← 首字母按钮
│   ├── AddBtn
│   └── FooterAvatar
```

### 3.1 组件改动清单

| 文件 | 改动 |
|------|------|
| `ConversationList.tsx` | 移除 `<NavTabs>` 渲染行（1行）；移除 `NavTabs`/`NavIconNames` import；移除 `activeNav`/`setActiveNav` store selector；移除 `navItems` 数组 |
| `NavTabs.tsx` | **不改动**，保留文件 |
| 其他文件 | **不改动** |

---

## 4. 交互行为

### 4.1 Agent 切换

```
click AgentItem
  → switchAgent(agentId)
    → set activeAgentId = agentId
    → clear unreadByAgent[agentId] = 0
    → 如果未连接 → connectToAgent(agentId)
  → HomePage 从 messagesByAgent[activeAgentId] 读取消息
  → 消息区域刷新，显示该 Agent 的历史消息
```

- 不断开任何 Agent 连接
- 切换无延迟（消息在内存中）
- 后台 Agent 继续收发消息

### 4.2 新建任务

```
click NewTaskButton
  → newTask()
    → 清空 messagesByAgent[activeAgentId] = []
  → HomePage 回到空状态（显示 HomeHeader + SceneTabs + GrowthBuddy）
```

### 4.3 添加 Agent

```
click [+] in header
  → showAddForm = true
  → 表单出现（host / port / token）
  → 提交
    → addAgent(host, port, token)
      → 检查是否已存在（去重）
      → push 到 agents[]
      → 自动 connectToAgent(agentId)
  → showAddForm = false，表单关闭
```

### 4.4 删除 Agent

```
hover AgentItem → 显示 [x] 按钮
click [x]
  → removeAgent(agentId)
    → disconnect agent WS
    → 删除 connectionByAgent[agentId]
    → 删除 messagesByAgent[agentId]
    → 清理 _streamingByAgent[agentId]
    → agent 从 agents[] 移除
    → 如果删除的是 activeAgentId → 切到第一个剩余 Agent
    → persist 到 localStorage
```

### 4.5 未读消息

```
后台 Agent (agentId !== activeAgentId) 收到 session.message
  → unreadByAgent[agentId] += 1
  → AgentItem 显示数字徽章（>99 显示 "99+"）

用户切换到该 Agent
  → unreadByAgent[agentId] = 0
  → 徽章消失
```

### 4.6 折叠/展开

```
click 折叠按钮
  → collapsed = true
  → 显示：Agent 头像按钮 + 添加按钮 + Footer 头像
  → 宽度 260px → 48px

click 展开按钮
  → collapsed = false
  → 显示完整布局
  → 宽度 48px → 260px
```

行为不变。

---

## 5. 数据流

```
                    ┌── IPC ──┐
                    │         │
    Main Process    │  渲染进程
    ────────────────┼─────────────
    Map<string,     │  CoreStore (Zustand + Immer + Persist)
    GatewayClient>  │  ┌──────────────────────┐
                    │  │ agents[]             │ ← localStorage 持久化
                    │  │ activeAgentId        │ ← localStorage 持久化
                    │  │ userId               │ ← localStorage 持久化
                    │  │ connectionByAgent{}  │ ← 内存，运行态
                    │  │ messagesByAgent{}    │ ← 内存，运行态
                    │  │ unreadByAgent{}      │ ← 内存，运行态
                    │  │ sending              │
                    │  └──────────────────────┘
                    │         │
                    │    ConversationList  ← 读取 agents, activeAgentId,
                    │                        connectionByAgent, unreadByAgent
                    │         │
                    │    HomePage ← 读取 messagesByAgent[activeAgentId]
```

---

## 6. 不变的部分

以下文件和功能完全不变：

| 文件/功能 | 说明 |
|-----------|------|
| `main/ipc-handlers.ts` | 连接池架构不动 |
| `main/gateway-client.ts` | 单连接客户端不动 |
| `renderer/store/core.ts` | Store 结构不动 |
| `renderer/types.ts` | 类型定义不动 |
| `renderer/App.tsx` | 启动逻辑不动 |
| `ConnectPage.tsx` | 首次连接页不动 |
| `HomePage.tsx` | 消息显示不动 |
| `MainShell.tsx` | 布局容器不动 |
| `MenuBar.tsx` | 菜单栏不动 |
| `SidebarTopbar.tsx` | 顶栏不动 |
| `NewTaskButton.tsx` | 按钮不动 |
| `CollapsibleSection.tsx` | 折叠区域不动 |
| `SidebarFooter.tsx` | 底部不动 |
| `sidebar.css` | 现有样式不动 |
| i18n 文件 | 现有 key 不动 |

---

## 7. 实现范围

### 改 1 个文件，删 7 行

**`ConversationList.tsx`：**

移除：
- `import { NavTabs, NavIconNames } from "./NavTabs"` (1行 import)
- `const activeNav = useCoreStore((s) => s.activeNav)` (1行 store selector)
- `const setActiveNav = useCoreStore((s) => s.setActiveNav)` (1行 store selector)
- `const navItems = [...]` (6行数组定义)
- `<NavTabs items={navItems} onSelect={setActiveNav} />` (1行渲染)

Store 中 `activeNav` 和 `setActiveNav` 保留不动（可能后续用）。

### 后续迭代（不在本次范围）

- 空间列表真实数据（需要后端 API）
- 任务列表真实数据（多会话支持）
- Agent 重命名
- Agent 右键菜单
- 功能 Tab 迁移到主内容区顶部

---

## 8. 验证清单

1. ~~侧栏渲染完整，无报错~~（改 7 行，验证无语法错误即可）
2. ~~Agent 列表正常显示，状态点正确~~（已有功能，不改变）
3. ~~未读徽章正常工作~~（已有功能，不改变）
4. ~~折叠/展开正常~~（已有功能，不改变）
5. ~~新建任务按钮正常~~（已有功能，不改变）
6. ~~NavTabs 不再出现在侧栏中~~
