import { execFile } from "child_process";
import { createHash } from "crypto";
import { createReadStream } from "fs";
import { promises as fs } from "fs";
import net from "net";
import os from "os";
import path from "path";
import { promisify } from "util";
import { app } from "electron";
import extract from "extract-zip";
import { ConfigStore } from "./config-store";

const execFileAsync = promisify(execFile);
const RUNTIME_LOCK_STALE_MS = 10 * 60 * 1000;
const RUNTIME_LOCK_WAIT_MS = 5 * 60 * 1000;

interface RuntimePackageManifest {
  schemaVersion: number;
  component: string;
  agentVersion: string;
  archive: string;
  archiveSha256: string;
  runtimeFileCount: number;
}

export type AgentLifecycleAction = "start" | "stop" | "restart";

export interface RuntimeDescriptor {
  executable: string;
  prefixArgs: string[];
  source: "environment" | "config" | "virtualenv" | "bundled" | "path";
}

export interface AgentLifecycleResult {
  ok: boolean;
  action: AgentLifecycleAction;
  agentId: string;
  message: string;
  runtimeSource?: RuntimeDescriptor["source"];
}

export interface AgentCreationResult {
  ok: boolean;
  name: string;
  description: string;
  message: string;
  agentId?: string;
  port?: number;
  runtimeSource?: RuntimeDescriptor["source"];
}

function pythonExecutable(venvDir: string): string {
  return process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");
}

async function isFile(filePath: string): Promise<boolean> {
  try {
    return (await fs.stat(filePath)).isFile();
  } catch {
    return false;
  }
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function canListen(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolve(true));
    });
  });
}

async function renameWithRetry(source: string, destination: string): Promise<void> {
  const deadline = Date.now() + 60_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      await fs.rename(source, destination);
      return;
    } catch (error) {
      lastError = error;
      const code = (error as NodeJS.ErrnoException).code;
      if (!new Set(["EPERM", "EBUSY", "EACCES"]).has(code ?? "")) throw error;
      await sleep(1_000);
    }
  }
  throw lastError;
}

function sha256File(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const input = createReadStream(filePath);
    input.on("error", reject);
    input.on("data", (chunk) => hash.update(chunk));
    input.on("end", () => resolve(hash.digest("hex")));
  });
}

function runtimeStorageRoot(): string {
  if (process.env.XIAOMEI_BRAIN_RUNTIME_HOME) {
    return path.resolve(process.env.XIAOMEI_BRAIN_RUNTIME_HOME);
  }
  if (process.platform === "win32" && process.env.LOCALAPPDATA) {
    return path.join(process.env.LOCALAPPDATA, "xiaomei-brain", "runtimes");
  }
  return path.join(app.getPath("userData"), "runtimes");
}

async function readRuntimeManifest(manifestPath: string): Promise<RuntimePackageManifest> {
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8")) as RuntimePackageManifest;
  if (
    manifest.schemaVersion !== 2
    || manifest.component !== "agent-runtime"
    || !manifest.agentVersion
    || path.basename(manifest.archive) !== manifest.archive
    || !/^[a-f0-9]{64}$/i.test(manifest.archiveSha256)
  ) {
    throw new Error(`Invalid bundled Runtime manifest: ${manifestPath}`);
  }
  return manifest;
}

function descriptorForExecutable(
  executable: string,
  source: RuntimeDescriptor["source"],
): RuntimeDescriptor {
  const basename = path.basename(executable).toLowerCase();
  const isPython = basename === "python" || basename === "python.exe" || basename.startsWith("python3");
  return {
    executable,
    prefixArgs: isPython ? ["-m", "xiaomei_brain"] : [],
    source,
  };
}

export class RuntimeManager {
  private bundledRuntimePromise?: Promise<RuntimeDescriptor>;

  constructor(private readonly config: ConfigStore) {}

  private async isPreparedRuntime(
    runtimeDir: string,
    manifest: RuntimePackageManifest,
  ): Promise<boolean> {
    const python = path.join(runtimeDir, "python", process.platform === "win32" ? "python.exe" : "bin/python");
    const readyPath = path.join(runtimeDir, ".runtime-ready.json");
    if (!await isFile(python) || !await isFile(readyPath)) return false;
    try {
      const ready = JSON.parse(await fs.readFile(readyPath, "utf8")) as {
        agentVersion?: string;
        archiveSha256?: string;
      };
      return ready.agentVersion === manifest.agentVersion
        && ready.archiveSha256 === manifest.archiveSha256;
    } catch {
      return false;
    }
  }

  private async acquireRuntimeLock(
    lockPath: string,
    runtimeDir: string,
    manifest: RuntimePackageManifest,
  ): Promise<Awaited<ReturnType<typeof fs.open>> | null> {
    const deadline = Date.now() + RUNTIME_LOCK_WAIT_MS;
    while (Date.now() < deadline) {
      try {
        const handle = await fs.open(lockPath, "wx");
        await handle.writeFile(JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }));
        return handle;
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code !== "EEXIST") throw error;
        if (await this.isPreparedRuntime(runtimeDir, manifest)) return null;
        try {
          const lockStat = await fs.stat(lockPath);
          if (Date.now() - lockStat.mtimeMs > RUNTIME_LOCK_STALE_MS) {
            await fs.rm(lockPath, { force: true });
            continue;
          }
        } catch (statError) {
          if ((statError as NodeJS.ErrnoException).code !== "ENOENT") throw statError;
        }
        await sleep(500);
      }
    }
    throw new Error(`Timed out waiting for bundled Runtime initialization: ${runtimeDir}`);
  }

  private async initializeBundledRuntime(): Promise<RuntimeDescriptor> {
    const packageDir = path.join(process.resourcesPath, "runtime-package");
    const manifestPath = path.join(packageDir, "runtime-manifest.json");
    const manifest = await readRuntimeManifest(manifestPath);
    const archivePath = path.join(packageDir, manifest.archive);
    if (!await isFile(archivePath)) {
      throw new Error(`Bundled Runtime archive was not found: ${archivePath}`);
    }

    const safeVersion = manifest.agentVersion.replace(/[^A-Za-z0-9._-]/g, "-");
    const runtimeName = `${safeVersion}-${manifest.archiveSha256.slice(0, 12)}`;
    const storageRoot = runtimeStorageRoot();
    const runtimeDir = path.join(storageRoot, runtimeName);
    const python = path.join(runtimeDir, "python", process.platform === "win32" ? "python.exe" : "bin/python");
    if (await this.isPreparedRuntime(runtimeDir, manifest)) {
      return descriptorForExecutable(python, "bundled");
    }

    await fs.mkdir(storageRoot, { recursive: true });
    const lockPath = path.join(storageRoot, `.${runtimeName}.lock`);
    const lockHandle = await this.acquireRuntimeLock(lockPath, runtimeDir, manifest);
    if (lockHandle === null) return descriptorForExecutable(python, "bundled");

    const stagingDir = path.join(storageRoot, `.${runtimeName}.staging-${process.pid}-${Date.now()}`);
    try {
      if (await this.isPreparedRuntime(runtimeDir, manifest)) {
        return descriptorForExecutable(python, "bundled");
      }

      const actualSha256 = await sha256File(archivePath);
      if (actualSha256.toLowerCase() !== manifest.archiveSha256.toLowerCase()) {
        throw new Error(`Bundled Runtime checksum mismatch: ${archivePath}`);
      }

      await fs.mkdir(stagingDir, { recursive: true });
      console.info(`[runtime] extracting ${manifest.archive} to ${runtimeDir}`);
      await extract(archivePath, { dir: stagingDir });

      const stagingPython = path.join(
        stagingDir,
        "python",
        process.platform === "win32" ? "python.exe" : "bin/python",
      );
      if (!await isFile(stagingPython)) {
        throw new Error(`Extracted Runtime does not contain Python: ${stagingPython}`);
      }

      await execFileAsync(stagingPython, [
        "-c",
        "import fastapi, lancedb, numpy, pyarrow, xiaomei_brain; print('runtime ready')",
      ], {
        windowsHide: true,
        timeout: 60_000,
        maxBuffer: 1024 * 1024,
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" },
      });

      await fs.writeFile(
        path.join(stagingDir, "runtime-manifest.json"),
        `${JSON.stringify(manifest, null, 2)}\n`,
        "utf8",
      );
      await fs.writeFile(
        path.join(stagingDir, ".runtime-ready.json"),
        `${JSON.stringify({
          agentVersion: manifest.agentVersion,
          archiveSha256: manifest.archiveSha256,
          preparedAt: new Date().toISOString(),
        }, null, 2)}\n`,
        "utf8",
      );

      await fs.rm(runtimeDir, { recursive: true, force: true });
      await renameWithRetry(stagingDir, runtimeDir);
      console.info(`[runtime] ready at ${runtimeDir}`);
      return descriptorForExecutable(python, "bundled");
    } finally {
      await fs.rm(stagingDir, { recursive: true, force: true });
      await lockHandle.close();
      await fs.rm(lockPath, { force: true });
    }
  }

  private prepareBundledRuntime(): Promise<RuntimeDescriptor> {
    if (!this.bundledRuntimePromise) {
      this.bundledRuntimePromise = this.initializeBundledRuntime().catch((error) => {
        this.bundledRuntimePromise = undefined;
        throw error;
      });
    }
    return this.bundledRuntimePromise;
  }

  async warmup(): Promise<void> {
    if (app.isPackaged) await this.resolve();
  }

  async resolve(): Promise<RuntimeDescriptor> {
    const fromEnvironment = process.env.XIAOMEI_BRAIN_RUNTIME || process.env.XIAOMEI_BRAIN_PYTHON;
    if (fromEnvironment) {
      if (!await isFile(fromEnvironment)) {
        throw new Error(`Configured runtime does not exist: ${fromEnvironment}`);
      }
      return descriptorForExecutable(fromEnvironment, "environment");
    }

    const configured = this.config.get("runtime_path");
    if (configured) {
      if (!await isFile(configured)) {
        throw new Error(`Desktop runtime path does not exist: ${configured}`);
      }
      return descriptorForExecutable(configured, "config");
    }

    if (app.isPackaged) {
      const standaloneCandidates = process.platform === "win32"
        ? [
            path.join(process.resourcesPath, "runtime", "xiaomei-agent.exe"),
          ]
        : [
            path.join(process.resourcesPath, "runtime", "xiaomei-agent"),
          ];
      for (const candidate of standaloneCandidates) {
        if (await isFile(candidate)) return descriptorForExecutable(candidate, "bundled");
      }

      const packageManifest = path.join(process.resourcesPath, "runtime-package", "runtime-manifest.json");
      if (await isFile(packageManifest)) return this.prepareBundledRuntime();

      const legacyPython = process.platform === "win32"
        ? path.join(process.resourcesPath, "runtime", "python", "python.exe")
        : path.join(process.resourcesPath, "runtime", "python", "bin", "python");
      if (await isFile(legacyPython)) return descriptorForExecutable(legacyPython, "bundled");
      throw new Error(`Bundled Agent runtime was not found under ${process.resourcesPath}`);
    }

    if (process.env.VIRTUAL_ENV) {
      const candidate = pythonExecutable(process.env.VIRTUAL_ENV);
      if (await isFile(candidate)) return descriptorForExecutable(candidate, "virtualenv");
    }

    return descriptorForExecutable(process.platform === "win32" ? "python.exe" : "python3", "path");
  }

  private commandEnvironment(): NodeJS.ProcessEnv {
    const sourceRoot = path.resolve(__dirname, "../../../..");
    const pythonPath = app.isPackaged
      ? process.env.PYTHONPATH
      : [sourceRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
    return {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONUTF8: "1",
      ...(pythonPath ? { PYTHONPATH: pythonPath } : {}),
    };
  }

  private async nextAgentId(displayName: string): Promise<string> {
    const normalized = displayName
      .normalize("NFKD")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "employee";
    const baseDir = path.join(os.homedir(), ".xiaomei-brain");
    let candidate = normalized;
    let suffix = 2;
    while (await pathExists(path.join(baseDir, candidate))) {
      candidate = `${normalized}-${suffix}`;
      suffix += 1;
    }
    return candidate;
  }

  private async nextGatewayPort(): Promise<number> {
    const baseDir = path.join(os.homedir(), ".xiaomei-brain");
    const reserved = new Set<number>();
    try {
      const entries = await fs.readdir(baseDir, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        try {
          const config = JSON.parse(await fs.readFile(path.join(baseDir, entry.name, "config.json"), "utf8")) as {
            ws_port?: unknown;
            admin_port?: unknown;
          };
          let wsPort = Number(config.ws_port);
          if (!Number.isInteger(wsPort) || wsPort <= 0 || wsPort > 65535) {
            const brain = await fs.readFile(path.join(baseDir, entry.name, "brain.yaml"), "utf8").catch(() => "");
            wsPort = Number(brain.match(/^\s*ws_port:\s*(\d+)/m)?.[1]);
          }
          for (const value of [wsPort, config.admin_port, Number.isInteger(wsPort) ? wsPort + 1 : undefined]) {
            const port = Number(value);
            if (Number.isInteger(port) && port > 0 && port <= 65535) reserved.add(port);
          }
        } catch {
          // Agents without a JSON config do not reserve a Desktop-managed port.
        }
      }
    } catch {
      // The Agent root is created by the backend command when needed.
    }

    for (let port = 19766; port <= 65534; port += 2) {
      if (reserved.has(port) || reserved.has(port + 1)) continue;
      if (await canListen(port) && await canListen(port + 1)) return port;
    }
    throw new Error("No available local Agent port pair was found");
  }

  async createAgent(displayName: string, description: string): Promise<AgentCreationResult> {
    const name = displayName.trim();
    const role = description.trim();
    if (!name || name.length > 80) {
      return { ok: false, name, description: role, message: "Agent name must be between 1 and 80 characters" };
    }
    if (!role || role.length > 500) {
      return { ok: false, name, description: role, message: "Agent responsibility must be between 1 and 500 characters" };
    }

    try {
      const runtime = await this.resolve();
      const agentId = await this.nextAgentId(name);
      const port = await this.nextGatewayPort();
      const args = [
        ...runtime.prefixArgs,
        "agent", "create", agentId,
        "--display-name", name,
        "--description", role,
        "--ws-port", String(port),
      ];
      const { stdout, stderr } = await execFileAsync(runtime.executable, args, {
        windowsHide: true,
        timeout: 45_000,
        maxBuffer: 1024 * 1024,
        env: this.commandEnvironment(),
      });
      const message = [stdout, stderr].map((value) => value.trim()).filter(Boolean).join("\n");
      return {
        ok: true,
        name,
        description: role,
        agentId,
        port,
        message: message || `Agent ${name} created`,
        runtimeSource: runtime.source,
      };
    } catch (error) {
      const detail = error as Error & { stdout?: string; stderr?: string };
      const message = [detail.stderr, detail.stdout, detail.message]
        .map((value) => value?.trim())
        .filter(Boolean)
        .join("\n");
      return { ok: false, name, description: role, message: message || String(error) };
    }
  }

  async control(agentId: string, action: AgentLifecycleAction): Promise<AgentLifecycleResult> {
    if (!/^[A-Za-z0-9_-]+$/.test(agentId)) {
      return { ok: false, action, agentId, message: "Invalid local Agent ID" };
    }

    try {
      const runtime = await this.resolve();
      const args = [...runtime.prefixArgs, action, agentId];
      const { stdout, stderr } = await execFileAsync(runtime.executable, args, {
        windowsHide: true,
        timeout: 45_000,
        maxBuffer: 1024 * 1024,
        env: this.commandEnvironment(),
      });
      const message = [stdout, stderr].map((value) => value.trim()).filter(Boolean).join("\n");
      return {
        ok: true,
        action,
        agentId,
        message: message || `${action} completed`,
        runtimeSource: runtime.source,
      };
    } catch (error) {
      const detail = error as Error & { stdout?: string; stderr?: string };
      const message = [detail.stderr, detail.stdout, detail.message]
        .map((value) => value?.trim())
        .filter(Boolean)
        .join("\n");
      return { ok: false, action, agentId, message: message || String(error) };
    }
  }
}
