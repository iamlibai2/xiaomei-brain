# WorkBuddy 首页 UI 全仿 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 像素级全仿 WorkBuddy v5.2.5 桌面端首页 UI，替换 xiaomei-brain 桌面端 Renderer 层。

**Architecture:** 提取 WorkBuddy `--wb-*` 设计 token → 改造 Electron 窗口为无边框 → 新建 MenuBar（Win/Linux 顶部菜单栏）+ ConversationList（左侧导航栏）+ HomePage（右侧首页）三大组件树。保留 Gateway WebSocket 后端不变，仅重写 UI 层。

**Tech Stack:** Electron 37 + React 18 + TypeScript 5 + Vite 6。无测试框架，验证方式为 TypeScript 编译检查 + `npm run dev` 视觉验证。

**Spec:** `docs/superpowers/specs/2026-07-10-desktop-workbuddy-home-ui-design.md`

**Working directory:** `src/xiaomei_brain/desktop/`

**Verification commands:**
- TypeScript 编译检查: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
- 启动 dev server: `cd src/xiaomei_brain/desktop && npm run dev:renderer`（仅前端，端口 5173）
- 完整启动: `cd src/xiaomei_brain/desktop && npm run dev`

---

## File Structure

```
src/xiaomei_brain/desktop/
├── main/
│   ├── index.ts                    (修改: 窗口配置 frame/titleBarStyle)
│   ├── preload.ts                  (修改: 扩展 win API)
│   └── ipc-handlers.ts             (修改: 新增 window: IPC handlers)
├── renderer/
│   ├── main.tsx                    (修改: 引入新 CSS + 平台标记)
│   ├── App.tsx                     (重写: MenuBar + MainShell 路由)
│   ├── types.ts                    (修改: 扩展 Window.win 类型)
│   ├── styles/
│   │   ├── tokens.css              (新建: --wb-* 设计 token)
│   │   ├── global.css              (重写: 基础 reset + 平台分支)
│   │   ├── menubar.css             (新建: 菜单栏样式)
│   │   ├── sidebar.css             (新建: 侧栏样式)
│   │   └── home.css                (新建: 首页样式)
│   ├── components/
│   │   ├── MenuBar.tsx             (新建)
│   │   ├── ConnectPage.tsx         (修改: 样式 WorkBuddy 化)
│   │   ├── MainShell.tsx           (新建: 替代 ChatLayout)
│   │   ├── conversation-list/
│   │   │   ├── ConversationList.tsx
│   │   │   ├── SidebarTopbar.tsx
│   │   │   ├── SidebarHeader.tsx
│   │   │   ├── NewTaskButton.tsx
│   │   │   ├── NavTabs.tsx
│   │   │   ├── CollapsibleSection.tsx
│   │   │   └── SidebarFooter.tsx
│   │   └── home/
│   │       ├── HomePage.tsx
│   │       ├── HomeHeader.tsx
│   │       ├── SceneTabs.tsx
│   │       ├── GrowthBuddy.tsx
│   │       ├── HomeComposer.tsx
│   │       ├── QuickActions.tsx
│   │       ├── ChatInput.tsx
│   │       └── ContextBar.tsx
│   └── hooks/
│       └── useGateway.ts           (保留不变)
├── 删除:
│   ├── renderer/components/TitleBar.tsx
│   ├── renderer/components/ChatLayout.tsx
│   ├── renderer/components/SessionList.tsx
│   ├── renderer/components/ChatView.tsx
│   ├── renderer/components/InputBar.tsx
│   ├── renderer/components/MessageBubble.tsx
│   └── renderer/components/ToolPanel.tsx
```

---

## Task 1: 设计 Token 系统

**Files:**
- Create: `renderer/styles/tokens.css`

- [ ] **Step 1: 创建 tokens.css**

创建 `renderer/styles/tokens.css`，包含完整的 WorkBuddy `--wb-*` 设计 token（亮色 + 暗色主题）。

```css
/* ─── WorkBuddy Design Tokens ─── */
/* 提取自 WorkBuddy v5.2.5 cb-bridge CSS */

:root {
  /* Palette — Brand (薄荷绿) */
  --wb-palette-brand-1: #DFF7F2;
  --wb-palette-brand-2: #BFF0E6;
  --wb-palette-brand-3: #9FE8D9;
  --wb-palette-brand-4: #80E1CD;
  --wb-palette-brand-5: #60D9C0;
  --wb-palette-brand-7: #40D1B3;
  --wb-palette-brand-8: #00C29A;
  --wb-palette-brand-9: #009273;
  --wb-palette-brand-10: #00614D;

  /* Palette — Gray */
  --wb-palette-gray-1: #FAFAFA;
  --wb-palette-gray-2: #F7F7F7;
  --wb-palette-gray-3: #F2F2F2;
  --wb-palette-gray-4: #EBEBEB;
  --wb-palette-gray-5: #E6E6E6;

  /* Palette — Black/White */
  --wb-palette-black-10: rgba(0, 0, 0, 0.1);
  --wb-palette-black-20: rgba(0, 0, 0, 0.2);
  --wb-palette-black-30: rgba(0, 0, 0, 0.3);
  --wb-palette-black-50: rgba(0, 0, 0, 0.5);
  --wb-palette-black-70: rgba(0, 0, 0, 0.7);
  --wb-palette-black-75: rgba(0, 0, 0, 0.75);
  --wb-palette-black-90: rgba(0, 0, 0, 0.9);
  --wb-palette-black-100: #000000;
  --wb-palette-white-100: #FFFFFF;

  /* Semantic — Text */
  --wb-color-text-primary: var(--wb-palette-black-90);
  --wb-color-text-secondary: var(--wb-palette-black-70);
  --wb-color-text-tertiary: var(--wb-palette-black-50);
  --wb-color-text-disabled: var(--wb-palette-black-30);
  --wb-text-strong: var(--wb-color-text-primary);
  --wb-text-weak: var(--wb-color-text-tertiary);
  --wb-text-muted: var(--wb-color-text-disabled);

  /* Semantic — Background */
  --wb-bg-primary: var(--wb-palette-white-100);
  --wb-bg-secondary: var(--wb-palette-gray-2);
  --wb-bg-tertiary: var(--wb-palette-gray-4);
  --wb-bg-hover: color-mix(in srgb, var(--wb-palette-black-100) 5%, transparent);
  --wb-bg-active: color-mix(in srgb, var(--wb-palette-black-100) 8%, transparent);
  --wb-sidebar-bg: var(--wb-palette-gray-3);

  /* Semantic — Border */
  --wb-border-default: color-mix(in srgb, var(--wb-palette-black-100) 8%, transparent);
  --wb-border-subtle: var(--wb-palette-gray-3);
  --wb-border-strong: var(--wb-palette-gray-5);
  --wb-border-focus: var(--wb-palette-black-75);

  /* Semantic — Brand */
  --wb-brand-primary: var(--wb-palette-brand-8);

  /* Sidebar menu tokens */
  --wb-todo-menu-text-default: var(--wb-color-text-secondary);
  --wb-todo-menu-text-heading: var(--wb-color-text-tertiary);
  --wb-todo-menu-icon-default: var(--wb-color-text-tertiary);
  --wb-todo-menu-bg-hover: var(--wb-bg-hover);

  /* Button tokens */
  --wb-button-ghost-bg-hover: var(--wb-bg-hover);
  --wb-button-grey-bg: var(--wb-palette-gray-4);
  --wb-button-grey-bg-hover: var(--wb-palette-gray-5);

  /* Font */
  --wb-font-family: "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --wb-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  /* Spacing */
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

  /* Radius */
  --wb-radius-xs: 2px;
  --wb-radius-sm: 4px;
  --wb-radius-md: 6px;
  --wb-radius-lg: 8px;
  --wb-radius-xl: 12px;
  --wb-radius-2xl: 16px;
  --wb-radius-full: 9999px;

  /* Shadow */
  --wb-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.08);
  --wb-shadow-md: 0 2px 8px rgba(0, 0, 0, 0.12);
  --wb-shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.16);
  --wb-shadow-xl: 0 8px 32px rgba(0, 0, 0, 0.20);

  /* Icon */
  --wb-icon-primary: var(--wb-color-text-primary);
  --wb-icon-secondary: var(--wb-color-text-secondary);

  /* Version badge */
  --wb-text-version-badge: var(--wb-color-text-tertiary);
}

/* ─── Dark Theme ─── */
@media (prefers-color-scheme: dark) {
  :root {
    --wb-palette-gray-1: #141414;
    --wb-palette-gray-2: #292929;
    --wb-palette-gray-3: #1f1f1f;
    --wb-palette-gray-4: #242424;
    --wb-palette-gray-5: #3a3a3a;

    --wb-palette-brand-7: #22cba8;
    --wb-palette-brand-8: #4cf0ce;

    --wb-color-text-primary: rgba(255, 255, 255, 0.92);
    --wb-color-text-secondary: rgba(255, 255, 255, 0.65);
    --wb-color-text-tertiary: rgba(255, 255, 255, 0.45);
    --wb-color-text-disabled: rgba(255, 255, 255, 0.25);

    --wb-bg-primary: var(--wb-palette-gray-3);
    --wb-bg-secondary: var(--wb-palette-gray-2);
    --wb-bg-tertiary: var(--wb-palette-gray-5);
    --wb-bg-hover: color-mix(in srgb, var(--wb-palette-white-100) 5%, transparent);
    --wb-bg-active: color-mix(in srgb, var(--wb-palette-white-100) 8%, transparent);
    --wb-sidebar-bg: var(--wb-palette-gray-3);

    --wb-border-default: color-mix(in srgb, var(--wb-palette-white-100) 8%, transparent);
    --wb-border-subtle: var(--wb-palette-gray-4);
    --wb-border-strong: #262626;
  }
}
```

- [ ] **Step 2: 验证 CSS 语法**

Run: `cd src/xiaomei_brain/desktop && head -5 renderer/styles/tokens.css`
Expected: 文件存在，首行为注释 `/* ─── WorkBuddy Design Tokens ─── */`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/styles/tokens.css
git commit -m "feat(desktop): 添加 WorkBuddy 设计 token 系统"
```

---

## Task 2: 全局样式重写

**Files:**
- Rewrite: `renderer/styles/global.css`

- [ ] **Step 1: 重写 global.css**

将 `renderer/styles/global.css` 完全重写为基础 reset + 平台分支 CSS。保留 ConnectPage 的样式（暂存到一起，后续 Task 10 再拆）。

```css
@import "./tokens.css";

*,
*::before,
*::after {
  box-sizing: border-box;
}

html,
body,
#root {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

body {
  background: var(--wb-bg-primary);
  color: var(--wb-color-text-primary);
  font-family: var(--wb-font-family);
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ─── Scrollbar ─── */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-thumb {
  background-color: rgba(100, 100, 100, 0.4);
  border-radius: 5px;
}
::-webkit-scrollbar-thumb:hover {
  background-color: rgba(100, 100, 100, 0.7);
}
::-webkit-scrollbar-track {
  background: transparent;
}

/* ─── App Root ─── */
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ─── Main Shell (侧栏 + 主内容) ─── */
.main-shell {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ─── 平台分支 ─── */
/* Windows/Linux: root 让位菜单栏 30px */
body[data-platform="windows"] #root,
body:not([data-platform="mac"]):not([data-platform="windows"]) #root {
  margin-top: 30px;
  height: calc(100% - 30px);
}

/* Mac: 菜单栏隐藏 */
body[data-platform="mac"] .menubar {
  display: none;
}

/* ─── Connect Page (暂存, Task 10 重写) ─── */
.connect-page {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  background: var(--wb-bg-primary);
}

.connect-card {
  background: var(--wb-bg-secondary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-2xl);
  padding: 40px;
  width: 420px;
  max-width: 90vw;
  text-align: center;
}

.connect-card h1 {
  font-size: 28px;
  font-weight: 800;
  color: var(--wb-color-text-primary);
  margin-bottom: 4px;
}

.connect-subtitle {
  color: var(--wb-color-text-secondary);
  margin-bottom: 28px;
  font-size: 14px;
}

.connect-field {
  margin-bottom: 16px;
  text-align: left;
}

.connect-field label {
  display: block;
  font-size: 12px;
  color: var(--wb-color-text-secondary);
  margin-bottom: 6px;
  font-weight: 500;
}

.connect-field input {
  width: 100%;
  padding: 10px 14px;
  background: var(--wb-bg-primary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-lg);
  color: var(--wb-color-text-primary);
  font-size: 14px;
  font-family: var(--wb-font-family);
  outline: none;
}

.connect-field input:focus {
  border-color: var(--wb-brand-primary);
}

.connect-error {
  color: var(--wb-palette-red-8, #F64041);
  font-size: 13px;
  margin-bottom: 12px;
  text-align: left;
}

.connect-btn {
  width: 100%;
  padding: 12px;
  background: var(--wb-brand-primary);
  color: white;
  border: none;
  border-radius: var(--wb-radius-lg);
  font-size: 15px;
  font-weight: 600;
  font-family: var(--wb-font-family);
  cursor: pointer;
  margin-top: 4px;
}

.connect-btn:hover {
  background: var(--wb-palette-brand-7);
}

.connect-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 2: 修改 main.tsx 引入新 CSS 结构**

修改 `renderer/main.tsx`，在引入 `global.css` 之前添加平台标记脚本。

```typescript
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/global.css";

// ─── 平台标记 (WorkBuddy 风格) ───
document.body.setAttribute("data-electron-desktop", "true");
document.body.setAttribute("data-application-name", "xiaomei-brain");
const isMac = navigator.platform.toLowerCase().includes("mac");
const isWindows = navigator.platform.toLowerCase().includes("win");
document.body.setAttribute(
  "data-platform",
  isMac ? "mac" : isWindows ? "windows" : "linux"
);

const root = createRoot(document.getElementById("root")!);
root.render(<App />);
```

- [ ] **Step 3: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/styles/global.css \
        src/xiaomei_brain/desktop/renderer/main.tsx
git commit -m "feat(desktop): 重写全局样式 + 平台标记"
```

---

## Task 3: Electron 窗口配置改造

**Files:**
- Modify: `main/index.ts`
- Modify: `main/preload.ts`
- Modify: `main/ipc-handlers.ts`

- [ ] **Step 1: 改造 main/index.ts 窗口配置**

将 `main/index.ts` 的 `createWindow()` 函数改为平台差异化无边框窗口，并删除 `Menu.setApplicationMenu()`。

完整替换 `main/index.ts`：

```typescript
import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { Store } from "./store";
import { registerIpcHandlers } from "./ipc-handlers";

const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";

let mainWindow: BrowserWindow | null = null;
const gateway = new GatewayClient();
const store = new Store();

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
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
      titleBarOverlay: {
        height: 30,
        color: "#00000000",
        symbolColor: "#ffffff",
      },
    },
    ...!isMac && !isWindows && {
      frame: false,
    },
  });

  mainWindow.on("ready-to-show", () => {
    mainWindow?.show();
  });

  if (process.env.NODE_ENV === "development") {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }

  // 窗口控制 IPC
  ipcMain.on("window:minimize", () => mainWindow?.minimize());
  ipcMain.on("window:maximize", () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow?.maximize();
    }
  });
  ipcMain.on("window:close", () => mainWindow?.close());
  ipcMain.handle("window:isMaximized", () => mainWindow?.isMaximized() ?? false);

  mainWindow.on("maximize", () => {
    mainWindow?.webContents.send("window:maximizeChanged", true);
  });
  mainWindow.on("unmaximize", () => {
    mainWindow?.webContents.send("window:maximizeChanged", false);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();
  registerIpcHandlers(gateway, store, () => mainWindow);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (mainWindow === null) {
    createWindow();
  }
});
```

关键改动：
- 删除 `Menu.setApplicationMenu()` 调用（用自定义 MenuBar 组件替代）
- 平台差异化窗口配置（Mac hiddenInset / Windows titleBarOverlay / Linux frame:false）
- 新增 `window:isMaximized` IPC handler
- 新增 maximize/unmaximize 事件转发
- `ready-to-show` 事件避免白屏闪烁
- 窗口尺寸从 1100×750 调大到 1200×800

- [ ] **Step 2: 改造 main/preload.ts**

扩展 `window.win` API，新增 `isMaximized` 和 `onMaximizeChange`。

完整替换 `main/preload.ts`：

```typescript
import { contextBridge, ipcRenderer } from "electron";

export interface GatewayAPI {
  connect: (args: {
    host: string;
    port: number;
    token: string;
    userId: string;
  }) => Promise<unknown>;
  disconnect: () => Promise<void>;
  sendMessage: (args: { content: string }) => Promise<unknown>;
  abortMessage: () => Promise<unknown>;
  getHistory: (args: {
    sessionId?: string;
    limit?: number;
  }) => Promise<unknown>;
  listIdentities: () => Promise<unknown>;
  getSessions: () => Promise<unknown>;
  getMessages: (args: {
    sessionId: string;
    limit?: number;
  }) => Promise<unknown>;
  getConfig: (key: string) => Promise<unknown>;
  onEvent: (callback: (event: string, data: unknown) => void) => void;
  removeEventListener: () => void;
}

const api: GatewayAPI = {
  connect: (args) => ipcRenderer.invoke("gateway:connect", args),
  disconnect: () => ipcRenderer.invoke("gateway:disconnect"),
  sendMessage: (args) => ipcRenderer.invoke("gateway:sendMessage", args),
  abortMessage: () => ipcRenderer.invoke("gateway:abortMessage"),
  getHistory: (args) => ipcRenderer.invoke("gateway:getHistory", args),
  listIdentities: () => ipcRenderer.invoke("gateway:listIdentities"),
  getSessions: () => ipcRenderer.invoke("store:getSessions"),
  getMessages: (args) => ipcRenderer.invoke("store:getMessages", args),
  getConfig: (key) => ipcRenderer.invoke("store:getConfig", key),

  onEvent: (callback) => {
    const handler = (_event: unknown, data: { event: string; data: unknown }) => {
      callback(data.event, data.data);
    };
    ipcRenderer.on("gateway:event", handler);
    (api as unknown as Record<string, unknown>)["_eventHandler"] = handler;
  },

  removeEventListener: () => {
    const handler = (api as unknown as Record<string, unknown>)["_eventHandler"];
    if (handler) {
      ipcRenderer.removeListener("gateway:event", handler as (...args: unknown[]) => void);
    }
  },
};

contextBridge.exposeInMainWorld("gateway", api);

contextBridge.exposeInMainWorld("win", {
  minimize: () => ipcRenderer.send("window:minimize"),
  maximize: () => ipcRenderer.send("window:maximize"),
  close: () => ipcRenderer.send("window:close"),
  isMaximized: () => ipcRenderer.invoke("window:isMaximized"),
  onMaximizeChange: (callback: (maximized: boolean) => void) => {
    const handler = (_event: unknown, maximized: boolean) => callback(maximized);
    ipcRenderer.on("window:maximizeChanged", handler);
  },
});
```

- [ ] **Step 3: 更新 types.ts 的 Window.win 类型声明**

在 `renderer/types.ts` 末尾的 `declare global` 块中扩展 `Window.win`：

将 `renderer/types.ts` 中的 `declare global` 块替换为：

```typescript
declare global {
  interface Window {
    gateway: GatewayAPI;
    win: {
      minimize: () => void;
      maximize: () => void;
      close: () => void;
      isMaximized: () => Promise<boolean>;
      onMaximizeChange: (callback: (maximized: boolean) => void) => void;
    };
  }
}
```

- [ ] **Step 4: TypeScript 编译检查（main + renderer）**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.main.json && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/desktop/main/index.ts \
        src/xiaomei_brain/desktop/main/preload.ts \
        src/xiaomei_brain/desktop/renderer/types.ts
git commit -m "feat(desktop): 无边框窗口 + 平台差异化标题栏"
```

---

## Task 4: MenuBar 组件

**Files:**
- Create: `renderer/components/MenuBar.tsx`
- Create: `renderer/styles/menubar.css`

- [ ] **Step 1: 创建 menubar.css**

创建 `renderer/styles/menubar.css`：

```css
.menubar {
  display: flex;
  align-items: center;
  height: 30px;
  padding: 0 8px;
  background: var(--wb-sidebar-bg);
  border-bottom: 1px solid var(--wb-border-subtle);
  -webkit-app-region: drag;
  user-select: none;
  flex-shrink: 0;
  font-size: 12px;
}

.menubar-logo {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  -webkit-app-region: no-drag;
}

.menubar-logo-icon {
  width: 18px;
  height: 18px;
  border-radius: var(--wb-radius-sm);
  background: var(--wb-brand-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 10px;
  font-weight: 700;
}

.menubar-logo-text {
  font-size: 12px;
  font-weight: 700;
  color: var(--wb-color-text-primary);
}

.menubar-items {
  display: flex;
  align-items: center;
  gap: 0;
  -webkit-app-region: no-drag;
}

.menubar-item {
  position: relative;
}

.menubar-item-button {
  height: 30px;
  padding: 0 8px;
  border: none;
  background: transparent;
  color: var(--wb-color-text-primary);
  font-size: 12px;
  font-family: var(--wb-font-family);
  cursor: pointer;
  display: flex;
  align-items: center;
}

.menubar-item-button:hover {
  background: var(--wb-bg-hover);
}

.menubar-item-button.open {
  background: var(--wb-bg-active);
}

.menubar-dropdown {
  position: absolute;
  top: 30px;
  left: 0;
  min-width: 160px;
  background: var(--wb-bg-primary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-lg);
  box-shadow: var(--wb-shadow-lg);
  padding: 4px;
  z-index: 9999;
}

.menubar-dropdown-item {
  width: 100%;
  height: 28px;
  padding: 0 10px;
  border: none;
  background: transparent;
  color: var(--wb-color-text-primary);
  font-size: 12px;
  font-family: var(--wb-font-family);
  text-align: left;
  cursor: pointer;
  border-radius: var(--wb-radius-sm);
  display: flex;
  align-items: center;
}

.menubar-dropdown-item:hover {
  background: var(--wb-bg-hover);
}

.menubar-dropdown-separator {
  height: 1px;
  margin: 4px 6px;
  background: var(--wb-border-default);
}

.menubar-spacer {
  flex: 1;
}

.menubar-window-controls {
  display: flex;
  align-items: center;
  gap: 0;
  -webkit-app-region: no-drag;
}

.menubar-window-btn {
  width: 46px;
  height: 30px;
  border: none;
  background: transparent;
  color: var(--wb-color-text-primary);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.menubar-window-btn:hover {
  background: var(--wb-bg-hover);
}

.menubar-window-btn-close:hover {
  background: #e81123;
  color: white;
}
```

- [ ] **Step 2: 创建 MenuBar.tsx**

创建 `renderer/components/MenuBar.tsx`：

```tsx
import { useState, useRef, useEffect } from "react";

interface MenuItem {
  label: string;
  action?: () => void;
  separator?: boolean;
}

const menus: Record<string, MenuItem[]> = {
  "编辑(E)": [
    { label: "撤销", action: () => document.execCommand("undo") },
    { label: "重做", action: () => document.execCommand("redo") },
    { separator: true, label: "" },
    { label: "剪切", action: () => document.execCommand("cut") },
    { label: "复制", action: () => document.execCommand("copy") },
    { label: "粘贴", action: () => document.execCommand("paste") },
    { label: "全选", action: () => document.execCommand("selectAll") },
  ],
  "窗口(W)": [
    { label: "重新加载", action: () => location.reload() },
    { label: "开发者工具", action: () => {} },
    { separator: true, label: "" },
    { label: "关闭", action: () => window.win.close() },
  ],
  "帮助(H)": [
    {
      label: "关于 xiaomei-brain",
      action: () =>
        alert("xiaomei-brain Desktop\n版本 1.0.0\nAI Agent 大脑框架"),
    },
  ],
};

export function MenuBar() {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [maximized, setMaximized] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    window.win.isMaximized().then(setMaximized);
    window.win.onMaximizeChange(setMaximized);
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div className="menubar" ref={menuRef}>
      <div className="menubar-logo">
        <div className="menubar-logo-icon">小</div>
        <span className="menubar-logo-text">xiaomei-brain</span>
      </div>

      <div className="menubar-items">
        {Object.keys(menus).map((key) => (
          <div className="menubar-item" key={key}>
            <button
              className={`menubar-item-button ${openMenu === key ? "open" : ""}`}
              onClick={() => setOpenMenu(openMenu === key ? null : key)}
            >
              {key}
            </button>
            {openMenu === key && (
              <div className="menubar-dropdown">
                {menus[key].map((item, i) =>
                  item.separator ? (
                    <div className="menubar-dropdown-separator" key={i} />
                  ) : (
                    <button
                      key={i}
                      className="menubar-dropdown-item"
                      onClick={() => {
                        item.action?.();
                        setOpenMenu(null);
                      }}
                    >
                      {item.label}
                    </button>
                  )
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="menubar-spacer" />

      <div className="menubar-window-controls">
        <button
          className="menubar-window-btn"
          onClick={() => window.win.minimize()}
          title="最小化"
        >
          &#x2212;
        </button>
        <button
          className="menubar-window-btn"
          onClick={() => window.win.maximize()}
          title={maximized ? "还原" : "最大化"}
        >
          {maximized ? "&#x29C9;" : "&#x25A1;"}
        </button>
        <button
          className="menubar-window-btn menubar-window-btn-close"
          onClick={() => window.win.close()}
          title="关闭"
        >
          &#x2715;
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/MenuBar.tsx \
        src/xiaomei_brain/desktop/renderer/styles/menubar.css
git commit -m "feat(desktop): 添加 MenuBar 顶部菜单栏组件"
```

---

## Task 5: 侧栏样式

**Files:**
- Create: `renderer/styles/sidebar.css`

- [ ] **Step 1: 创建 sidebar.css**

创建 `renderer/styles/sidebar.css`，包含完整的侧栏样式。

```css
/* ─── ConversationList 容器 ─── */
.conversation-list {
  background: var(--wb-sidebar-bg);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: 260px;
  height: 100%;
  overflow: hidden;
  transition: width 0.25s ease-out;
}

.conversation-list.collapsed {
  width: 48px;
  min-width: 48px;
}

/* ─── Sidebar Topbar (56px drag region) ─── */
.sidebar-topbar {
  position: relative;
  height: 56px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-shrink: 0;
  -webkit-app-region: drag;
  gap: 4px;
}

.sidebar-topbar button {
  -webkit-app-region: no-drag;
}

body[data-platform="mac"] .sidebar-topbar {
  padding-left: 80px;
}

.sidebar-icon-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--wb-radius-lg);
  background: transparent;
  border: none;
  color: var(--wb-color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.sidebar-icon-btn:hover {
  background: var(--wb-button-ghost-bg-hover);
  color: var(--wb-icon-primary);
}

/* ─── Sidebar Header (Logo + Version) ─── */
.sidebar-header {
  padding: 0 12px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-logo-row {
  height: 20px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.sidebar-logo {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.sidebar-logo-icon {
  width: 20px;
  height: 20px;
  border-radius: var(--wb-radius-sm);
  background: var(--wb-brand-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}

.sidebar-logo-text {
  font-size: 12px;
  font-weight: 700;
  color: var(--wb-color-text-primary);
  line-height: 20px;
}

.sidebar-version-badge {
  font-size: 10px;
  font-weight: 400;
  color: var(--wb-text-version-badge);
  line-height: 1;
  white-space: nowrap;
}

/* ─── New Task Button ─── */
.new-task-button {
  margin: 0 12px 8px;
  height: 36px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: none;
  border-radius: var(--wb-radius-lg);
  background: var(--wb-bg-tertiary);
  color: var(--wb-color-text-primary);
  font-size: 13px;
  font-family: var(--wb-font-family);
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.new-task-button:hover {
  background: var(--wb-palette-gray-5);
}

.new-task-button svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

/* ─── Nav Tabs ─── */
.nav-tabs {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0;
}

.nav-tab {
  width: 100%;
  height: 30px;
  border: none;
  border-radius: var(--wb-radius-lg);
  background: transparent;
  color: var(--wb-todo-menu-text-default);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 13px;
  line-height: 22px;
  font-weight: 400;
  text-align: left;
  overflow: hidden;
  transition: background-color 0.15s ease, color 0.15s ease;
  font-family: var(--wb-font-family);
}

.nav-tab svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--wb-todo-menu-icon-default);
  transition: color 0.15s ease;
}

.nav-tab:hover {
  background: var(--wb-todo-menu-bg-hover);
}

.nav-tab.active {
  background: var(--wb-bg-active);
  color: var(--wb-color-text-primary);
}

.nav-tab.active svg {
  color: var(--wb-color-text-primary);
}

.nav-tab-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-tab-red-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 4px;
  border-radius: 50%;
  background-color: #e53e3e;
  flex-shrink: 0;
}

/* ─── Collapsible Section ─── */
.collapsible-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 8px;
}

.section-header {
  display: flex;
  align-items: center;
  padding: 6px 0 6px 16px;
  margin: 0 12px;
  height: 36px;
  flex: 0 0 36px;
  gap: 6px;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  border-radius: var(--wb-radius-sm);
  transition: background 0.15s;
  text-align: left;
  font-family: var(--wb-font-family);
}

.section-header:hover {
  background: var(--wb-todo-menu-bg-hover);
}

.section-header-text {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  color: var(--wb-todo-menu-text-heading);
}

.section-chevron {
  flex: 0 0 14px;
  color: var(--wb-color-text-tertiary);
  transition: transform 0.2s ease;
  font-size: 14px;
}

.section-chevron.collapsed {
  transform: rotate(-90deg);
}

.section-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.section-body.collapsed {
  height: 0;
  overflow: hidden;
  gap: 0;
}

/* ─── Task / Space Item ─── */
.task-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px 6px 36px;
  margin: 0 12px;
  height: 30px;
  border-radius: var(--wb-radius-sm);
  cursor: pointer;
  transition: background-color 0.15s ease;
  gap: 8px;
}

.task-item:hover {
  background: var(--wb-todo-menu-bg-hover);
}

.task-item-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--wb-color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-item-time {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--wb-color-text-disabled);
}

.task-item-active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--wb-brand-primary);
  flex-shrink: 0;
}

.space-item {
  display: flex;
  flex-direction: column;
  padding: 6px 12px 6px 36px;
  margin: 0 12px;
  border-radius: var(--wb-radius-sm);
  cursor: pointer;
  transition: background-color 0.15s ease;
  gap: 2px;
}

.space-item:hover {
  background: var(--wb-todo-menu-bg-hover);
}

.space-item-title {
  font-size: 13px;
  color: var(--wb-color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.space-item-subtitle {
  font-size: 12px;
  color: var(--wb-color-text-disabled);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ─── Sidebar Footer ─── */
.sidebar-footer {
  padding: 12px 16px 12px 12px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-shrink: 0;
  border-top: 1px solid var(--wb-border-subtle);
}

.sidebar-footer-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid var(--wb-brand-primary);
  background: var(--wb-palette-gray-5);
  color: var(--wb-color-text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
  cursor: pointer;
}

.sidebar-footer-name {
  flex: 1;
  min-width: 0;
  margin-left: 10px;
  font-size: 13px;
  font-weight: 500;
  color: var(--wb-color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-footer-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/styles/sidebar.css
git commit -m "feat(desktop): 添加侧栏样式"
```

---

## Task 6: 侧栏组件——SidebarTopbar + SidebarHeader + NewTaskButton

**Files:**
- Create: `renderer/components/conversation-list/SidebarTopbar.tsx`
- Create: `renderer/components/conversation-list/SidebarHeader.tsx`
- Create: `renderer/components/conversation-list/NewTaskButton.tsx`

- [ ] **Step 1: 创建 SidebarTopbar.tsx**

```tsx
interface SidebarTopbarProps {
  onToggleCollapse: () => void;
  onSearch: () => void;
  onRefresh: () => void;
}

export function SidebarTopbar({ onToggleCollapse, onSearch, onRefresh }: SidebarTopbarProps) {
  return (
    <div className="sidebar-topbar">
      <button className="sidebar-icon-btn" onClick={onRefresh} title="刷新">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 2v6h6" />
          <path d="M21 12A9 9 0 0 0 6 5.3L3 8" />
          <path d="M21 22v-6h-6" />
          <path d="M3 12a9 9 0 0 0 15 6.7l3-2.7" />
        </svg>
      </button>
      <button className="sidebar-icon-btn" onClick={onSearch} title="搜索">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
      </button>
      <button className="sidebar-icon-btn" onClick={onToggleCollapse} title="折叠侧栏">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
    </div>
  );
}
```

- [ ] **Step 2: 创建 SidebarHeader.tsx**

```tsx
export function SidebarHeader() {
  return (
    <div className="sidebar-header">
      <div className="sidebar-logo-row">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">小</div>
          <span className="sidebar-logo-text">xiaomei-brain</span>
        </div>
        <span className="sidebar-version-badge">v1.0.0</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 创建 NewTaskButton.tsx**

```tsx
interface NewTaskButtonProps {
  onClick: () => void;
}

export function NewTaskButton({ onClick }: NewTaskButtonProps) {
  return (
    <button className="new-task-button" onClick={onClick}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="5" x2="12" y2="19" />
        <line x1="5" y1="12" x2="19" y2="12" />
      </svg>
      <span>新建任务</span>
    </button>
  );
}
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/conversation-list/SidebarTopbar.tsx \
        src/xiaomei_brain/desktop/renderer/components/conversation-list/SidebarHeader.tsx \
        src/xiaomei_brain/desktop/renderer/components/conversation-list/NewTaskButton.tsx
git commit -m "feat(desktop): 侧栏头部组件 (Topbar/Header/NewTaskButton)"
```

---

## Task 7: 侧栏组件——NavTabs + CollapsibleSection + SidebarFooter

**Files:**
- Create: `renderer/components/conversation-list/NavTabs.tsx`
- Create: `renderer/components/conversation-list/CollapsibleSection.tsx`
- Create: `renderer/components/conversation-list/SidebarFooter.tsx`

- [ ] **Step 1: 创建 NavTabs.tsx**

```tsx
interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  active?: boolean;
  redDot?: boolean;
}

interface NavTabsProps {
  items: NavItem[];
  onSelect: (id: string) => void;
}

export function NavTabs({ items, onSelect }: NavTabsProps) {
  return (
    <div className="nav-tabs">
      {items.map((item) => (
        <button
          key={item.id}
          className={`nav-tab ${item.active ? "active" : ""}`}
          onClick={() => onSelect(item.id)}
        >
          {item.icon}
          <span className="nav-tab-label">{item.label}</span>
          {item.redDot && <span className="nav-tab-red-dot" />}
        </button>
      ))}
    </div>
  );
}

// ─── 内置图标 ───
export const NavIcons = {
  assistant: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </svg>
  ),
  project: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2H5a2 2 0 0 1-2-2" />
      <path d="M8 3v4" />
      <path d="M16 3v4" />
    </svg>
  ),
  expert: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2v6" />
      <path d="M5 8h14l-1 5a7 7 0 0 1-12 0z" />
      <path d="M12 18v4" />
    </svg>
  ),
  automation: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a10 10 0 1 0 10 10" />
      <path d="M12 6v6l4 2" />
    </svg>
  ),
  more: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </svg>
  ),
};
```

- [ ] **Step 2: 创建 CollapsibleSection.tsx**

```tsx
import { useState, ReactNode } from "react";

interface CollapsibleSectionProps {
  title: string;
  count?: number;
  defaultExpanded?: boolean;
  children: ReactNode;
}

export function CollapsibleSection({
  title,
  count,
  defaultExpanded = true,
  children,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="collapsible-section">
      <button
        className="section-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="section-header-text">
          {title}
          {count !== undefined && ` (${count})`}
        </span>
        <span className={`section-chevron ${!expanded ? "collapsed" : ""}`}>
          ▾
        </span>
      </button>
      <div className={`section-body ${!expanded ? "collapsed" : ""}`}>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 创建 SidebarFooter.tsx**

```tsx
interface SidebarFooterProps {
  userName: string;
  onSettings?: () => void;
  onNotifications?: () => void;
}

export function SidebarFooter({ userName, onSettings, onNotifications }: SidebarFooterProps) {
  return (
    <div className="sidebar-footer">
      <div className="sidebar-footer-avatar">{userName[0] || "?"}</div>
      <span className="sidebar-footer-name">{userName}</span>
      <div className="sidebar-footer-actions">
        <button className="sidebar-icon-btn" onClick={onNotifications} title="通知">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
            <path d="M10 21a2 2 0 0 0 4 0" />
          </svg>
        </button>
        <button className="sidebar-icon-btn" onClick={onSettings} title="设置">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v6m0 10v6M4.22 4.22l4.24 4.24m7.08 7.08 4.24 4.24M1 12h6m10 0h6M4.22 19.78l4.24-4.24m7.08-7.08 4.24-4.24" />
          </svg>
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/conversation-list/NavTabs.tsx \
        src/xiaomei_brain/desktop/renderer/components/conversation-list/CollapsibleSection.tsx \
        src/xiaomei_brain/desktop/renderer/components/conversation-list/SidebarFooter.tsx
git commit -m "feat(desktop): 侧栏导航/折叠区/用户区组件"
```

---

## Task 8: ConversationList 组装

**Files:**
- Create: `renderer/components/conversation-list/ConversationList.tsx`

- [ ] **Step 1: 创建 ConversationList.tsx**

组装所有侧栏子组件。包含模拟数据（后续接 Gateway 后替换）。

```tsx
import { useState } from "react";
import { SidebarTopbar } from "./SidebarTopbar";
import { SidebarHeader } from "./SidebarHeader";
import { NewTaskButton } from "./NewTaskButton";
import { NavTabs, NavIcons } from "./NavTabs";
import { CollapsibleSection } from "./CollapsibleSection";
import { SidebarFooter } from "./SidebarFooter";

interface TaskItem {
  name: string;
  time: string;
  active?: boolean;
}

interface SpaceItem {
  title: string;
  subtitle: string;
}

interface ConversationListProps {
  userName?: string;
  onNewTask?: () => void;
}

const navItems = [
  { id: "assistant", label: "助理", icon: NavIcons.assistant },
  { id: "project", label: "项目", icon: NavIcons.project },
  { id: "expert", label: "专家·技能·连接器", icon: NavIcons.expert },
  { id: "automation", label: "自动化", icon: NavIcons.automation },
  { id: "more", label: "更多", icon: NavIcons.more },
];

const mockTasks: TaskItem[] = [
  { name: "JSON-RPC 协议讨论", time: "3天前", active: true },
  { name: "代码 Review", time: "昨天" },
  { name: "Python 环境配置", time: "5天前" },
];

const mockSpaces: SpaceItem[] = [
  { title: "xiaomei-brain 开发", subtitle: "3 个任务" },
];

export function ConversationList({ userName = "李白", onNewTask }: ConversationListProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [activeNav, setActiveNav] = useState("assistant");

  return (
    <div className={`conversation-list ${collapsed ? "collapsed" : ""}`}>
      <SidebarTopbar
        onToggleCollapse={() => setCollapsed(!collapsed)}
        onSearch={() => {}}
        onRefresh={() => {}}
      />
      {!collapsed && (
        <>
          <SidebarHeader />
          <NewTaskButton onClick={() => onNewTask?.()} />
          <NavTabs items={navItems} onSelect={setActiveNav} />
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <CollapsibleSection title="任务" count={mockTasks.length}>
              {mockTasks.map((task, i) => (
                <div key={i} className="task-item">
                  <span className="task-item-name">
                    {task.name}
                    {task.active && <span className="task-item-active-dot" />}
                  </span>
                  <span className="task-item-time">{task.time}</span>
                </div>
              ))}
            </CollapsibleSection>
            <CollapsibleSection title="空间" count={mockSpaces.length}>
              {mockSpaces.map((space, i) => (
                <div key={i} className="space-item">
                  <span className="space-item-title">{space.title}</span>
                  <span className="space-item-subtitle">{space.subtitle}</span>
                </div>
              ))}
            </CollapsibleSection>
          </div>
          <SidebarFooter userName={userName} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/conversation-list/ConversationList.tsx
git commit -m "feat(desktop): 组装 ConversationList 侧栏"
```

---

## Task 9: 首页样式

**Files:**
- Create: `renderer/styles/home.css`

- [ ] **Step 1: 创建 home.css**

```css
/* ─── Main Content (右侧主区) ─── */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--wb-bg-primary);
  position: relative;
}

/* ─── Home Page ─── */
.wb-home-page {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  padding: 32px 24px 48px;
  box-sizing: border-box;
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  scrollbar-width: none;
}

.wb-home-page::-webkit-scrollbar {
  display: none;
}

/* ─── Activity Banner (右上角悬浮) ─── */
.activity-banner {
  position: absolute;
  top: 16px;
  right: 24px;
  z-index: 10;
}

.activity-banner-button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  border: none;
  border-radius: var(--wb-radius-full);
  background: var(--wb-brand-primary);
  color: white;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  font-family: var(--wb-font-family);
  transition: background 0.15s ease;
}

.activity-banner-button:hover {
  background: var(--wb-palette-brand-7);
}

/* ─── Home Header (大标题) ─── */
.wb-home-header {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 96px;
  gap: 0;
  text-align: left;
  margin-bottom: 24px;
}

.wb-home-header__title,
.wb-home-header__subtitle {
  margin: 0;
  font-family: var(--wb-font-family);
  font-size: 36px;
  font-weight: 600;
  line-height: 48px;
  color: var(--wb-color-text-primary);
  letter-spacing: 0;
}

/* ─── Scene Tabs (场景标签) ─── */
.scene-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.scene-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  border-radius: var(--wb-radius-lg);
  font-size: 13px;
  font-family: var(--wb-font-family);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.scene-tab svg {
  width: 14px;
  height: 14px;
}

.scene-tab.selected {
  background: var(--wb-palette-black-100);
  color: var(--wb-palette-white-100);
}

.scene-tab:not(.selected) {
  background: var(--wb-bg-tertiary);
  color: var(--wb-color-text-primary);
}

.scene-tab:not(.selected):hover {
  background: var(--wb-palette-gray-5);
}

/* ─── GrowthBuddy (宠物通知) ─── */
.growth-buddy {
  position: absolute;
  right: 24px;
  top: 200px;
  z-index: 5;
  display: flex;
  align-items: flex-end;
  gap: 0;
}

.growth-buddy-bubble {
  position: relative;
  background: var(--wb-bg-primary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-xl);
  padding: 12px 14px;
  box-shadow: var(--wb-shadow-lg);
  max-width: 220px;
  margin-right: -8px;
}

.growth-buddy-bubble::after {
  content: "";
  position: absolute;
  right: -8px;
  bottom: 16px;
  width: 0;
  height: 0;
  border-top: 8px solid transparent;
  border-bottom: 8px solid transparent;
  border-left: 8px solid var(--wb-bg-primary);
}

.growth-buddy-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--wb-brand-primary);
  margin-bottom: 4px;
}

.growth-buddy-desc {
  font-size: 12px;
  color: var(--wb-color-text-secondary);
  line-height: 18px;
  margin-bottom: 8px;
}

.growth-buddy-action {
  display: inline-block;
  padding: 4px 10px;
  background: var(--wb-bg-primary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-lg);
  font-size: 12px;
  color: var(--wb-color-text-primary);
  cursor: pointer;
}

.growth-buddy-close {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--wb-color-text-tertiary);
  cursor: pointer;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--wb-radius-sm);
}

.growth-buddy-close:hover {
  background: var(--wb-bg-hover);
  color: var(--wb-color-text-primary);
}

.growth-buddy-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--wb-palette-black-100);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}

/* ─── Home Composer (快捷功能 + 输入区) ─── */
.wb-home-composer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.wb-home-composer__chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-action-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: var(--wb-radius-lg);
  background: var(--wb-bg-tertiary);
  color: var(--wb-color-text-primary);
  font-size: 12px;
  font-family: var(--wb-font-family);
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease;
}

.quick-action-chip:hover {
  background: var(--wb-palette-gray-5);
  transform: translateY(-1px);
}

.quick-action-chip svg {
  width: 14px;
  height: 14px;
}

/* ─── Chat Input (核心输入框) ─── */
.chat-input-container {
  background: var(--wb-bg-secondary);
  border: 1px solid var(--wb-border-default);
  border-radius: var(--wb-radius-2xl);
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-input-textarea {
  width: 100%;
  background: transparent;
  border: none;
  color: var(--wb-color-text-primary);
  font-size: 14px;
  font-family: var(--wb-font-family);
  resize: none;
  outline: none;
  line-height: 1.5;
  min-height: 24px;
}

.chat-input-textarea::placeholder {
  color: var(--wb-color-text-tertiary);
}

.chat-input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chat-input-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-input-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-input-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--wb-radius-lg);
  background: transparent;
  color: var(--wb-color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease, color 0.15s ease;
}

.chat-input-btn:hover {
  background: var(--wb-bg-hover);
  color: var(--wb-color-text-primary);
}

.chat-input-dropdown {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  border-radius: var(--wb-radius-lg);
  background: transparent;
  color: var(--wb-color-text-secondary);
  font-size: 12px;
  font-family: var(--wb-font-family);
  cursor: pointer;
}

.chat-input-dropdown:hover {
  background: var(--wb-bg-hover);
}

.chat-input-send {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--wb-radius-full);
  background: var(--wb-palette-black-100);
  color: var(--wb-palette-white-100);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s ease;
}

.chat-input-send:hover {
  opacity: 0.85;
}

.chat-input-send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.chat-input-abort {
  padding: 6px 14px;
  background: #F64041;
  color: white;
  border: none;
  border-radius: var(--wb-radius-lg);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--wb-font-family);
}

.chat-input-abort:hover {
  opacity: 0.9;
}

/* ─── Context Bar (底部上下文栏) ─── */
.context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding: 8px 16px;
  background: var(--wb-bg-secondary);
  border-radius: var(--wb-radius-2xl);
}

.context-bar-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--wb-color-text-secondary);
  font-size: 12px;
  font-family: var(--wb-font-family);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--wb-radius-lg);
}

.context-bar-item:hover {
  background: var(--wb-bg-hover);
  color: var(--wb-color-text-primary);
}

.context-bar-item svg {
  width: 14px;
  height: 14px;
}

/* ─── 窄屏适配 ─── */
@media (max-width: 640px) {
  .wb-home-page {
    padding: 24px 20px 32px;
    gap: 24px;
  }
  .wb-home-header__title,
  .wb-home-header__subtitle {
    font-size: 26px;
    line-height: 36px;
  }
  .growth-buddy {
    display: none;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/styles/home.css
git commit -m "feat(desktop): 添加首页样式"
```

---

## Task 10: 首页组件——HomeHeader + SceneTabs + GrowthBuddy

**Files:**
- Create: `renderer/components/home/HomeHeader.tsx`
- Create: `renderer/components/home/SceneTabs.tsx`
- Create: `renderer/components/home/GrowthBuddy.tsx`

- [ ] **Step 1: 创建 HomeHeader.tsx**

```tsx
type HomeMode = "working" | "coding" | "design";

const SUBTITLES: Record<HomeMode, string> = {
  working: "你的职场超能力",
  coding: "你的开发超能力",
  design: "你的设计超能力",
};

interface HomeHeaderProps {
  mode: HomeMode;
}

export function HomeHeader({ mode }: HomeHeaderProps) {
  return (
    <header className="wb-home-header">
      <h1 className="wb-home-header__title">xiaomei-brain</h1>
      <p className="wb-home-header__subtitle">{SUBTITLES[mode]}</p>
    </header>
  );
}
```

- [ ] **Step 2: 创建 SceneTabs.tsx**

```tsx
export type HomeMode = "working" | "coding" | "design";

interface SceneTabsProps {
  selected: HomeMode;
  onSelect: (mode: HomeMode) => void;
}

const TABS: { mode: HomeMode; label: string }[] = [
  { mode: "working", label: "日常办公" },
  { mode: "coding", label: "@代码开发" },
  { mode: "design", label: "@设计创意" },
];

export function SceneTabs({ selected, onSelect }: SceneTabsProps) {
  return (
    <div className="scene-tabs">
      {TABS.map((tab) => (
        <button
          key={tab.mode}
          className={`scene-tab ${selected === tab.mode ? "selected" : ""}`}
          onClick={() => onSelect(tab.mode)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: 创建 GrowthBuddy.tsx**

```tsx
import { useState } from "react";

interface GrowthBuddyProps {
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}

export function GrowthBuddy({
  title = "活动通知",
  description = "xiaomei-brain 新版本发布，快来体验记忆系统升级",
  actionText = "立即体验",
  onAction,
}: GrowthBuddyProps) {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <div className="growth-buddy">
      <div className="growth-buddy-bubble">
        <button
          className="growth-buddy-close"
          onClick={() => setVisible(false)}
        >
          ✕
        </button>
        <div className="growth-buddy-title">{title}</div>
        <div className="growth-buddy-desc">{description}</div>
        <button className="growth-buddy-action" onClick={onAction}>
          {actionText}
        </button>
      </div>
      <div className="growth-buddy-avatar">🐱</div>
    </div>
  );
}
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/home/HomeHeader.tsx \
        src/xiaomei_brain/desktop/renderer/components/home/SceneTabs.tsx \
        src/xiaomei_brain/desktop/renderer/components/home/GrowthBuddy.tsx
git commit -m "feat(desktop): 首页标题/场景标签/宠物通知组件"
```

---

## Task 11: 首页组件——QuickActions + ChatInput + ContextBar

**Files:**
- Create: `renderer/components/home/QuickActions.tsx`
- Create: `renderer/components/home/ChatInput.tsx`
- Create: `renderer/components/home/ContextBar.tsx`

- [ ] **Step 1: 创建 QuickActions.tsx**

```tsx
interface QuickAction {
  id: string;
  label: string;
  icon: React.ReactNode;
}

interface QuickActionsProps {
  onAction: (id: string) => void;
}

const ACTIONS: QuickAction[] = [
  {
    id: "doc",
    label: "文档处理",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
    ),
  },
  {
    id: "finance",
    label: "金融服务",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="1" x2="12" y2="23" />
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    ),
  },
  {
    id: "data",
    label: "数据分析及可视化",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="M7 16l4-6 4 4 5-8" />
      </svg>
    ),
  },
  {
    id: "more",
    label: "更多",
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
        <circle cx="5" cy="12" r="1" />
      </svg>
    ),
  },
];

export function QuickActions({ onAction }: QuickActionsProps) {
  return (
    <div className="wb-home-composer__chips">
      {ACTIONS.map((action) => (
        <button
          key={action.id}
          className="quick-action-chip"
          onClick={() => onAction(action.id)}
        >
          {action.icon}
          <span>{action.label}</span>
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 创建 ChatInput.tsx**

```tsx
import { useState, useRef } from "react";
import { useGateway } from "../hooks/useGateway";

interface ChatInputProps {
  gateway: ReturnType<typeof useGateway>;
}

export function ChatInput({ gateway }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;

    setInput("");
    setSending(true);
    await gateway.sendMessage(text);
    setSending(false);
    textareaRef.current?.focus();
  };

  const handleAbort = async () => {
    await gateway.abortMessage();
    setSending(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input-container">
      <textarea
        ref={textareaRef}
        className="chat-input-textarea"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="今天帮你做些什么？ @ 引用对话文件，/ 调用技能与指令"
        rows={2}
        disabled={gateway.conn.status !== "connected"}
      />
      <div className="chat-input-toolbar">
        <div className="chat-input-toolbar-left">
          <button className="chat-input-btn" title="添加附件">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
        </div>
        <div className="chat-input-toolbar-right">
          <button className="chat-input-dropdown" title="模式">
            自动 ▾
          </button>
          <button className="chat-input-btn" title="语音输入">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <line x1="12" y1="19" x2="12" y2="22" />
            </svg>
          </button>
          {sending ? (
            <button className="chat-input-abort" onClick={handleAbort}>
              中断
            </button>
          ) : (
            <button
              className="chat-input-send"
              onClick={handleSend}
              disabled={!input.trim() || gateway.conn.status !== "connected"}
              title="发送"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 创建 ContextBar.tsx**

```tsx
export function ContextBar() {
  return (
    <div className="context-bar">
      <button className="context-bar-item">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        <span>选择工作空间</span>
        <span>▾</span>
      </button>
      <button className="context-bar-item">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
        <span>默认权限</span>
        <span>▾</span>
      </button>
    </div>
  );
}
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/home/QuickActions.tsx \
        src/xiaomei_brain/desktop/renderer/components/home/ChatInput.tsx \
        src/xiaomei_brain/desktop/renderer/components/home/ContextBar.tsx
git commit -m "feat(desktop): 首页快捷功能/输入框/上下文栏组件"
```

---

## Task 12: 首页组件——HomeComposer + HomePage 组装

**Files:**
- Create: `renderer/components/home/HomeComposer.tsx`
- Create: `renderer/components/home/HomePage.tsx`

- [ ] **Step 1: 创建 HomeComposer.tsx**

```tsx
import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { ContextBar } from "./ContextBar";
import { useGateway } from "../../hooks/useGateway";

interface HomeComposerProps {
  gateway: ReturnType<typeof useGateway>;
}

export function HomeComposer({ gateway }: HomeComposerProps) {
  return (
    <div className="wb-home-composer">
      <QuickActions onAction={() => {}} />
      <ChatInput gateway={gateway} />
      <ContextBar />
    </div>
  );
}
```

- [ ] **Step 2: 创建 HomePage.tsx**

```tsx
import { useState } from "react";
import { useGateway } from "../../hooks/useGateway";
import { HomeHeader } from "./HomeHeader";
import { SceneTabs, HomeMode } from "./SceneTabs";
import { GrowthBuddy } from "./GrowthBuddy";
import { HomeComposer } from "./HomeComposer";

interface HomePageProps {
  gateway: ReturnType<typeof useGateway>;
}

export function HomePage({ gateway }: HomePageProps) {
  const [mode, setMode] = useState<HomeMode>("working");

  return (
    <div className="main-content">
      <div className="activity-banner">
        <button className="activity-banner-button">
          📈 做任务赢积分好礼 &gt;
        </button>
      </div>
      <div className="wb-home-page">
        <HomeHeader mode={mode} />
        <SceneTabs selected={mode} onSelect={setMode} />
        <GrowthBuddy />
        <HomeComposer gateway={gateway} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/home/HomeComposer.tsx \
        src/xiaomei_brain/desktop/renderer/components/home/HomePage.tsx
git commit -m "feat(desktop): 组装 HomePage 首页"
```

---

## Task 13: MainShell + App.tsx + 删除旧组件

**Files:**
- Create: `renderer/components/MainShell.tsx`
- Rewrite: `renderer/App.tsx`
- Delete: `renderer/components/TitleBar.tsx`, `ChatLayout.tsx`, `SessionList.tsx`, `ChatView.tsx`, `InputBar.tsx`, `MessageBubble.tsx`, `ToolPanel.tsx`

- [ ] **Step 1: 创建 MainShell.tsx**

```tsx
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { useGateway } from "../hooks/useGateway";

interface MainShellProps {
  gateway: ReturnType<typeof useGateway>;
}

export function MainShell({ gateway }: MainShellProps) {
  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage gateway={gateway} />
    </div>
  );
}
```

- [ ] **Step 2: 重写 App.tsx**

```tsx
import { useState } from "react";
import { useGateway } from "./hooks/useGateway";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";

export function App() {
  const gateway = useGateway();
  const [page, setPage] = useState<"connect" | "chat">("connect");

  const handleConnected = () => setPage("chat");

  return (
    <div className="app">
      <MenuBar />
      {page === "connect" ? (
        <ConnectPage gateway={gateway} onConnected={handleConnected} />
      ) : (
        <MainShell gateway={gateway} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: 删除旧组件**

删除以下文件：
- `renderer/components/TitleBar.tsx`
- `renderer/components/ChatLayout.tsx`
- `renderer/components/SessionList.tsx`
- `renderer/components/ChatView.tsx`
- `renderer/components/InputBar.tsx`
- `renderer/components/MessageBubble.tsx`
- `renderer/components/ToolPanel.tsx`

Run:
```bash
rm src/xiaomei_brain/desktop/renderer/components/TitleBar.tsx \
   src/xiaomei_brain/desktop/renderer/components/ChatLayout.tsx \
   src/xiaomei_brain/desktop/renderer/components/SessionList.tsx \
   src/xiaomei_brain/desktop/renderer/components/ChatView.tsx \
   src/xiaomei_brain/desktop/renderer/components/InputBar.tsx \
   src/xiaomei_brain/desktop/renderer/components/MessageBubble.tsx \
   src/xiaomei_brain/desktop/renderer/components/ToolPanel.tsx
```

- [ ] **Step 4: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误（旧文件删除后不应有残留引用）

- [ ] **Step 5: Commit**

```bash
git add -A src/xiaomei_brain/desktop/renderer/
git commit -m "feat(desktop): MainShell 组装 + App 路由重写 + 删除旧组件"
```

---

## Task 14: ConnectPage 样式 WorkBuddy 化

**Files:**
- Modify: `renderer/components/ConnectPage.tsx`

ConnectPage 的基础样式已在 `global.css` 中（Task 2），这里微调组件使其更贴合 WorkBuddy 风格。

- [ ] **Step 1: 微调 ConnectPage.tsx**

将标题改为 "xiaomei-brain" + 副标题，保持表单不变，但确保 className 与 global.css 一致。

替换 `renderer/components/ConnectPage.tsx` 全文：

```tsx
import { useState, useEffect } from "react";
import { useGateway } from "../hooks/useGateway";

interface Props {
  gateway: ReturnType<typeof useGateway>;
  onConnected: () => void;
}

export function ConnectPage({ gateway, onConnected }: Props) {
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("19766");
  const [token, setToken] = useState("");
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    window.gateway.getConfig("last_host").then((h) => {
      if (h) setHost(h as string);
    });
    window.gateway.getConfig("last_port").then((p) => {
      if (p) setPort(p as string);
    });
  }, []);

  const handleConnect = async () => {
    setLoading(true);
    const ok = await gateway.connect(host, parseInt(port) || 19766, token, userId);
    setLoading(false);
    if (ok) onConnected();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleConnect();
  };

  return (
    <div className="connect-page">
      <div className="connect-card">
        <h1>xiaomei-brain</h1>
        <p className="connect-subtitle">连接到 Gateway</p>

        <div className="connect-field">
          <label>地址</label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="localhost"
          />
        </div>

        <div className="connect-field">
          <label>端口</label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="19766"
          />
        </div>

        <div className="connect-field">
          <label>Token (可选)</label>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={handleKeyDown}
            type="password"
            placeholder="留空则跳过认证"
          />
        </div>

        <div className="connect-field">
          <label>用户身份 (可选)</label>
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入 user_id"
          />
        </div>

        {gateway.conn.error && (
          <p className="connect-error">{gateway.conn.error}</p>
        )}

        <button
          className="connect-btn"
          onClick={handleConnect}
          disabled={loading}
        >
          {loading ? "连接中..." : "连接"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/desktop/renderer/components/ConnectPage.tsx
git commit -m "feat(desktop): ConnectPage 样式 WorkBuddy 化"
```

---

## Task 15: 集成验证

- [ ] **Step 1: 完整 TypeScript 编译检查**

Run: `cd src/xiaomei_brain/desktop && npx tsc --noEmit -p tsconfig.main.json && npx tsc --noEmit -p tsconfig.renderer.json`
Expected: 无错误

- [ ] **Step 2: 构建检查**

Run: `cd src/xiaomei_brain/desktop && npm run build:renderer`
Expected: Vite 构建成功，输出到 `dist/renderer/`

- [ ] **Step 3: 清理根目录 WorkBuddy 参考文件**

删除项目根目录下之前提取的 WorkBuddy CSS/HTML 参考文件（已不再需要）：

```bash
rm -f agent-chat-pane-D_nLZw-_.css \
      cb-bridge-BQMqrgRE.css \
      claw-workspace-BLa-57Er.css \
      colleague-chat-page-CZvcZSKj.css \
      foundation-njGfaEke.css \
      index-B1I-AkRx.css \
      index.html \
      screenshot_test.png
```

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "feat(desktop): WorkBuddy 首页 UI 全仿完成 + 清理参考文件"
```

- [ ] **Step 5: 视觉验证（手动）**

启动 dev server 进行视觉验证：

```bash
cd src/xiaomei_brain/desktop && npm run dev
```

验证清单：
- [ ] 顶部菜单栏（Windows/Linux）显示 Logo + 菜单项 + 窗口控制按钮
- [ ] Mac 上菜单栏隐藏，侧栏 topbar 左侧留空避让红绿灯
- [ ] 左侧导航栏显示 Logo + 版本号 + 新建任务按钮 + 导航项 + 任务/空间历史 + 用户区
- [ ] 右侧首页显示大标题 + 场景标签 + 快捷功能 + 输入框 + 上下文栏
- [ ] 右上角活动入口按钮可见
- [ ] GrowthBuddy 宠物通知气泡显示在右侧
- [ ] 输入框可输入文字，Enter 发送
- [ ] 侧栏可折叠/展开
- [ ] 任务/空间 section 可折叠/展开

---

## Self-Review

### Spec coverage

| Spec 章节 | 对应 Task |
|---|---|
| 3. 设计 Token 系统 | Task 1 |
| 4. 顶部菜单栏 | Task 3 (窗口) + Task 4 (MenuBar) |
| 5. 左侧导航栏 | Task 5 (CSS) + Task 6-8 (组件) |
| 6. 右侧首页 | Task 9 (CSS) + Task 10-12 (组件) |
| 7. 组件架构 & 文件结构 | Task 13 (组装) |
| 8. Electron 主进程改动 | Task 3 |
| 9. 实现顺序 | Task 1-15 按序执行 |
| 10. 不在本次范围 | 未包含聊天工作区/多 Tab/产物抽屉/暗色切换交互/PracticeCases — 符合 |

### Placeholder scan

无 TBD/TODO，所有步骤包含完整代码。

### Type consistency

- `HomeMode` 类型在 `SceneTabs.tsx` 定义，在 `HomeHeader.tsx` 和 `HomePage.tsx` 引用 — 一致
- `useGateway` 返回类型在 `ChatInput.tsx`、`HomeComposer.tsx`、`HomePage.tsx`、`MainShell.tsx`、`ConnectPage.tsx` 中作为 `ReturnType<typeof useGateway>` 引用 — 一致
- `window.win` 接口在 `types.ts` 定义，在 `MenuBar.tsx` 使用 — 一致（`isMaximized` / `onMaximizeChange`）
