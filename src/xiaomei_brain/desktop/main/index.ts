import { app, BrowserWindow, ipcMain, shell } from "electron";
import { existsSync } from "fs";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { registerIpcHandlers } from "./ipc-handlers";
import { initializeDesktopDiagnostics, registerDesktopDiagnosticsIpc } from "./desktop-diagnostics";

const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";
const windowsAppId = "com.xiaomei.brain.desktop";

if (isWindows) {
  app.setAppUserModelId(windowsAppId);
}

let mainWindow: BrowserWindow | null = null;
const gateway = new GatewayClient();
const config = new ConfigStore();

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
  initializeDesktopDiagnostics();
  registerWindowsShortcutIdentity();
  createWindow();
  registerDesktopDiagnosticsIpc();
  registerIpcHandlers(gateway, config, () => mainWindow);

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
