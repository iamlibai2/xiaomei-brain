import { app, BrowserWindow, ipcMain, Menu, session, shell, type MenuItemConstructorOptions } from "electron";
import { existsSync } from "fs";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { registerIpcHandlers } from "./ipc-handlers";
import { initializeDesktopDiagnostics, registerDesktopDiagnosticsIpc } from "./desktop-diagnostics";
import {
  applyStoredDesktopSettings,
  readDesktopSettings,
  registerDesktopSettingsIpc,
} from "./desktop-settings";

const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";
const useDevelopmentRenderer = !app.isPackaged && process.argv.includes("--dev-renderer");
const windowsAppId = "com.xiaomei.brain.desktop";
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

if (isWindows) {
  app.setAppUserModelId(windowsAppId);
}

let mainWindow: BrowserWindow | null = null;
let isQuitting = false;
const gateway = new GatewayClient();
const config = new ConfigStore();

async function loadDevelopmentRenderer(window: BrowserWindow): Promise<void> {
  const rendererUrl = "http://localhost:5173";
  let lastError: unknown;
  // `npm run dev` starts Electron and Vite concurrently.  Wait briefly for
  // Vite instead of falling back to a stale production bundle in dist/.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      await window.loadURL(rendererUrl);
      return;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  console.error(`[desktop] development renderer unavailable: ${String(lastError)}`);
  await window.loadURL(
    `data:text/plain;charset=utf-8,${encodeURIComponent("Desktop 开发服务启动失败，请确认 Vite 正在运行。")}`,
  );
}

function registerWindowsShortcutIdentity(): void {
  if (!isWindows) return;

  const isDevelopment = !app.isPackaged;
  const shortcutPath = path.join(
    app.getPath("appData"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    isDevelopment ? "xiaomei-brain Development.lnk" : "xiaomei-brain.lnk",
  );
  const shortcutArgs = isDevelopment ? `"${app.getAppPath()}"` : "";
  const shortcutDetails: Electron.ShortcutDetails = {
    target: process.execPath,
    args: shortcutArgs,
    description: isDevelopment
      ? "xiaomei-brain Desktop development client"
      : "xiaomei-brain Desktop client",
    appUserModelId: windowsAppId,
    icon: process.execPath,
    iconIndex: 0,
  };

  let operation: "create" | "update" = "create";
  if (existsSync(shortcutPath)) {
    operation = "update";
    try {
      const current = shell.readShortcutLink(shortcutPath);
      const sameTarget = path.resolve(current.target).toLowerCase() === path.resolve(process.execPath).toLowerCase();
      if (
        sameTarget
        && current.appUserModelId === windowsAppId
        && (current.args || "") === shortcutArgs
      ) {
        return;
      }
    } catch (error) {
      console.warn(`[shortcut] failed to inspect ${shortcutPath}: ${error}`);
    }
  }

  const registered = shell.writeShortcutLink(shortcutPath, operation, shortcutDetails);
  if (!registered) {
    console.warn(`[shortcut] failed to register ${shortcutPath}`);
  }
}

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
    },
    ...!isMac && !isWindows && {
      frame: false,
    },
  });

  mainWindow.on("ready-to-show", () => {
    mainWindow?.show();
  });

  mainWindow.on("close", (event) => {
    if (!isQuitting && readDesktopSettings(config).closeBehavior === "minimize") {
      event.preventDefault();
      mainWindow?.minimize();
    }
  });

  mainWindow.webContents.on("context-menu", (_event, params) => {
    const template: MenuItemConstructorOptions[] = [];
    if (params.isEditable) {
      template.push(
        { label: "撤销", role: "undo", enabled: params.editFlags.canUndo },
        { label: "重做", role: "redo", enabled: params.editFlags.canRedo },
        { type: "separator" },
        { label: "剪切", role: "cut", enabled: params.editFlags.canCut },
        { label: "复制", role: "copy", enabled: params.editFlags.canCopy },
        { label: "粘贴", role: "paste", enabled: params.editFlags.canPaste },
        { type: "separator" },
        { label: "全选", role: "selectAll", enabled: params.editFlags.canSelectAll },
      );
    } else {
      template.push(
        { label: "复制", role: "copy", enabled: Boolean(params.selectionText) },
        { label: "全选", role: "selectAll" },
      );
    }
    Menu.buildFromTemplate(template).popup({ window: mainWindow || undefined });
  });

  if (useDevelopmentRenderer) {
    void loadDevelopmentRenderer(mainWindow);
  } else {
    void mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
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
  ipcMain.on("window:quit", () => app.quit());
  ipcMain.handle("window:isMaximized", () => mainWindow?.isMaximized() ?? false);
  ipcMain.handle("window:setFullScreen", (event, enabled: unknown) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window || typeof enabled !== "boolean") return false;
    window.setFullScreen(enabled);
    return window.isFullScreen();
  });

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
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback) => {
      const source = webContents.getURL();
      const trustedRenderer = source.startsWith("file://")
        || source.startsWith("http://localhost:5173");
      callback(trustedRenderer && permission === "media");
    },
  );
  initializeDesktopDiagnostics();
  applyStoredDesktopSettings(config);
  registerWindowsShortcutIdentity();
  createWindow();
  registerDesktopDiagnosticsIpc();
  registerDesktopSettingsIpc(config);
  registerIpcHandlers(gateway, config, () => mainWindow);

});

app.on("before-quit", () => {
  isQuitting = true;
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
