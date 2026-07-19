import { execFile } from "child_process";
import { promises as fs } from "fs";
import path from "path";
import { promisify } from "util";
import { app } from "electron";
import { ConfigStore } from "./config-store";

const execFileAsync = promisify(execFile);

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
  constructor(private readonly config: ConfigStore) {}

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
      const bundledCandidates = process.platform === "win32"
        ? [
            path.join(process.resourcesPath, "runtime", "xiaomei-agent.exe"),
            path.join(process.resourcesPath, "runtime", "python", "python.exe"),
          ]
        : [
            path.join(process.resourcesPath, "runtime", "xiaomei-agent"),
            path.join(process.resourcesPath, "runtime", "python", "bin", "python"),
          ];
      for (const candidate of bundledCandidates) {
        if (await isFile(candidate)) return descriptorForExecutable(candidate, "bundled");
      }
      throw new Error(`Bundled Agent runtime was not found under ${process.resourcesPath}`);
    }

    if (process.env.VIRTUAL_ENV) {
      const candidate = pythonExecutable(process.env.VIRTUAL_ENV);
      if (await isFile(candidate)) return descriptorForExecutable(candidate, "virtualenv");
    }

    return descriptorForExecutable(process.platform === "win32" ? "python.exe" : "python3", "path");
  }

  async control(agentId: string, action: AgentLifecycleAction): Promise<AgentLifecycleResult> {
    if (!/^[A-Za-z0-9_-]+$/.test(agentId)) {
      return { ok: false, action, agentId, message: "Invalid local Agent ID" };
    }

    try {
      const runtime = await this.resolve();
      const args = [...runtime.prefixArgs, action, agentId];
      const sourceRoot = path.resolve(__dirname, "../../../..");
      const pythonPath = app.isPackaged
        ? process.env.PYTHONPATH
        : [sourceRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);

      const { stdout, stderr } = await execFileAsync(runtime.executable, args, {
        windowsHide: true,
        timeout: 45_000,
        maxBuffer: 1024 * 1024,
        env: {
          ...process.env,
          PYTHONUTF8: "1",
          ...(pythonPath ? { PYTHONPATH: pythonPath } : {}),
        },
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
