import { execFile } from "child_process";
import http from "http";
import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { promisify } from "util";
import { RuntimeManager } from "./runtime-manager";

const execFileAsync = promisify(execFile);
const SERVICE_ENDPOINTS: Record<string, string> = {
  embedding: "http://127.0.0.1:18765",
  tts_voxcpm: "http://127.0.0.1:18766",
  stt: "http://127.0.0.1:18767",
  voiceprint: "http://127.0.0.1:18768",
  face: "http://127.0.0.1:18769",
};

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

export type LocalAIServiceAction = "start" | "stop" | "restart" | "download" | "cancel-download";

export interface LocalAIModelOption {
  id: string;
  name: string;
  source: string;
  expected_size: string;
  expected_size_bytes: number;
  downloaded_bytes: number;
  model_present: boolean;
  recommended_device: string;
  supported_devices: string[];
}

export interface LocalAIServiceStatus {
  id: "embedding" | "stt" | "tts_voxcpm" | "voiceprint" | "face";
  name: string;
  description: string;
  model: string;
  selected_model_id: string;
  models: LocalAIModelOption[];
  selection_locked: boolean;
  selection_lock_reason: string;
  selected_device: "auto" | "cpu" | "cuda";
  supported_devices: Array<"auto" | "cpu" | "cuda">;
  expected_size: string;
  endpoint: string;
  required: boolean;
  controllable: boolean;
  downloadable: boolean;
  installed: boolean;
  missing_dependencies: string[];
  model_present: boolean;
  model_path: string;
  expected_size_bytes: number;
  downloaded_bytes: number;
  download_progress: number;
  state: "online" | "starting" | "downloading" | "not_installed" | "download_error" | "stopped" | "unavailable" | "available" | "error";
  pid?: number | null;
  started_at: string;
  device: string;
  health: Record<string, unknown>;
  memory_bytes: number;
  system_memory_total_bytes: number;
  gpu_memory_bytes: number;
  gpu_memory_total_bytes: number;
  error: string;
  log_path: string;
  download_log_path: string;
}

export interface LocalAISystemStatus {
  cpu_percent: number;
  memory_percent: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  gpus: Array<{
    name: string;
    utilization_percent: number;
    memory_used_bytes: number;
    memory_total_bytes: number;
  }>;
}

export interface LocalAIDownloadProgress {
  serviceId: string;
  modelId: string;
  progress: number;
  completed: boolean;
  failed: boolean;
  error: string;
}

export interface LocalAIStartupState {
  serviceId: string;
  online: boolean;
  running: boolean;
  pid: number | null;
  failed: boolean;
  error: string;
}

interface CommandEnvelope<T> {
  ok: boolean;
  result?: T;
  error?: string;
}

export class LocalAIRuntimeManager {
  private snapshotPromise: Promise<{ services: LocalAIServiceStatus[]; system: LocalAISystemStatus }> | null = null;
  private snapshotCache: { services: LocalAIServiceStatus[]; system: LocalAISystemStatus } | null = null;

  constructor(private readonly runtime: RuntimeManager) {}

  async snapshot(): Promise<{ services: LocalAIServiceStatus[]; system: LocalAISystemStatus }> {
    // Desktop startup and the settings page can request the same expensive
    // inventory at nearly the same time. Share that work instead of spawning
    // two Python processes and scanning every model cache twice.
    if (this.snapshotPromise) return this.snapshotPromise;
    this.snapshotPromise = this.invoke<{ services: LocalAIServiceStatus[]; system: LocalAISystemStatus }>(["list"])
      .then(async (snapshot) => {
        this.snapshotCache = snapshot;
        await this.writeSnapshotCache(snapshot);
        return snapshot;
      })
      .finally(() => {
        this.snapshotPromise = null;
      });
    return this.snapshotPromise;
  }

  async cachedSnapshot(): Promise<{ services: LocalAIServiceStatus[]; system?: LocalAISystemStatus } | null> {
    let cached = this.snapshotCache;
    if (!cached) {
      try {
        const value = JSON.parse(await fs.readFile(this.snapshotCachePath(), "utf8")) as {
          services?: LocalAIServiceStatus[];
          system?: LocalAISystemStatus;
        };
        if (!Array.isArray(value.services) || !value.system) return null;
        cached = { services: value.services, system: value.system };
        this.snapshotCache = cached;
      } catch {
        return null;
      }
    }

    // Cached model metadata makes the cards available immediately, but live
    // process and load fields must never be copied from the previous run.
    const services = await Promise.all(cached.services.map(async (service) => {
      const runtime = await this.startupState(service.id);
      const downloadRunning = await this.downloadIsRunning(service.id);
      let state: LocalAIServiceStatus["state"];
      let error = "";
      if (runtime.online) {
        state = "online";
      } else if (runtime.running) {
        state = "starting";
      } else if (downloadRunning) {
        state = "downloading";
      } else if (runtime.failed) {
        state = "error";
        error = runtime.error;
      } else if (!service.installed) {
        state = "unavailable";
        error = service.error;
      } else if (service.downloadable && !service.model_present) {
        state = "not_installed";
      } else if (!service.controllable) {
        state = "available";
        error = service.error;
      } else {
        state = "stopped";
      }
      return {
        ...service,
        state,
        pid: runtime.pid,
        started_at: runtime.running ? service.started_at : "",
        health: {},
        memory_bytes: 0,
        system_memory_total_bytes: 0,
        gpu_memory_bytes: 0,
        gpu_memory_total_bytes: 0,
        error,
      };
    }));
    // CPU/GPU load is deliberately omitted until the background refresh.
    return { services };
  }

  async list(): Promise<LocalAIServiceStatus[]> {
    return (await this.snapshot()).services;
  }

  async control(
    serviceId: string,
    action: LocalAIServiceAction,
    device?: "auto" | "cpu" | "cuda",
  ): Promise<LocalAIServiceStatus> {
    if (!/^[a-z0-9_]+$/.test(serviceId)) throw new Error("Invalid local AI service ID");
    const args = [action, serviceId];
    if ((action === "start" || action === "restart") && device) args.push("--device", device);
    return this.invoke<LocalAIServiceStatus>(args);
  }

  async readLog(serviceId: string): Promise<string> {
    if (!/^[a-z0-9_]+$/.test(serviceId)) throw new Error("Invalid local AI service ID");
    const result = await this.invoke<{ service: string; content: string }>(["log", serviceId]);
    return result.content || "";
  }

  async downloadProgress(serviceId: string, modelId: string): Promise<LocalAIDownloadProgress> {
    if (!/^[a-z0-9_]+$/.test(serviceId)) throw new Error("Invalid local AI service ID");
    if (!/^[a-z0-9._-]+$/.test(modelId)) throw new Error("Invalid local AI model ID");
    const runtimeDir = this.runtimeDirectory();
    const completionPath = path.join(runtimeDir, `${serviceId}.${modelId}.model.json`);
    try {
      const completion = JSON.parse(await fs.readFile(completionPath, "utf8")) as { model_path?: string };
      if (completion.model_path && await pathExists(completion.model_path)) {
        return { serviceId, modelId, progress: 100, completed: true, failed: false, error: "" };
      }
    } catch {
      // The completion record is written atomically only after all files exist.
    }

    const logPath = path.join(runtimeDir, `${serviceId}.download.log`);
    const metadataPath = path.join(runtimeDir, `${serviceId}.download.json`);
    const content = await this.readFileTail(logPath, 256 * 1024);
    const plain = content.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
    const weightMatches = [...plain.matchAll(/model\.safetensors:\s*(\d{1,3})%/g)];
    const aggregateMatches = [...plain.matchAll(/(?:Downloading|Fetching[^:]*):\s*(\d{1,3})%/g)];
    const matches = weightMatches.length ? weightMatches : aggregateMatches;
    const progress = matches.length
      ? Math.min(99, Number(matches.at(-1)?.[1] || 0))
      : 0;

    let pid = 0;
    try {
      const metadata = JSON.parse(await fs.readFile(metadataPath, "utf8")) as { pid?: number };
      pid = Number(metadata.pid || 0);
    } catch {
      // Missing metadata means the task did not start or has been cancelled.
    }
    let running = false;
    if (pid > 0) {
      try {
        process.kill(pid, 0);
        running = true;
      } catch (error) {
        running = (error as NodeJS.ErrnoException).code === "EPERM";
      }
    }
    const completed = plain.includes("Model download completed:");
    if (completed) {
      return { serviceId, modelId, progress: 100, completed: true, failed: false, error: "" };
    }
    const failed = pid > 0 && !running;
    const lines = plain.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const lastLine = lines.at(-1) || "";
    return {
      serviceId,
      modelId,
      progress,
      completed: false,
      failed,
      error: failed ? lastLine || "模型下载进程已意外退出" : "",
    };
  }

  async startupState(serviceId: string): Promise<LocalAIStartupState> {
    if (!/^[a-z0-9_]+$/.test(serviceId) || !SERVICE_ENDPOINTS[serviceId]) {
      throw new Error("Invalid local AI service ID");
    }
    if (await this.healthAvailable(SERVICE_ENDPOINTS[serviceId])) {
      return { serviceId, online: true, running: true, pid: null, failed: false, error: "" };
    }
    const runtimeDir = this.runtimeDirectory();
    let pid = 0;
    try {
      const metadata = JSON.parse(
        await fs.readFile(path.join(runtimeDir, `${serviceId}.json`), "utf8"),
      ) as { pid?: number };
      pid = Number(metadata.pid || 0);
    } catch {
      // The full status refresh will explain a missing runtime record.
    }
    const running = this.processIsRunning(pid);
    if (pid <= 0 || running) {
      return { serviceId, online: false, running, pid: running ? pid : null, failed: false, error: "" };
    }
    const log = await this.readFileTail(path.join(runtimeDir, `${serviceId}.log`), 32 * 1024);
    const lines = log.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    return {
      serviceId,
      online: false,
      running: false,
      pid: null,
      failed: true,
      error: lines.at(-1) || "模型服务进程已意外退出",
    };
  }

  private async downloadIsRunning(serviceId: string): Promise<boolean> {
    try {
      const metadata = JSON.parse(
        await fs.readFile(path.join(this.runtimeDirectory(), `${serviceId}.download.json`), "utf8"),
      ) as { pid?: number };
      return this.processIsRunning(Number(metadata.pid || 0));
    } catch {
      return false;
    }
  }

  async selectModel(serviceId: string, modelId: string): Promise<LocalAIServiceStatus> {
    if (!/^[a-z0-9_]+$/.test(serviceId)) throw new Error("Invalid local AI service ID");
    if (!/^[a-z0-9._-]+$/.test(modelId)) throw new Error("Invalid local AI model ID");
    return this.invoke<LocalAIServiceStatus>(["select", serviceId, modelId]);
  }

  async selectDevice(serviceId: string, device: "auto" | "cpu" | "cuda"): Promise<LocalAIServiceStatus> {
    if (!/^[a-z0-9_]+$/.test(serviceId)) throw new Error("Invalid local AI service ID");
    return this.invoke<LocalAIServiceStatus>(["select-device", serviceId, device]);
  }

  async ensureEmbedding(loadTimeoutMs = 180_000): Promise<LocalAIServiceStatus> {
    let services = await this.list();
    let embedding = services.find((item) => item.id === "embedding");
    if (!embedding) throw new Error("本机运行环境没有注册向量服务");
    if (embedding.state === "online") return embedding;
    if (!embedding.installed) throw new Error(embedding.error || "向量服务运行库尚未安装");
    if (!embedding.model_present) {
      throw new Error("请先在“设置 → 本机 AI 服务”中选择并下载向量模型");
    }
    if (embedding.state !== "starting") {
      embedding = await this.control("embedding", "start");
    }

    const deadline = Date.now() + loadTimeoutMs;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
      services = await this.list();
      embedding = services.find((item) => item.id === "embedding");
      if (!embedding) throw new Error("向量服务状态丢失");
      if (embedding.state === "online") return embedding;
      if (embedding.state === "unavailable" || embedding.state === "error" || embedding.state === "stopped") {
        const tail = await this.readLog("embedding").catch(() => "");
        const lastLine = tail.split(/\r?\n/).filter(Boolean).at(-1);
        throw new Error(lastLine || embedding.error || "向量服务启动失败");
      }
    }
    throw new Error("向量模型加载超时，请在本机 AI 服务中查看日志");
  }

  runtimeDirectory(): string {
    return path.join(os.homedir(), ".xiaomei-brain", "runtime", "ai-services");
  }

  private snapshotCachePath(): string {
    return path.join(this.runtimeDirectory(), "snapshot.json");
  }

  private async writeSnapshotCache(snapshot: {
    services: LocalAIServiceStatus[];
    system: LocalAISystemStatus;
  }): Promise<void> {
    try {
      await this.ensureRuntimeDirectory();
      const target = this.snapshotCachePath();
      const temporary = `${target}.${process.pid}.tmp`;
      await fs.writeFile(temporary, JSON.stringify(snapshot), "utf8");
      await fs.rename(temporary, target);
    } catch (error) {
      // A cache failure must never make service management unavailable.
      console.warn("[local-ai] failed to cache runtime snapshot", error);
    }
  }

  async ensureRuntimeDirectory(): Promise<string> {
    const directory = this.runtimeDirectory();
    await fs.mkdir(directory, { recursive: true });
    return directory;
  }

  private async readFileTail(filePath: string, maxBytes: number): Promise<string> {
    try {
      const handle = await fs.open(filePath, "r");
      try {
        const stat = await handle.stat();
        const length = Math.min(stat.size, maxBytes);
        const buffer = Buffer.alloc(length);
        await handle.read(buffer, 0, length, Math.max(0, stat.size - length));
        return buffer.toString("utf8");
      } finally {
        await handle.close();
      }
    } catch {
      return "";
    }
  }

  private processIsRunning(pid: number): boolean {
    if (pid <= 0) return false;
    try {
      process.kill(pid, 0);
      return true;
    } catch (error) {
      return (error as NodeJS.ErrnoException).code === "EPERM";
    }
  }

  private healthAvailable(endpoint: string): Promise<boolean> {
    return new Promise((resolve) => {
      const request = http.get(`${endpoint}/health`, (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      });
      request.setTimeout(800, () => {
        request.destroy();
        resolve(false);
      });
      request.once("error", () => resolve(false));
    });
  }

  private async invoke<T>(args: string[]): Promise<T> {
    const command = await this.runtime.buildCommand(["runtime-service", ...args]);
    try {
      const { stdout } = await execFileAsync(command.command, command.args, {
        cwd: command.cwd,
        env: command.env,
        windowsHide: true,
        timeout: 30_000,
        maxBuffer: 2 * 1024 * 1024,
        encoding: "utf8",
      });
      return this.parse<T>(stdout);
    } catch (error) {
      const detail = error as Error & { stdout?: string; stderr?: string };
      if (detail.stdout) {
        const parsed = this.tryParse<T>(detail.stdout);
        if (parsed) {
          if (parsed.ok && parsed.result !== undefined) return parsed.result;
          throw new Error(parsed.error || detail.message);
        }
      }
      throw new Error(detail.stderr?.trim() || detail.message);
    }
  }

  private parse<T>(output: string): T {
    const parsed = this.tryParse<T>(output);
    if (!parsed) throw new Error("本机 AI 运行服务返回了无效结果");
    if (!parsed.ok || parsed.result === undefined) throw new Error(parsed.error || "本机 AI 运行服务操作失败");
    return parsed.result;
  }

  private tryParse<T>(output: string): CommandEnvelope<T> | null {
    const lines = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      try {
        return JSON.parse(lines[index]) as CommandEnvelope<T>;
      } catch {
        // Some Python dependencies print startup notices before the JSON line.
      }
    }
    return null;
  }
}
