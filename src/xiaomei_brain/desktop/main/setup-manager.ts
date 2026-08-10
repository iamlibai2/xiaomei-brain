import { execFile, spawn } from "child_process";
import { createHash } from "crypto";
import { promises as fs } from "fs";
import path from "path";
import { promisify } from "util";
import { app, BrowserWindow } from "electron";
import extract from "extract-zip";
import { ConfigStore } from "./config-store";
import { RuntimeManager } from "./runtime-manager";

const execFileAsync = promisify(execFile);
const TORCH_VERSION = "2.6.0";
const TORCH_INDEX = {
  cpu: "https://download.pytorch.org/whl/cpu",
  cuda: "https://download.pytorch.org/whl/cu124",
} as const;
const FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
const FFMPEG_SHA256_URL = `${FFMPEG_URL}.sha256`;

export type InferenceVariant = "cpu" | "cuda";

export interface FirstRunSetupStatus {
  requiredReady: boolean;
  inference: {
    ready: boolean;
    variant: InferenceVariant | "unknown";
    torchVersion: string;
    cudaAvailable: boolean;
  };
  ffmpeg: { ready: boolean; path: string };
  gpu: { detected: boolean; name: string };
}

function componentsRoot(): string {
  if (process.env.XIAOMEI_BRAIN_COMPONENT_HOME) {
    return path.resolve(process.env.XIAOMEI_BRAIN_COMPONENT_HOME);
  }
  const base = process.platform === "win32" && process.env.LOCALAPPDATA
    ? process.env.LOCALAPPDATA
    : app.getPath("userData");
  return path.join(base, "xiaomei-brain", "components");
}

function requirementsPath(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, "setup", "ai-runtime-requirements.txt")
    : path.resolve(__dirname, "../../ai-runtime-requirements.txt");
}

function optionalServicesPath(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, "setup", "optional-ai-services.json")
    : path.resolve(__dirname, "../../optional-ai-services.json");
}

async function isFile(candidate: string): Promise<boolean> {
  try { return (await fs.stat(candidate)).isFile(); } catch { return false; }
}

export class SetupManager {
  constructor(
    private readonly runtime: RuntimeManager,
    private readonly config: ConfigStore,
    private readonly getWindow: () => BrowserWindow | null,
  ) {}

  async status(): Promise<FirstRunSetupStatus> {
    const command = await this.runtime.buildPythonCommand([]);
    let inference: FirstRunSetupStatus["inference"] = {
      ready: false, variant: "unknown", torchVersion: "", cudaAvailable: false,
    };
    const markerPath = path.join(componentsRoot(), "inference.json");
    try {
      const marker = JSON.parse(await fs.readFile(markerPath, "utf8")) as FirstRunSetupStatus["inference"] & { python?: string };
      if (marker.ready && marker.python === command.command) inference = marker;
      else throw new Error("stale inference marker");
    } catch {
      try {
      const { stdout } = await execFileAsync(command.command, [
        ...command.args,
        "-c",
        "import json, modelscope, sentence_transformers, torch; print(json.dumps({'version': torch.__version__, 'cuda': torch.cuda.is_available(), 'build': torch.version.cuda}))",
      ], { cwd: command.cwd, env: command.env, windowsHide: true, timeout: 20_000 });
      const value = JSON.parse(stdout.trim().split(/\r?\n/).at(-1) || "{}") as {
        version?: string; cuda?: boolean; build?: string | null;
      };
      inference = {
        ready: true,
        variant: value.build ? "cuda" : "cpu",
        torchVersion: value.version || "",
        cudaAvailable: Boolean(value.cuda),
      };
        await fs.mkdir(path.dirname(markerPath), { recursive: true });
        await fs.writeFile(markerPath, JSON.stringify({ ...inference, python: command.command }, null, 2), "utf8");
      } catch { /* not installed yet */ }
    }

    const configuredFfmpeg = this.config.get("managed_ffmpeg_bin") || "";
    const ffmpegPath = configuredFfmpeg
      ? path.join(configuredFfmpeg, process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg")
      : "";
    let ffmpegReady = Boolean(ffmpegPath && await isFile(ffmpegPath));
    let resolvedFfmpegPath = ffmpegReady ? ffmpegPath : "";
    if (!ffmpegReady) {
      try {
        await execFileAsync(process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg", ["-version"], {
          windowsHide: true, timeout: 5_000,
        });
        ffmpegReady = true;
        resolvedFfmpegPath = "PATH";
      } catch { /* optional component is absent */ }
    }
    const gpu = await this.detectNvidiaGpu();
    return {
      requiredReady: inference.ready,
      inference,
      ffmpeg: { ready: ffmpegReady, path: resolvedFfmpegPath },
      gpu,
    };
  }

  async installInference(variant: InferenceVariant): Promise<FirstRunSetupStatus> {
    this.progress("inference", "installing", 5, "正在准备本机推理环境");
    const command = await this.runtime.buildPythonCommand([]);
    await this.run(command.command, [
      ...command.args, "-m", "pip", "install", "--disable-pip-version-check",
      "--upgrade", "--force-reinstall",
      `torch==${TORCH_VERSION}`, `torchaudio==${TORCH_VERSION}`,
      "--index-url", TORCH_INDEX[variant],
    ], command.cwd, command.env, "inference", 10, 62);
    await this.run(command.command, [
      ...command.args, "-m", "pip", "install", "--disable-pip-version-check",
      "--upgrade", "--requirement", requirementsPath(),
    ], command.cwd, command.env, "inference", 63, 96);
    await fs.rm(path.join(componentsRoot(), "inference.json"), { force: true });
    this.progress("inference", "complete", 100, "本机推理环境已安装");
    return this.status();
  }

  async installFfmpeg(): Promise<FirstRunSetupStatus> {
    if (process.platform !== "win32") throw new Error("当前仅实现 Windows FFmpeg 组件安装");
    const root = path.join(componentsRoot(), "ffmpeg");
    const archive = path.join(root, "ffmpeg-release-essentials.zip");
    const staging = path.join(root, `.staging-${process.pid}-${Date.now()}`);
    await fs.mkdir(root, { recursive: true });
    this.progress("ffmpeg", "downloading", 2, "正在下载 FFmpeg");
    const response = await fetch(FFMPEG_URL);
    if (!response.ok || !response.body) throw new Error(`FFmpeg 下载失败：HTTP ${response.status}`);
    const total = Number(response.headers.get("content-length") || 0);
    const handle = await fs.open(archive, "w");
    let received = 0;
    try {
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        await handle.write(value);
        received += value.byteLength;
        this.progress("ffmpeg", "downloading", total ? Math.min(85, Math.round(received * 85 / total)) : 35, "正在下载 FFmpeg");
      }
    } finally { await handle.close(); }
    const expectedHashResponse = await fetch(FFMPEG_SHA256_URL);
    if (!expectedHashResponse.ok) throw new Error(`无法校验 FFmpeg：HTTP ${expectedHashResponse.status}`);
    const expectedHash = (await expectedHashResponse.text()).trim().split(/\s+/)[0]?.toLowerCase();
    const actualHash = createHash("sha256").update(await fs.readFile(archive)).digest("hex");
    if (!expectedHash || !/^[a-f0-9]{64}$/.test(expectedHash) || actualHash !== expectedHash) {
      await fs.rm(archive, { force: true });
      throw new Error("FFmpeg 下载校验失败，请重试");
    }
    this.progress("ffmpeg", "installing", 88, "正在安装 FFmpeg");
    await fs.rm(staging, { recursive: true, force: true });
    await fs.mkdir(staging, { recursive: true });
    await extract(archive, { dir: staging });
    const entries = await fs.readdir(staging, { withFileTypes: true });
    const packageRoot = entries.find((item) => item.isDirectory());
    if (!packageRoot) throw new Error("FFmpeg 压缩包结构无效");
    const sourceBin = path.join(staging, packageRoot.name, "bin");
    if (!await isFile(path.join(sourceBin, "ffmpeg.exe")) || !await isFile(path.join(sourceBin, "ffprobe.exe"))) {
      throw new Error("FFmpeg 压缩包缺少 ffmpeg.exe 或 ffprobe.exe");
    }
    const installed = path.join(root, "current");
    await fs.rm(installed, { recursive: true, force: true });
    await fs.cp(sourceBin, path.join(installed, "bin"), { recursive: true });
    for (const name of ["LICENSE", "LICENSE.txt", "README.txt"]) {
      const source = path.join(staging, packageRoot.name, name);
      if (await isFile(source)) await fs.copyFile(source, path.join(installed, name));
    }
    this.config.set("managed_ffmpeg_bin", path.join(installed, "bin"));
    await fs.rm(staging, { recursive: true, force: true });
    await fs.rm(archive, { force: true });
    this.progress("ffmpeg", "complete", 100, "FFmpeg 已安装");
    return this.status();
  }

  async installOptionalService(serviceId: string): Promise<void> {
    const catalog = JSON.parse(await fs.readFile(optionalServicesPath(), "utf8")) as Record<string, { packages: string[] }>;
    const spec = catalog[serviceId];
    if (!spec) throw new Error(`没有可安装的本机服务组件：${serviceId}`);
    const command = await this.runtime.buildPythonCommand([]);
    const regular = spec.packages.filter((item) => !item.startsWith("face-recognition=="));
    if (regular.length) {
      await this.run(command.command, [
        ...command.args, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", ...regular,
      ], command.cwd, command.env, serviceId, 5, 94);
    }
    const noDeps = spec.packages.filter((item) => item.startsWith("face-recognition=="));
    if (noDeps.length) {
      await this.run(command.command, [
        ...command.args, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", ...noDeps,
      ], command.cwd, command.env, serviceId, 94, 99);
    }
    this.progress(serviceId, "complete", 100, "本机服务运行组件已安装");
  }

  private async detectNvidiaGpu(): Promise<{ detected: boolean; name: string }> {
    try {
      const { stdout } = await execFileAsync("nvidia-smi", ["--query-gpu=name", "--format=csv,noheader"], {
        windowsHide: true, timeout: 5_000,
      });
      const name = stdout.trim().split(/\r?\n/)[0] || "NVIDIA GPU";
      return { detected: true, name };
    } catch { return { detected: false, name: "" }; }
  }

  private run(
    executable: string, args: string[], cwd: string, env: NodeJS.ProcessEnv,
    component: string, from: number, to: number,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const child = spawn(executable, args, { cwd, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
      let tail = "";
      let lines = 0;
      const onData = (data: Buffer) => {
        const value = data.toString("utf8");
        tail = `${tail}${value}`.slice(-8_000);
        lines += value.split(/\r?\n/).length - 1;
        const progress = Math.min(to - 1, from + Math.round((to - from) * (1 - Math.exp(-lines / 80))));
        this.progress(component, "installing", progress, value.trim().split(/\r?\n/).at(-1) || "正在安装");
      };
      child.stdout.on("data", onData);
      child.stderr.on("data", onData);
      child.once("error", reject);
      child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(tail.trim() || `安装进程退出：${code}`)));
    });
  }

  private progress(component: string, state: string, percent: number, message: string): void {
    this.getWindow()?.webContents.send("setup:progress", { component, state, percent, message });
  }
}
