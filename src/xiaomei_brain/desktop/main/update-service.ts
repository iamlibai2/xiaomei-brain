import { app, BrowserWindow, ipcMain } from "electron";
import { promises as fs } from "fs";
import path from "path";
import {
  autoUpdater,
  type ProgressInfo,
  type UpdateInfo,
} from "electron-updater";
import { discoverLocalAgents } from "./local-agent-discovery";
import type { LocalAIRuntimeManager } from "./local-ai-runtime-manager";
import type { RuntimeManager } from "./runtime-manager";

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

interface AgentUpgradeRestoreRecord {
  schemaVersion: 1;
  agentIds: string[];
  createdAt: string;
}

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
  private installing = false;
  private startupTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly getWindow: WindowProvider,
    private readonly automaticCheckEnabled: () => boolean,
    private readonly runtimeManager: RuntimeManager,
    private readonly localAIRuntime: LocalAIRuntimeManager,
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

    // Once a check finds a new version, download it silently. Installing the
    // downloaded version remains an explicit action in the Desktop sidebar.
    autoUpdater.autoDownload = true;
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

    // An update stops only the local Agents that were running. Restore them
    // after the new Desktop starts; remote and already-stopped Agents are not
    // part of this host-local lifecycle.
    void this.restoreAgentsAfterUpgrade().catch((error) => {
      console.error(`[update] failed to restore local Agents: ${String(error)}`);
    });
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
    if (["checking", "available", "downloading", "downloaded"].includes(this.state.phase)) {
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

  async install(): Promise<DesktopUpdateState> {
    if (this.state.phase !== "downloaded" || this.installing) return this.snapshot();
    this.installing = true;
    try {
      await this.stopRunningAgentsForUpgrade();
    } catch (error) {
      this.installing = false;
      this.setState({ phase: "error", error: String(error), progress: undefined });
      return this.snapshot();
    }
    // A click on the upgrade action is the person's consent. Reuse the
    // existing installation directory and avoid showing a second installer
    // confirmation flow.
    setImmediate(() => autoUpdater.quitAndInstall(true, true));
    return this.snapshot();
  }

  private get agentRestorePath(): string {
    return path.join(app.getPath("userData"), "update-agent-restore.json");
  }

  private async writeAgentRestoreRecord(record: AgentUpgradeRestoreRecord): Promise<void> {
    const destination = this.agentRestorePath;
    await fs.mkdir(path.dirname(destination), { recursive: true });
    const temporary = `${destination}.${process.pid}.tmp`;
    await fs.writeFile(temporary, JSON.stringify(record, null, 2), "utf8");
    await fs.rename(temporary, destination);
  }

  private async readAgentRestoreRecord(): Promise<AgentUpgradeRestoreRecord | null> {
    try {
      const value = JSON.parse(await fs.readFile(this.agentRestorePath, "utf8")) as Partial<AgentUpgradeRestoreRecord>;
      if (value.schemaVersion !== 1 || !Array.isArray(value.agentIds)) return null;
      const agentIds = value.agentIds.filter((item): item is string => (
        typeof item === "string" && /^[A-Za-z0-9_-]+$/.test(item)
      ));
      return {
        schemaVersion: 1,
        agentIds: [...new Set(agentIds)],
        createdAt: typeof value.createdAt === "string" ? value.createdAt : "",
      };
    } catch {
      return null;
    }
  }

  private async stopRunningAgentsForUpgrade(): Promise<void> {
    const running = (await discoverLocalAgents()).filter((agent) => Boolean(agent.pid));
    if (running.length === 0) {
      await fs.rm(this.agentRestorePath, { force: true });
      return;
    }

    await this.writeAgentRestoreRecord({
      schemaVersion: 1,
      agentIds: running.map((agent) => agent.agentId),
      createdAt: new Date().toISOString(),
    });

    for (const agent of running) {
      const result = await this.runtimeManager.control(agent.agentId, "stop");
      if (!result.ok) {
        console.warn(`[update] failed to stop local Agent ${agent.agentId}: ${result.message}`);
      }
    }
  }

  private async restoreAgentsAfterUpgrade(): Promise<void> {
    const record = await this.readAgentRestoreRecord();
    if (!record || record.agentIds.length === 0) return;

    try {
      await this.localAIRuntime.ensureEmbedding();
    } catch (error) {
      console.warn(`[update] shared embedding unavailable while restoring Agents: ${String(error)}`);
      return;
    }

    const currentlyRunning = new Set(
      (await discoverLocalAgents()).filter((agent) => Boolean(agent.pid)).map((agent) => agent.agentId),
    );
    const pending: string[] = [];
    for (const agentId of record.agentIds) {
      if (currentlyRunning.has(agentId)) continue;
      const result = await this.runtimeManager.control(agentId, "start");
      if (!result.ok) {
        pending.push(agentId);
        console.warn(`[update] failed to restore local Agent ${agentId}: ${result.message}`);
      }
    }

    if (pending.length === 0) {
      await fs.rm(this.agentRestorePath, { force: true });
      return;
    }
    await this.writeAgentRestoreRecord({ ...record, agentIds: pending });
  }

  private setState(patch: Partial<DesktopUpdateState>): void {
    this.state = { ...this.state, ...patch, currentVersion: app.getVersion() };
    const window = this.getWindow();
    if (window && !window.isDestroyed()) {
      window.webContents.send("desktop-update:state", this.snapshot());
    }
  }
}
