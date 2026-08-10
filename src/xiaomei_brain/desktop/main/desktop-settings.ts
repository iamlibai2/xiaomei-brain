import { app, ipcMain } from "electron";
import type { ConfigStore } from "./config-store";

export type DesktopLanguage = "zh-CN" | "en-US";
export type CloseBehavior = "exit" | "minimize";
export type DesktopTheme = "system" | "light" | "dark";
export type MessageSound = "none" | "soft" | "crisp" | "bubble";
export type MessageFont = "default" | "pianpian" | "wanweiwei" | "honglei" | "ozcaramel";

export interface DesktopSettings {
  openAtLogin: boolean;
  openAtLoginAvailable: boolean;
  closeBehavior: CloseBehavior;
  notificationsEnabled: boolean;
  messageSound: MessageSound;
  messageFont: MessageFont;
  language: DesktopLanguage;
  theme: DesktopTheme;
  openRightSidebarByDefault: boolean;
  automaticUpdatesEnabled: boolean;
}

const KEYS = {
  openAtLogin: "desktop.openAtLogin",
  closeBehavior: "desktop.closeBehavior",
  notificationsEnabled: "desktop.notificationsEnabled",
  messageSound: "desktop.messageSound",
  messageFont: "desktop.messageFont",
  language: "desktop.language",
  theme: "desktop.theme",
  openRightSidebarByDefault: "desktop.openRightSidebarByDefault",
  automaticUpdatesEnabled: "desktop.automaticUpdatesEnabled",
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
  const theme = config.get(KEYS.theme);
  const messageSound = config.get(KEYS.messageSound);
  const messageFont = config.get(KEYS.messageFont);
  return {
    openAtLogin: readBoolean(config, KEYS.openAtLogin, false),
    openAtLoginAvailable: process.platform === "win32" || process.platform === "darwin",
    closeBehavior: closeBehavior === "minimize" ? "minimize" : "exit",
    notificationsEnabled: readBoolean(config, KEYS.notificationsEnabled, true),
    messageSound: messageSound === "none" || messageSound === "crisp" || messageSound === "bubble"
      ? messageSound
      : "soft",
    messageFont: messageFont === "pianpian" || messageFont === "wanweiwei" || messageFont === "honglei" || messageFont === "ozcaramel"
      ? messageFont
      : "default",
    language: language === "en-US" ? "en-US" : "zh-CN",
    theme: theme === "light" || theme === "dark" ? theme : "system",
    openRightSidebarByDefault: readBoolean(
      config,
      KEYS.openRightSidebarByDefault,
      false,
    ),
    automaticUpdatesEnabled: readBoolean(config, KEYS.automaticUpdatesEnabled, true),
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
    async (_event, patch: Partial<Omit<DesktopSettings, "openAtLoginAvailable">>) => {
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
      if (patch?.messageSound === "none" || patch?.messageSound === "soft" || patch?.messageSound === "crisp" || patch?.messageSound === "bubble") {
        config.set(KEYS.messageSound, patch.messageSound);
      }
      if (patch?.messageFont === "default" || patch?.messageFont === "pianpian" || patch?.messageFont === "wanweiwei" || patch?.messageFont === "honglei" || patch?.messageFont === "ozcaramel") {
        config.set(KEYS.messageFont, patch.messageFont);
      }
      if (patch?.language === "zh-CN" || patch?.language === "en-US") {
        config.set(KEYS.language, patch.language);
      }
      if (patch?.theme === "system" || patch?.theme === "light" || patch?.theme === "dark") {
        config.set(KEYS.theme, patch.theme);
      }
      if (typeof patch?.openRightSidebarByDefault === "boolean") {
        config.set(
          KEYS.openRightSidebarByDefault,
          String(patch.openRightSidebarByDefault),
        );
      }
      if (typeof patch?.automaticUpdatesEnabled === "boolean") {
        config.set(KEYS.automaticUpdatesEnabled, String(patch.automaticUpdatesEnabled));
      }
      return { ok: true, settings: readDesktopSettings(config) };
    },
  );
}
