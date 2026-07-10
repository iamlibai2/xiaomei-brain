# xiaomei-brain Desktop — WorkBuddy 首页 UI 全仿设计

> 日期: 2026-07-10
> 状态: 设计确认，待实现
> 参考: WorkBuddy v5.2.5 桌面客户端首页

## 1. 目标

像素级全仿 WorkBuddy 桌面端首页 UI，先仿 UI 再接功能。提取 WorkBuddy 设计 token，重写干净 CSS，不搬运 WorkBuddy 全部 CSS 文件。

xiaomei-brain 的 Gateway WebSocket JSON-RPC 后端不变，仅重写 Renderer 层 UI。

## 2. 三层整体架构

```
┌─────────────────────────────────────────────────────────┐
│ 编辑(E)  窗口(W)  帮助(H)                    [─] [□] [✕] │ 顶部菜单栏 30px (Win/Linux)
├──────────┬──────────────────────────────────────────────┤
│ WorkBuddy│                              [做任务赢积分 >]│
│ v5.2.5   │                                              │
│ [🔄][🔍][≡]│                                            │
│          │  WorkBuddy                                   │
│ [+新建任务]│  你的职场超能力                              │
│          │                                              │
│ 助理     │  [日常办公] [@代码开发] [@设计创意]           │
│ 项目     │                                              │
│ 专家·技能│  [文档处理] [金融服务] [数据分析] [更多]      │
│ 自动化   │                                              │
│ 更多     │  ┌──────────────────────────────────────┐   │
│          │  │ 今天帮你做些什么？@ 引用 / 调用技能  │   │
│ 任务 (3)▾│  │                                      │   │
│  任务1 3天│  │ [+]                  [自动▾] [🎤] [➤]│   │
│  任务2   │  └──────────────────────────────────────┘   │
│ 空间 (1)▾│  [📍选择工作空间▾]         [🛡默认权限▾]    │
│  空间1   │                                              │
│          │                                              │
│ [头像]李白│                                              │
├──────────┴──────────────────────────────────────────────┤
```

## 3. 设计 Token 系统

从 WorkBuddy `cb-bridge-BQMqrgRE.css` 提取完整 `--wb-*` token，写入 `renderer/styles/tokens.css`。

### 3.1 颜色（亮色主题）

| Token | 值 | 用途 |
|---|---|---|
| `--wb-palette-brand-8` | `#00C29A` | 品牌主色（薄荷绿） |
| `--wb-palette-brand-7` | `#40D1B3` | 品牌悬停 |
| `--wb-palette-brand-9` | `#009273` | 品牌激活 |
| `--wb-palette-brand-1` | `#DFF7F2` | 品牌浅底 |
| `--wb-palette-gray-1` | `#FAFAFA` | 最浅灰 |
| `--wb-palette-gray-2` | `#F7F7F7` | 次浅灰 |
| `--wb-palette-gray-3` | `#F2F2F2` | 主背景灰 |
| `--wb-palette-gray-4` | `#EBEBEB` | 次背景灰 |
| `--wb-palette-gray-5` | `#E6E6E6` | 边框灰 |
| `--wb-palette-white-100` | `#FFFFFF` | 面板/卡片 |
| `--wb-palette-black-90` | `rgba(0,0,0,0.9)` | 主文字 |
| `--wb-palette-black-70` | `rgba(0,0,0,0.7)` | 次文字 |
| `--wb-palette-black-50` | `rgba(0,0,0,0.5)` | 弱文字 |
| `--wb-palette-black-30` | `rgba(0,0,0,0.3)` | 禁用文字 |
| `--wb-palette-black-100` | `#000000` | 纯黑 |

### 3.2 语义别名

```css
--wb-color-text-primary: var(--wb-palette-black-90);
--wb-color-text-secondary: var(--wb-palette-black-70);
--wb-color-text-tertiary: var(--wb-palette-black-50);
--wb-color-text-disabled: var(--wb-palette-black-30);
--wb-bg-primary: var(--wb-palette-white-100);
--wb-bg-secondary: var(--wb-palette-gray-2);
--wb-bg-tertiary: var(--wb-palette-gray-4);
--wb-bg-hover: color-mix(in srgb, var(--wb-palette-black-100) 5%, transparent);
--wb-bg-active: color-mix(in srgb, var(--wb-palette-black-100) 8%, transparent);
--wb-border-default: color-mix(in srgb, var(--wb-palette-black-100) 8%, transparent);
--wb-border-subtle: var(--wb-palette-gray-3);
--wb-sidebar-bg: var(--wb-palette-gray-3);
--wb-brand-primary: var(--wb-palette-brand-8);
```

### 3.3 暗色主题

完整暗色 token 也在 `tokens.css` 中定义，通过 `body[data-theme="dark"]` 或 `prefers-color-scheme: dark` 切换。暗色下品牌色提亮，背景色取深灰。

### 3.4 字体

```css
--wb-font-family: "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--wb-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
--wb-font-display-size: 32px;    /* 显示标题 */
--wb-font-display-line-height: 40px;
--wb-font-h1-size: 24px;         /* 一级标题 */
--wb-font-h1-line-height: 32px;
--wb-font-body-size: 14px;       /* 正文 */
--wb-font-body-line-height: 22px;
--wb-font-caption-size: 12px;    /* 说明文字 */
--wb-font-caption-line-height: 18px;
```

首页大标题特殊规格：36px / 48px line-height / font-weight 600。

### 3.5 间距

```css
--wb-spacing-0: 0;
--wb-spacing-1: 2px;
--wb-spacing-2: 4px;
--wb-spacing-3: 8px;
--wb-spacing-4: 12px;
--wb-spacing-5: 16px;
--wb-spacing-6: 20px;
--wb-spacing-7: 24px;
--wb-spacing-8: 32px;
--wb-spacing-9: 40px;
--wb-spacing-10: 48px;
--wb-spacing-12: 64px;
```

### 3.6 圆角

```css
--wb-radius-xs: 2px;
--wb-radius-sm: 4px;
--wb-radius-md: 6px;
--wb-radius-lg: 8px;
--wb-radius-xl: 12px;
--wb-radius-2xl: 16px;
--wb-radius-full: 9999px;
```

### 3.7 阴影

```css
--wb-shadow-sm: 0 1px 2px rgba(0,0,0,0.08);
--wb-shadow-md: 0 2px 8px rgba(0,0,0,0.12);
--wb-shadow-lg: 0 4px 16px rgba(0,0,0,0.16);
--wb-shadow-xl: 0 8px 32px rgba(0,0,0,0.20);
```

## 4. 顶部菜单栏（MenuBar）

### 4.1 平台规则

- **Mac**：不显示自定义菜单栏（`display: none`），用原生红绿灯按钮（`titleBarStyle: "hiddenInset"`）
- **Windows**：`frame: false` + `titleBarOverlay: { height: 30, color: "#00000000", symbolColor: "#ffffff" }`，原生窗口控件叠加在菜单栏右侧
- **Linux**：`frame: false`，无原生窗口控件

### 4.2 结构（Windows/Linux）

```
┌─────────────────────────────────────────────────────────┐
│ [Logo] xiaomei-brain  编辑(E) 窗口(W) 帮助(H)  [─][□][✕]│ 30px
└─────────────────────────────────────────────────────────┘
```

- 高度 **30px**，`-webkit-app-region: drag`（整个菜单栏可拖拽移动窗口）
- 菜单项和 Logo 区域：`-webkit-app-region: no-drag`（可点击）
- **左侧**：Logo 图标（18×18）+ "xiaomei-brain" 文字（12px, bold）
- **中间**：菜单项（编辑(E) / 窗口(W) / 帮助(H)），带下划线快捷键标记，点击弹出下拉菜单
- **右侧**：Windows 上为 `titleBarOverlay` 预留 `padding-right`（约 138px），Linux 无预留
- `#root` 设 `margin-top: 30px` + `height: calc(100% - 30px)`

### 4.3 菜单项

菜单项是 VS Code 风格 AgentMenubar：
- hover 时浅底色
- 点击弹出下拉菜单
- 编辑：撤销/重做/剪切/复制/粘贴/全选
- 窗口：重新加载/开发者工具/关闭
- 帮助：关于

### 4.4 Mac 适配

Mac 上菜单栏隐藏后，侧栏 topbar（56px）兼作拖拽区，`padding-left: 80px` 避让红绿灯。

## 5. 左侧导航栏（ConversationList）

### 5.1 容器

- 宽度 **260px**（展开态），可折叠为 **48px**（图标条）
- 背景 `--wb-sidebar-bg`（`#F2F2F2`）
- `flex-shrink: 0`，`flex-direction: column`，`height: 100%`
- `transition: width 0.25s ease-out`（折叠动画）

### 5.2 结构（从上到下）

#### 5.2.1 SidebarTopbar（56px）

```
┌──────────────────────────────────┐
│                    [🔄] [🔍] [≡] │  56px, drag region
└──────────────────────────────────┘
```

- 高度 56px，`-webkit-app-region: drag`
- Mac 上 `padding-left: 80px`（避让红绿灯）
- 右侧操作图标（32×32，8px 圆角，`-webkit-app-region: no-drag`）：
  - 刷新/新建按钮
  - 搜索按钮
  - 折叠侧栏按钮（三条横线图标）
- Windows 上 topbar 高度为 0（让位给 30px 菜单栏），操作图标绝对定位到右上角

#### 5.2.2 SidebarHeader（App 头部）

```
┌──────────────────────────────────┐
│ [icon] WorkBuddy          v5.2.5 │
└──────────────────────────────────┘
```

- Logo 图标（20×20，4px 圆角）+ "WorkBuddy" 文字（12px, bold）+ 版本号 badge（10px）
- Windows 上 Logo 纵向排列（图标在上，文字在下），`padding-right: 76px` 避让窗口控件
- `padding: 0 12px 16px 12px`

#### 5.2.3 NewTaskButton

```
┌──────────────────────────────────┐
│  + 新建任务                       │  圆角矩形, 浅灰底
└──────────────────────────────────┘
```

- `+` 图标 + "新建任务" 文字
- 浅灰背景（`--wb-bg-tertiary`），hover 加深
- 圆角 8px

#### 5.2.4 NavTabs（导航项列表）

每项 30px 高：
```
┌──────────────────────────────────┐
│ [icon] 助理                      │  30px
│ [icon] 项目                      │
│ [icon] 专家·技能·连接器           │
│ [icon] 自动化                    │
│ [icon] 更多                      │
└──────────────────────────────────┘
```

- 16px 线框图标 + 13px 文字
- `border-radius: 8px`，`padding: 4px 12px`，`gap: 8px`
- hover：`--wb-todo-menu-bg-hover` 浅底色
- active：更深底色
- 可能有红色圆点（未读标记，6px）

#### 5.2.5 TaskSection（任务历史，可折叠）

```
┌──────────────────────────────────┐
│ 任务 (3)                    ▾    │  section header 36px
├──────────────────────────────────┤
│  任务名称1               3天前   │  task item
│  任务名称2                昨天   │
│  任务名称3                        │
└──────────────────────────────────┘
```

- section header：可折叠，点击切换展开/收起
  - "任务 (3)" 文字（12px, 600 weight）+ 计数 + ▾ 箭头（折叠时旋转 -90deg）
  - 36px 高，`padding: 6px 0 6px 16px`，`margin: 0 12px`
- task item：
  - 左侧任务名 + 右侧时间（如"3天前"）
  - 第一条可能有绿色圆点（活跃/未读状态）
  - `padding: 6px 12px`，hover 浅底色
- 超过 5 条显示"查看更多 (N)"按钮

#### 5.2.6 SpaceSection（空间历史，可折叠）

结构同 TaskSection：
- "空间 (1)" + ▾
- 空间项：缩进排版，主标题 + 子标题

#### 5.2.7 SidebarFooter（用户区，固定底部）

```
┌──────────────────────────────────┐
│ [头像] 李白              [🔔] [⚙] │
└──────────────────────────────────┘
```

- `padding: 12px 16px 12px 12px`，`flex-shrink: 0`
- 圆形头像（32px，绿色边框）+ 昵称（13px）+ 通知铃铛图标 + 设置图标
- 头像可点击弹出用户菜单

### 5.3 折叠态（48px）

折叠为图标条时：
- 宽度 48px，只显示 Logo + 导航图标
- hover 时可展开回 260px

## 6. 右侧主工作区——首页（HomePage）

### 6.1 容器

- 纯白背景（`--wb-bg-primary`）
- `max-width: 800px`，`margin: 0 auto`（居中）
- `padding: 32px 24px 48px`
- `flex-direction: column`
- 可滚动（`overflow-y: auto`），隐藏滚动条

### 6.2 结构（从上到下）

#### 6.2.1 ActivityBanner（活动入口，右上角悬浮）

```
                                    ┌─────────────────────┐
                                    │ 📈 做任务赢积分好礼 >│  绿色胶囊
                                    └─────────────────────┘
```

- 绝对定位到首页右上角
- 绿色胶囊按钮（`--wb-palette-brand-8` 背景，白字）
- 折线箭头图标 + "做任务赢积分好礼 >" 文字
- 点击跳转活动页

#### 6.2.2 HomeHeader（大标题区）

```
WorkBuddy
你的职场超能力
```

- "WorkBuddy"：h1，36px，PingFang SC Semibold（font-weight 600），48px line-height
- "你的职场超能力"：p，同字体规格
- 两行紧贴（无 gap/margin），左对齐
- `min-height: 96px`
- 颜色：`--wb-color-text-primary`（亮色 `rgba(0,0,0,0.9)`）
- 副标题随 SceneTabs 选中模式变化：
  - 日常办公 → "你的职场超能力"
  - 代码开发 → "你的开发超能力"
  - 设计创意 → "你的设计超能力"

#### 6.2.3 SceneTabs（场景标签）

```
[日常办公]  [@代码开发]  [@设计创意]
```

- 三个胶囊按钮，水平排列
- 选中态：深色背景（`--wb-palette-black-100`）+ 白字
- 未选中：浅灰背景（`--wb-bg-tertiary`）+ 黑字 + 线框图标
- `border-radius: 8px`，`font-size: 13px`

#### 6.2.4 GrowthBuddy（宠物通知，右侧边缘）

```
                    ┌──────────────────────┐
                    │ 活动通知              │
                    │ Hy3正式发布...        │
                    │ [立即体验]        [X] │
                    └──────────────────────┘
                                            [🐱]
```

- 戴耳机的黑色小猫头像（绝对定位，右侧边缘）
- 旁边气泡通知（带指向性尾巴）
  - 绿色标题"活动通知"
  - 灰色说明文字
  - 白底黑字"立即体验"按钮
  - 右上角关闭 X 按钮

#### 6.2.5 HomeComposer（快捷功能 + 输入区）

**QuickActions（快捷功能 chips）**：
```
[📄文档处理] [💰金融服务] [📊数据分析及可视化] [更多]
```

- 水平排列的小胶囊按钮
- 12px 字体，线框图标在前
- `border-radius: 8px`，浅灰背景
- hover 上移 1px

**ChatInput（核心输入框）**：
```
┌──────────────────────────────────────────┐
│ 今天帮你做些什么？ @ 引用对话文件，/ 调用 │
│ 技能与指令                                │
│                                          │
│ [+]                    [自动▾] [🎤] [➤]  │
└──────────────────────────────────────────┘
```

- 大浅灰圆角矩形（`--wb-bg-secondary` 背景，`border-radius: 16px`）
- placeholder：灰色（`--wb-color-text-tertiary`），14px
- 左下角：`+` 附件按钮
- 右下角（输入区内部底部）：
  - `自动` 下拉菜单（带下拉箭头）
  - 麦克风图标（语音输入）
  - 发送按钮：圆形（32px），深灰/黑背景，白色纸飞机/箭头图标
- Enter 发送，Shift+Enter 换行
- 流式中显示「中断」按钮

#### 6.2.6 ContextBar（底部上下文设置栏）

```
┌──────────────────────────────────────────┐
│ [📍] 选择工作空间▾          [🛡] 默认权限▾│
└──────────────────────────────────────────┘
```

- 浅灰圆角长条（`--wb-bg-secondary`，`border-radius: 16px`）
- 左侧：图标 + "选择工作空间" + 下拉箭头
- 右侧：盾牌图标 + "默认权限" + 下拉箭头

### 6.3 窗口窄屏适配

`@media (max-width: 640px)`：
- padding 缩小为 `24px 20px 32px`
- 标题字号缩小为 26px / 22px

## 7. 组件架构 & 文件结构

### 7.1 组件树

```
App
├── MenuBar                    (Windows/Linux 顶部菜单栏, 30px)
├── ConnectPage                (连接 Gateway 页, 保留改造)
└── MainShell                  (主外壳: 侧栏 + 主内容)
    ├── ConversationList       (左侧导航栏)
    │   ├── SidebarTopbar      (56px, drag, 搜索/折叠图标)
    │   ├── SidebarHeader      (Logo + 版本号)
    │   ├── NewTaskButton      (+ 新建任务)
    │   ├── NavTabs            (助理/项目/专家/自动化/更多)
    │   ├── TaskSection        (任务历史, 可折叠)
    │   │   ├── SectionHeader  ("任务 (3)" + ▾)
    │   │   └── TaskItem       (任务名 + 时间)
    │   ├── SpaceSection       (空间历史, 可折叠)
    │   │   ├── SectionHeader  ("空间 (1)" + ▾)
    │   │   └── SpaceItem      (主标题 + 子标题)
    │   └── SidebarFooter      (用户头像 + 昵称 + 通知/设置)
    └── MainContent            (右侧主区, flex:1)
        └── HomePage           (wb-home-page, 居中 800px)
            ├── ActivityBanner (右上角悬浮 "做任务赢积分 >")
            ├── HomeHeader     ("WorkBuddy" + "你的职场超能力")
            ├── SceneTabs      (日常办公/代码开发/设计创意)
            ├── GrowthBuddy    (猫头像 + 通知气泡, 绝对定位)
            ├── HomeComposer   (快捷chips + ChatInput)
            │   ├── QuickActions (文档处理/金融服务/...)
            │   └── ChatInput    (大输入框 + 底部上下文栏)
            └── PracticeCases  (练习案例, 可选, 首期不做)
```

### 7.2 文件结构

```
renderer/
├── App.tsx                    (改造: MenuBar + MainShell 路由)
├── components/
│   ├── MenuBar.tsx            (新: 顶部菜单栏)
│   ├── ConnectPage.tsx        (保留改造: 样式 WorkBuddy 化)
│   ├── MainShell.tsx          (新: 替代 ChatLayout)
│   ├── conversation-list/
│   │   ├── ConversationList.tsx
│   │   ├── SidebarTopbar.tsx
│   │   ├── SidebarHeader.tsx
│   │   ├── NewTaskButton.tsx
│   │   ├── NavTabs.tsx
│   │   ├── TaskSection.tsx
│   │   ├── SpaceSection.tsx
│   │   └── SidebarFooter.tsx
│   └── home/
│       ├── HomePage.tsx
│       ├── HomeHeader.tsx
│       ├── SceneTabs.tsx
│       ├── GrowthBuddy.tsx
│       ├── HomeComposer.tsx
│       ├── QuickActions.tsx
│       ├── ChatInput.tsx
│       └── ContextBar.tsx
├── styles/
│   ├── tokens.css             (--wb-* 设计 token, 亮/暗主题)
│   ├── menubar.css            (菜单栏样式)
│   ├── sidebar.css            (侧栏样式)
│   ├── home.css               (首页样式)
│   └── global.css             (基础 reset + 变量引入)
└── hooks/
    └── useGateway.ts          (保留不变)
```

### 7.3 当前文件映射

| 当前文件 | 处理 | 新文件 |
|---------|------|--------|
| `TitleBar.tsx` | 删除 | `MenuBar.tsx` |
| `ChatLayout.tsx` | 删除 | `MainShell.tsx` |
| `SessionList.tsx` | 删除 | `conversation-list/ConversationList.tsx` |
| `ChatView.tsx` | 删除 | `home/HomePage.tsx` |
| `InputBar.tsx` | 删除 | `home/ChatInput.tsx` |
| `MessageBubble.tsx` | 暂存 | 后续聊天页用 |
| `ToolPanel.tsx` | 暂存 | 后续聊天页用 |
| `ConnectPage.tsx` | 改造 | 样式 WorkBuddy 化 |
| `global.css` | 拆分 | `tokens.css` + `global.css` |
| `useGateway.ts` | 保留 | 不变 |

## 8. Electron 主进程改动

### 8.1 窗口配置（`main/index.ts`）

```typescript
const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";

mainWindow = new BrowserWindow({
  minWidth: 800,
  minHeight: 600,
  show: false,
  title: "xiaomei-brain",
  webPreferences: {
    preload: path.join(__dirname, "preload.js"),
    contextIsolation: true,
    nodeIntegration: false,
  },
  ...isMac && {
    titleBarStyle: "hiddenInset",
  },
  ...isWindows && {
    frame: false,
    titleBarOverlay: { height: 30, color: "#00000000", symbolColor: "#ffffff" },
  },
  ...!isMac && !isWindows && {
    frame: false,
  },
});
```

### 8.2 删除系统菜单

当前 `main/index.ts` 用 `Menu.setApplicationMenu()` 设置系统菜单——WorkBuddy 用自定义 MenuBar 组件替代，应删除 `Menu.setApplicationMenu()` 调用。

### 8.3 Preload 扩展（`main/preload.ts`）

当前 `window.win` 已有 minimize/maximize/close。新增：
- `win.isMaximized()` — 获取最大化状态
- `win.onMaximizeChange(callback)` — 监听最大化状态变化

### 8.4 平台标记

renderer 入口（`main.tsx` 或 `App.tsx`）设 body 属性：

```typescript
document.body.setAttribute("data-electron-desktop", "true");
document.body.setAttribute("data-application-name", "xiaomei-brain");
const isMac = navigator.platform.toLowerCase().includes("mac");
const isWindows = navigator.platform.toLowerCase().includes("win");
document.body.setAttribute("data-platform", isMac ? "mac" : isWindows ? "windows" : "linux");
```

### 8.5 CSS 平台分支

```css
/* Mac: 隐藏菜单栏 */
body[data-platform="mac"] .menubar { display: none; }

/* Mac: 侧栏 topbar 左侧留 80px 避让红绿灯 */
body[data-platform="mac"] .sidebar-topbar { padding-left: 80px; }

/* Windows/Linux: root 让位菜单栏 30px */
body[data-platform="windows"] #root,
body:not([data-platform="mac"]):not([data-platform="windows"]) #root {
  margin-top: 30px;
  height: calc(100% - 30px);
}
```

## 9. 实现顺序

1. **tokens.css** — 提取设计 token，亮/暗主题
2. **global.css** — 基础 reset + 平台标记 CSS
3. **main/index.ts** — 改造窗口配置（frame/titleBarStyle/titleBarOverlay）
4. **main/preload.ts** — 扩展 win API
5. **MenuBar.tsx** — 顶部菜单栏组件
6. **conversation-list/** — 侧栏全部组件
7. **home/** — 首页全部组件
8. **MainShell.tsx** — 组合侧栏 + 首页
9. **App.tsx** — 改造路由（ConnectPage → MenuBar + MainShell）
10. **ConnectPage.tsx** — 样式 WorkBuddy 化

## 10. 不在本次范围

以下功能不在本次 UI 仿制范围内，后续再接：
- 聊天工作区（claw-workspace / colleague-chat-page）—— 首页只做输入框，发送后跳转聊天页
- 多 Tab 工作区
- 产物抽屉（artifact drawer）
- 搜索面板
- 自动化/技能/插件面板
- 暗色主题切换 UI（token 预留，切换交互不做）
- 练习案例（PracticeCases）
- GrowthBuddy 宠物的实际交互逻辑（先做静态 UI）
