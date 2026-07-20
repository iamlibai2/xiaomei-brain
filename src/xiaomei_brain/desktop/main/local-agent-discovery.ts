import { promises as fs } from "fs";
import type { Dirent } from "fs";
import net from "net";
import os from "os";
import path from "path";

export interface LocalAgentInfo {
  agentId: string;
  name: string;
  description?: string;
  host: string;
  port: number;
  online: boolean;
  pid?: number;
  startedAt?: string;
}

interface LocalAgentConfig {
  name?: unknown;
  description?: unknown;
  ws_port?: unknown;
}

const LOCAL_HOST = "127.0.0.1";
const PORT_PROBE_TIMEOUT_MS = 500;

function validPort(value: unknown): number | null {
  const port = typeof value === "number" ? value : Number(value);
  return Number.isInteger(port) && port > 0 && port <= 65535 ? port : null;
}

function extractIdentityName(identity: string): string | null {
  const selfIntroduction = identity.match(/你(?:是|叫)([^，,。\s]+)/);
  if (selfIntroduction?.[1]) return selfIntroduction[1].trim();

  const lines = identity.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const heading = lines[index].match(/^#\s+(.+)$/)?.[1]?.trim();
    if (!heading) continue;

    if (["名字", "名称", "Name"].includes(heading)) {
      for (let next = index + 1; next < lines.length; next += 1) {
        const value = lines[next].trim();
        if (!value) continue;
        if (value.startsWith("#")) break;
        return value;
      }
      continue;
    }

    const reserved = new Set([
      "出生", "性格", "擅长", "不擅长", "学习兴趣", "阶段目标", "身份",
      "追求", "热爱", "底线", "种子", "生长记录", "Birth", "Personality",
      "Skills", "Weaknesses", "Identity", "Work Principles", "Phase Goal",
    ]);
    if (!reserved.has(heading)) return heading;
  }
  return null;
}

async function readJson(filePath: string): Promise<LocalAgentConfig> {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8")) as LocalAgentConfig;
  } catch {
    return {};
  }
}

async function readIdentityName(agentDir: string): Promise<string | null> {
  const candidates = [
    path.join(agentDir, "identity.md"),
    path.join(agentDir, "consciousness", "identity.md"),
  ];
  for (const candidate of candidates) {
    try {
      return extractIdentityName(await fs.readFile(candidate, "utf8"));
    } catch {
      // Try the next supported identity location.
    }
  }
  return null;
}

async function readBrainYamlPort(agentDir: string): Promise<number | null> {
  try {
    const content = await fs.readFile(path.join(agentDir, "brain.yaml"), "utf8");
    return validPort(content.match(/^\s*ws_port:\s*(-?\d+)/m)?.[1]);
  } catch {
    return null;
  }
}

async function readPidInfo(agentDir: string): Promise<{ pid?: number; startedAt?: string }> {
  try {
    const data = JSON.parse(await fs.readFile(path.join(agentDir, "agent.pid"), "utf8")) as {
      pid?: unknown;
      started_at?: unknown;
    };
    if (!Number.isInteger(data.pid) || (data.pid as number) <= 0) return {};
    try {
      process.kill(data.pid as number, 0);
    } catch {
      return {};
    }
    return {
      pid: data.pid as number,
      startedAt: typeof data.started_at === "string" ? data.started_at : undefined,
    };
  } catch {
    return {};
  }
}

function probePort(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    let settled = false;

    const finish = (online: boolean) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(online);
    };

    socket.setTimeout(PORT_PROBE_TIMEOUT_MS);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

export async function discoverLocalAgents(baseDir = path.join(os.homedir(), ".xiaomei-brain")): Promise<LocalAgentInfo[]> {
  let entries: Dirent[];
  try {
    entries = await fs.readdir(baseDir, { withFileTypes: true });
  } catch {
    return [];
  }

  const discovered = await Promise.all(entries
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
    .map(async (entry): Promise<LocalAgentInfo | null> => {
      const agentDir = path.join(baseDir, entry.name);
      const config = await readJson(path.join(agentDir, "config.json"));
      const port = validPort(config.ws_port) ?? await readBrainYamlPort(agentDir);
      if (!port) return null;

      const configuredName = typeof config.name === "string" ? config.name.trim() : "";
      const name = configuredName || await readIdentityName(agentDir) || entry.name;
      const description = typeof config.description === "string" ? config.description.trim() : "";
      const pidInfo = await readPidInfo(agentDir);
      return {
        agentId: entry.name,
        name,
        ...(description ? { description } : {}),
        host: LOCAL_HOST,
        port,
        online: await probePort(LOCAL_HOST, port),
        ...pidInfo,
      };
    }));

  return discovered
    .filter((agent): agent is LocalAgentInfo => agent !== null)
    .sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
}
