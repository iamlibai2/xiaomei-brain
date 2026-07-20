import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync } from "node:fs";
import path from "node:path";
import { format } from "node:util";
import { app, ipcMain, shell } from "electron";

const MAX_LOG_SIZE = 5 * 1024 * 1024;
const LOG_TAIL_SIZE = 512 * 1024;
let initialized = false;

function logDirectory(): string {
  return path.join(app.getPath("userData"), "logs");
}

function logFile(): string {
  return path.join(logDirectory(), "desktop.log");
}

function rotateLogIfNeeded(filePath: string): void {
  if (!existsSync(filePath) || statSync(filePath).size < MAX_LOG_SIZE) return;
  const previousPath = `${filePath}.1`;
  try {
    if (existsSync(previousPath)) {
      unlinkSync(previousPath);
    }
    renameSync(filePath, previousPath);
  } catch (error) {
    // Logging must never prevent Desktop from starting.
    process.stderr.write(`[diagnostics] failed to rotate log: ${String(error)}\n`);
  }
}

function serialize(values: unknown[]): string {
  return format(...values.map((value) => value instanceof Error ? value.stack || value.message : value));
}

function append(level: string, values: unknown[]): void {
  try {
    appendFileSync(
      logFile(),
      `${new Date().toISOString()} [${level}] ${serialize(values)}\n`,
      "utf8",
    );
  } catch (error) {
    process.stderr.write(`[diagnostics] failed to write log: ${String(error)}\n`);
  }
}

export function initializeDesktopDiagnostics(): void {
  if (initialized) return;
  initialized = true;
  mkdirSync(logDirectory(), { recursive: true });
  rotateLogIfNeeded(logFile());

  for (const level of ["log", "info", "warn", "error"] as const) {
    const original = console[level].bind(console);
    console[level] = (...values: unknown[]) => {
      original(...values);
      append(level.toUpperCase(), values);
    };
  }

  console.info(
    `[desktop] starting v${app.getVersion()} (${app.isPackaged ? "packaged" : "development"}, ${process.platform} ${process.arch})`,
  );
}

function readLogTail(): string {
  const filePath = logFile();
  if (!existsSync(filePath)) return "";
  const contents = readFileSync(filePath);
  return contents.subarray(Math.max(0, contents.length - LOG_TAIL_SIZE)).toString("utf8");
}

async function openDirectory(directory: string): Promise<{ ok: boolean; error?: string }> {
  mkdirSync(directory, { recursive: true });
  const error = await shell.openPath(directory);
  return error ? { ok: false, error } : { ok: true };
}

export function registerDesktopDiagnosticsIpc(): void {
  ipcMain.handle("desktop:getInfo", async () => ({
    version: app.getVersion(),
    environment: app.isPackaged ? "production" : "development",
    platform: process.platform,
    arch: process.arch,
    electronVersion: process.versions.electron,
    nodeVersion: process.versions.node,
    configDirectory: app.getPath("userData"),
    agentDirectory: path.join(app.getPath("home"), ".xiaomei-brain"),
    logDirectory: logDirectory(),
    logFile: logFile(),
  }));

  ipcMain.handle("desktop:readLog", async () => ({ content: readLogTail() }));
  ipcMain.handle("desktop:openLogDirectory", async () => openDirectory(logDirectory()));
  ipcMain.handle("desktop:openConfigDirectory", async () => openDirectory(app.getPath("userData")));
}
