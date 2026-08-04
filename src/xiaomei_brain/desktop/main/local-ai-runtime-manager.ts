import { execFile } from "child_process";
import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { promisify } from "util";
import { RuntimeManager } from "./runtime-manager";

const execFileAsync = promisify(execFile);

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

interface CommandEnvelope<T> {
  ok: boolean;
  result?: T;
  error?: string;
}

export class LocalAIRuntimeManager {
  constructor(private readonly runtime: RuntimeManager) {}

  async snapshot(): Promise<{ services: LocalAIServiceStatus[]; system: LocalAISystemStatus }> {
    return this.invoke<{ services: LocalAIServiceStatus[]; system: LocalAISystemStatus }>(["list"]);
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
