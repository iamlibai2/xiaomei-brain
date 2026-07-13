import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { autoUpdater } from "electron-updater";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { registerIpcHandlers } from "./ipc-handlers";

const isMac = process.platform === "darwin";
const isWindows = process.platform === "win32";

let mainWindow: BrowserWindow | null = null;
const gateway = new GatewayClient();
const config = new ConfigStore();

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
  createWindow();
  registerIpcHandlers(gateway, config, () => mainWindow);

  // Auto-update: dev 环境跳过，打包后才生效
  if (!process.env.NODE_ENV || process.env.NODE_ENV !== "development") {
    autoUpdater.checkForUpdatesAndNotify();
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
