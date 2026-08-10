import { app, BrowserWindow, ipcMain } from "electron";
import {
  autoUpdater,
  type ProgressInfo,
  type UpdateInfo,
} from "electron-updater";

export type DesktopUpdatePhase =
  | "disabled"
  | "idle"
  | "checking"
  | "available"
  | "not_available"
  | "downloading"
  | "downloaded"
  | "error";

export interface DesktopUpdateState {
  phase: DesktopUpdatePhase;
  currentVersion: string;
  availableVersion?: string;
  checkedAt?: number;
  releaseNotes?: string;
  error?: string;
  progress?: {
    percent: number;
    transferred: number;
    total: number;
    bytesPerSecond: number;
  };
}

type WindowProvider = () => BrowserWindow | null;

function releaseNotesText(value: UpdateInfo["releaseNotes"]): string | undefined {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return undefined;
  const text = value
    .map((item) => item.note)
    .filter((item): item is string => typeof item === "string" && item.length > 0)
    .join("\n\n");
  return text || undefined;
}

function progressSnapshot(value: ProgressInfo): DesktopUpdateState["progress"] {
  return {
    percent: Math.max(0, Math.min(100, value.percent)),
    transferred: value.transferred,
    total: value.total,
    bytesPerSecond: value.bytesPerSecond,
  };
}

export class DesktopUpdateService {
  private state: DesktopUpdateState;
  private initialized = false;
  private startupTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly getWindow: WindowProvider,
    private readonly automaticCheckEnabled: () => boolean,
  ) {
    this.state = {
      phase: this.supported ? "idle" : "disabled",
      currentVersion: app.getVersion(),
    };
  }

  private get supported(): boolean {
    return process.platform === "win32"
      && (app.isPackaged || process.env.XIAOMEI_ENABLE_DEV_UPDATER === "1");
  }

  initialize(): void {
    if (this.initialized) return;
    this.initialized = true;

    if (!this.supported) {
      this.setState({ phase: "disabled" });
      return;
    }

    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.allowPrerelease = false;
    autoUpdater.logger = console;

    if (!app.isPackaged) {
      autoUpdater.forceDevUpdateConfig = true;
    }
    const customFeed = process.env.XIAOMEI_UPDATE_URL?.trim();
    if (customFeed) {
      autoUpdater.setFeedURL({ provider: "generic", url: customFeed });
    }

    autoUpdater.on("checking-for-update", () => {
      this.setState({ phase: "checking", error: undefined, progress: undefined });
    });
    autoUpdater.on("update-available", (info) => {
      this.setState({
        phase: "available",
        availableVersion: info.version,
        checkedAt: Date.now(),
        releaseNotes: releaseNotesText(info.releaseNotes),
        error: undefined,
        progress: undefined,
      });
    });
    autoUpdater.on("update-not-available", () => {
      this.setState({
        phase: "not_available",
        availableVersion: undefined,
        checkedAt: Date.now(),
        releaseNotes: undefined,
        error: undefined,
        progress: undefined,
      });
    });
    autoUpdater.on("download-progress", (progress) => {
      this.setState({
        phase: "downloading",
        progress: progressSnapshot(progress),
        error: undefined,
      });
    });
    autoUpdater.on("update-downloaded", (info) => {
      this.setState({
        phase: "downloaded",
        availableVersion: info.version,
        progress: { percent: 100, transferred: 0, total: 0, bytesPerSecond: 0 },
        error: undefined,
      });
    });
    autoUpdater.on("error", (error) => {
      console.error(`[update] ${error.stack || error.message}`);
      this.setState({ phase: "error", error: error.message, progress: undefined });
    });

    if (this.automaticCheckEnabled()) {
      this.startupTimer = setTimeout(() => {
        this.startupTimer = null;
        void this.check();
      }, 10_000);
    }
  }

  registerIpc(): void {
    ipcMain.handle("desktop-update:getState", async () => this.snapshot());
    ipcMain.handle("desktop-update:check", async () => this.check());
    ipcMain.handle("desktop-update:download", async () => this.download());
    ipcMain.handle("desktop-update:install", async () => this.install());
  }

  dispose(): void {
    if (this.startupTimer) clearTimeout(this.startupTimer);
    this.startupTimer = null;
  }

  snapshot(): DesktopUpdateState {
    return {
      ...this.state,
      progress: this.state.progress ? { ...this.state.progress } : undefined,
    };
  }

  async check(): Promise<DesktopUpdateState> {
    if (!this.supported) return this.snapshot();
    if (this.state.phase === "checking" || this.state.phase === "downloading") {
      return this.snapshot();
    }
    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      this.setState({ phase: "error", error: String(error), progress: undefined });
    }
    return this.snapshot();
  }

  async download(): Promise<DesktopUpdateState> {
    if (this.state.phase !== "available") return this.snapshot();
    this.setState({ phase: "downloading", error: undefined });
    try {
      await autoUpdater.downloadUpdate();
    } catch (error) {
      this.setState({ phase: "error", error: String(error), progress: undefined });
    }
    return this.snapshot();
  }

  install(): DesktopUpdateState {
    if (this.state.phase === "downloaded") {
      // NSIS replaces Desktop and restarts it. Agent processes are deliberately
      // not stopped here; they remain independent and reconnect after restart.
      setImmediate(() => autoUpdater.quitAndInstall(false, true));
    }
    return this.snapshot();
  }

  private setState(patch: Partial<DesktopUpdateState>): void {
    this.state = { ...this.state, ...patch, currentVersion: app.getVersion() };
    const window = this.getWindow();
    if (window && !window.isDestroyed()) {
      window.webContents.send("desktop-update:state", this.snapshot());
    }
  }
}
