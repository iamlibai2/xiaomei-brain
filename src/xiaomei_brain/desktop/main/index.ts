import { app, BrowserWindow, ipcMain, shell } from "electron";
import { existsSync } from "fs";
import path from "path";
import { autoUpdater } from "electron-updater";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { registerIpcHandlers } from "./ipc-handlers";

const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";
const windowsAppId = "com.xiaomei.brain.desktop";

if (isWindows) {
  app.setAppUserModelId(windowsAppId);
}

let mainWindow: BrowserWindow | null = null;
const gateway = new GatewayClient();
const config = new ConfigStore();

function registerDevelopmentNotificationIdentity(): void {
  if (!isWindows || app.isPackaged) return;

  const shortcutPath = path.join(
    app.getPath("appData"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "xiaomei-brain Development.lnk",
  );
  const shortcutDetails: Electron.ShortcutDetails = {
    target: process.execPath,
    description: "Electron development runtime for xiaomei-brain",
    appUserModelId: windowsAppId,
    icon: process.execPath,
    iconIndex: 0,
  };
  const operation = existsSync(shortcutPath) ? "update" : "create";
  const registered = shell.writeShortcutLink(shortcutPath, operation, shortcutDetails);
  if (!registered) {
    console.warn(`[notification] failed to register development shortcut: ${shortcutPath}`);
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
  registerDevelopmentNotificationIdentity();
  createWindow();
  registerIpcHandlers(gateway, config, () => mainWindow);

  // Auto-update: dev 环境跳过，打包后才生效
  const updateConfig = path.join(process.resourcesPath, "app-update.yml");
  if (
    (!process.env.NODE_ENV || process.env.NODE_ENV !== "development")
    && existsSync(updateConfig)
  ) {
    void autoUpdater.checkForUpdatesAndNotify().catch((error) => {
      console.error("[updater] update check failed", error);
    });
  }
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
