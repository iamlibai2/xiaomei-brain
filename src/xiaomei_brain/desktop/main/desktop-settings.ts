import { app, ipcMain } from "electron";
import type { ConfigStore } from "./config-store";

export type DesktopLanguage = "zh-CN" | "en-US";
export type CloseBehavior = "exit" | "minimize";

export interface DesktopSettings {
  openAtLogin: boolean;
  openAtLoginAvailable: boolean;
  closeBehavior: CloseBehavior;
  notificationsEnabled: boolean;
  language: DesktopLanguage;
  openRightSidebarByDefault: boolean;
  automaticUpdates: {
    state: "disabled";
    message: string;
  };
}

const KEYS = {
  openAtLogin: "desktop.openAtLogin",
  closeBehavior: "desktop.closeBehavior",
  notificationsEnabled: "desktop.notificationsEnabled",
  language: "desktop.language",
  openRightSidebarByDefault: "desktop.openRightSidebarByDefault",
} as const;

function readBoolean(config: ConfigStore, key: string, fallback: boolean): boolean {
  const value = config.get(key);
  if (value === "true") return true;
  if (value === "false") return false;
  return fallback;
}

export function readDesktopSettings(config: ConfigStore): DesktopSettings {
  const closeBehavior = config.get(KEYS.closeBehavior);
  const language = config.get(KEYS.language);
  return {
    openAtLogin: readBoolean(config, KEYS.openAtLogin, false),
    openAtLoginAvailable: process.platform === "win32" || process.platform === "darwin",
    closeBehavior: closeBehavior === "minimize" ? "minimize" : "exit",
    notificationsEnabled: readBoolean(config, KEYS.notificationsEnabled, true),
    language: language === "en-US" ? "en-US" : "zh-CN",
    openRightSidebarByDefault: readBoolean(
      config,
      KEYS.openRightSidebarByDefault,
      false,
    ),
    automaticUpdates: {
      state: "disabled",
      message: "正式更新服务尚未启用，Desktop 不会自动检查更新。",
    },
  };
}

function applyOpenAtLogin(enabled: boolean): void {
  if (process.platform !== "win32" && process.platform !== "darwin") return;
  app.setLoginItemSettings({
    openAtLogin: enabled,
    path: process.execPath,
    args: app.isPackaged ? [] : [app.getAppPath()],
  });
}

export function applyStoredDesktopSettings(config: ConfigStore): void {
  const settings = readDesktopSettings(config);
  if (settings.openAtLoginAvailable) {
    try {
      applyOpenAtLogin(settings.openAtLogin);
    } catch (error) {
      console.warn(`[settings] failed to apply startup preference: ${String(error)}`);
    }
  }
}

export function registerDesktopSettingsIpc(config: ConfigStore): void {
  ipcMain.handle("desktop:getSettings", async () => readDesktopSettings(config));
  ipcMain.handle(
    "desktop:updateSettings",
    async (_event, patch: Partial<Omit<DesktopSettings, "openAtLoginAvailable" | "automaticUpdates">>) => {
      const current = readDesktopSettings(config);

      if (typeof patch?.openAtLogin === "boolean") {
        if (!current.openAtLoginAvailable) {
          return { ok: false, error: "当前系统暂不支持开机启动设置。" };
        }
        try {
          applyOpenAtLogin(patch.openAtLogin);
          config.set(KEYS.openAtLogin, String(patch.openAtLogin));
        } catch (error) {
          return { ok: false, error: `设置开机启动失败：${String(error)}` };
        }
      }
      if (patch?.closeBehavior === "exit" || patch?.closeBehavior === "minimize") {
        config.set(KEYS.closeBehavior, patch.closeBehavior);
      }
      if (typeof patch?.notificationsEnabled === "boolean") {
        config.set(KEYS.notificationsEnabled, String(patch.notificationsEnabled));
      }
      if (patch?.language === "zh-CN" || patch?.language === "en-US") {
        config.set(KEYS.language, patch.language);
      }
      if (typeof patch?.openRightSidebarByDefault === "boolean") {
        config.set(
          KEYS.openRightSidebarByDefault,
          String(patch.openRightSidebarByDefault),
        );
      }
      return { ok: true, settings: readDesktopSettings(config) };
    },
  );
}
