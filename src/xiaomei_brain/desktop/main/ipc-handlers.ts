import { ipcMain, BrowserWindow, Notification, app, dialog, shell } from "electron";
import { createHash, randomUUID } from "crypto";
import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { TerminalManager } from "./terminal-manager";
import { discoverLocalAgents } from "./local-agent-discovery";
import { AgentLifecycleAction, RuntimeManager } from "./runtime-manager";
import { sanitizeNotificationText } from "./notification-text";
import { IdentityVault } from "./identity-vault";
import { LocalAIRuntimeManager, type LocalAIServiceAction } from "./local-ai-runtime-manager";

const connections = new Map<string, GatewayClient>();
const connectionSessions = new Map<string, string>();
const connectionReady = new Map<string, boolean>();
const connectionSessionSwitchers = new Map<
  string,
  (sessionId: string) => Promise<Record<string, unknown>>
>();
const activeNotifications = new Set<Notification>();
const attachmentCache = new Map<string, {
  id: string; name: string; mimeType: string; size: number; kind: string; dataBase64: string;
}>();
const artifactCache = new Map<string, {
  id: string; name: string; mimeType: string; size: number; kind: string; description: string; dataBase64: string;
}>();

function invalidateArtifactCache(
  agentId: string,
  data?: unknown,
): void {
  const value = data && typeof data === "object" && !Array.isArray(data)
    ? data as Record<string, unknown>
    : null;
  const sessionId = value && typeof value.session_id === "string" ? value.session_id : "";
  const artifactId = value && typeof value.id === "string" ? value.id : "";
  if (sessionId && artifactId) {
    artifactCache.delete(`${agentId}\u0000${sessionId}\u0000${artifactId}`);
    return;
  }
  const prefix = `${agentId}\u0000`;
  for (const key of artifactCache.keys()) {
    if (key.startsWith(prefix)) artifactCache.delete(key);
  }
}
const inspectedCapabilityPackages = new Map<string, {
  filePath: string;
  sha256: string;
}>();
const MAX_CACHED_ATTACHMENTS = 32;
const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_VIDEO_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const MAX_VIDEO_TOTAL_ATTACHMENT_BYTES = 32 * 1024 * 1024;
// Conversation documents remain limited by the Agent. Generated video clips
// have a larger server-side allowance and still pass exact metadata checks.
const MAX_ARTIFACT_BYTES = 128 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_CAPABILITY_PACKAGE_BYTES = 8 * 1024 * 1024;
const IMAGE_MIMES: Record<string, string> = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
};
const VIDEO_MIMES: Record<string, string> = {
  ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
  ".webm": "video/webm", ".mkv": "video/x-matroska",
  ".avi": "video/x-msvideo", ".mpeg": "video/mpeg", ".mpg": "video/mpeg",
};
const TEXT_EXTENSIONS = new Set([
  ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml", ".toml",
  ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts",
  ".tsx", ".py", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp",
  ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".sql", ".sh", ".bash", ".zsh",
  ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".conf", ".log",
]);
const OFFICE_MIMES: Record<string, string> = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".pdf": "application/pdf",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

async function ensureImmutableCacheFile(cachePath: string, data: Buffer): Promise<void> {
  try {
    const existing = await fs.stat(cachePath);
    if (existing.isFile() && existing.size === data.length) return;
    throw new Error("Cached file does not match the immutable Agent snapshot");
  } catch (error) {
    if ((error as { code?: string }).code !== "ENOENT") throw error;
  }
  try {
    await fs.writeFile(cachePath, data, { flag: "wx" });
  } catch (error) {
    // Two clicks can race to materialize the same immutable snapshot. The
    // winner's complete file is safe to reuse and must not be overwritten.
    if ((error as { code?: string }).code !== "EEXIST") throw error;
    const existing = await fs.stat(cachePath);
    if (!existing.isFile() || existing.size !== data.length) throw error;
  }
}

export function registerIpcHandlers(
  _gateway: GatewayClient,
  config: ConfigStore,
  getWindow: () => BrowserWindow | null
): void {
  const terminalMgr = new TerminalManager();
  const runtimeManager = new RuntimeManager(config);
  const localAIRuntime = new LocalAIRuntimeManager(runtimeManager);
  const identityVault = new IdentityVault();
  let desktopDeviceId = config.get("desktop_device_id") || "";
  if (!desktopDeviceId) {
    desktopDeviceId = randomUUID();
    config.set("desktop_device_id", desktopDeviceId);
  }
  const registerDesktopEmbodiment = async (client: GatewayClient) => client.rpc(
    "embodiment.register",
    {
      device_id: desktopDeviceId,
      label: `${os.hostname()} Desktop`,
      capabilities: ["hearing", "speech", "vision"],
      allow_proactive_use: false,
    },
  );
  void runtimeManager.warmup().catch((error) => {
    console.error("[runtime] background initialization failed", error);
  });
  // A fresh installation must let the person choose an embedding model before
  // the first download. Existing installations still start their cached model
  // automatically so normal Desktop startup remains unchanged.
  void localAIRuntime.list().then((services) => {
    const embedding = services.find((item) => item.id === "embedding");
    if (embedding?.model_present) return localAIRuntime.ensureEmbedding();
    return undefined;
  }).catch((error) => {
    console.error("[local-ai] embedding initialization failed", error);
  });

  ipcMain.handle("localAI:list", async () => {
    try {
      return { ok: true, ...(await localAIRuntime.snapshot()) };
    } catch (error) {
      return { ok: false, services: [], error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:cachedList", async () => {
    try {
      const snapshot = await localAIRuntime.cachedSnapshot();
      return snapshot ? { ok: true, ...snapshot } : { ok: true, services: [] };
    } catch (error) {
      return { ok: false, services: [], error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:control", async (_event, args: {
    serviceId: string;
    action: LocalAIServiceAction;
    device?: "auto" | "cpu" | "cuda";
  }) => {
    try {
      return {
        ok: true,
        service: await localAIRuntime.control(args.serviceId, args.action, args.device || "auto"),
      };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:selectModel", async (_event, args: { serviceId: string; modelId: string }) => {
    try {
      return { ok: true, service: await localAIRuntime.selectModel(args.serviceId, args.modelId) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:selectDevice", async (_event, args: {
    serviceId: string;
    device: "auto" | "cpu" | "cuda";
  }) => {
    try {
      return { ok: true, service: await localAIRuntime.selectDevice(args.serviceId, args.device) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:readLog", async (_event, args: { serviceId: string }) => {
    try {
      return { ok: true, content: await localAIRuntime.readLog(args.serviceId) };
    } catch (error) {
      return { ok: false, content: "", error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:downloadProgress", async (_event, args: { serviceId: string; modelId: string }) => {
    try {
      return {
        ok: true,
        progress: await localAIRuntime.downloadProgress(args.serviceId, args.modelId),
      };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:startupState", async (_event, args: { serviceId: string }) => {
    try {
      return { ok: true, state: await localAIRuntime.startupState(args.serviceId) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("localAI:openDirectory", async () => {
    try {
      const result = await shell.openPath(await localAIRuntime.ensureRuntimeDirectory());
      return result ? { ok: false, error: result } : { ok: true };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });

  ipcMain.handle("identity:status", async () => {
    try {
      return identityVault.status();
    } catch (error) {
      return {
        exists: true,
        unlocked: false,
        activeSubject: "",
        accounts: [],
        error: String(error instanceof Error ? error.message : error),
      };
    }
  });
  ipcMain.handle(
    "identity:create",
    async (_event, args: { displayName: string; password: string }) => {
      try {
        return { ok: true, status: identityVault.create(args.displayName, args.password) };
      } catch (error) {
        return { ok: false, error: String(error instanceof Error ? error.message : error) };
      }
    },
  );
  ipcMain.handle("identity:unlock", async (_event, args: { password: string; subject?: string }) => {
    try {
      return { ok: true, status: identityVault.unlock(args.password, args.subject) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:select", async (_event, args: { subject: string }) => {
    try {
      return { ok: true, status: identityVault.select(args.subject) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:remove", async (_event, args: {
    subject: string;
    password: string;
  }) => {
    try {
      return { ok: true, status: identityVault.remove(args.subject, args.password) };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:lock", async () => identityVault.lock());
  ipcMain.handle("identity:changePassword", async (_event, args: {
    currentPassword: string;
    newPassword: string;
    subject?: string;
  }) => {
    try {
      return {
        ok: true,
        status: identityVault.changePassword(
          args.currentPassword,
          args.newPassword,
          args.subject,
        ),
      };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:exportBackup", async (_event, args?: { subject?: string }) => {
    try {
      const subject = args?.subject || identityVault.status().activeSubject || "";
      const account = identityVault.status().accounts.find((item) => item.subject === subject);
      if (!account) throw new Error("找不到指定的本机账户");
      const win = getWindow();
      const result = win
        ? await dialog.showSaveDialog(win, {
            title: "导出加密身份备份",
            defaultPath: `${account.displayName}-xiaomei-identity.json`,
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          })
        : await dialog.showSaveDialog({
            title: "导出加密身份备份",
            defaultPath: `${account.displayName}-xiaomei-identity.json`,
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          });
      if (result.canceled || !result.filePath) return { ok: false, canceled: true };
      identityVault.exportBackup(result.filePath, subject);
      return { ok: true };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:importBackup", async (_event, args: { password: string }) => {
    try {
      const win = getWindow();
      const result = win
        ? await dialog.showOpenDialog(win, {
            title: "导入身份备份",
            properties: ["openFile"],
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          })
        : await dialog.showOpenDialog({
            title: "导入身份备份",
            properties: ["openFile"],
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          });
      if (result.canceled || !result.filePaths[0]) return { ok: false, canceled: true };
      return {
        ok: true,
        status: identityVault.importBackup(result.filePaths[0], args.password),
      };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });

  async function authenticateIdentity(client: GatewayClient): Promise<Record<string, unknown>> {
    const identity = identityVault.identity();
    const begin = await client.rpc("identity.authenticate.begin", {
      issuer: identity.issuer,
      subject: identity.subject,
    });

    if (!begin.error) {
      const challengeId = String(begin.result?.challenge_id || "");
      const challenge = String(begin.result?.challenge || "");
      const complete = await client.rpc("identity.authenticate.complete", {
        challenge_id: challengeId,
        signature: identityVault.signChallenge(challenge),
      });
      if (complete.error) throw new Error(complete.error.message);
      return complete.result || {};
    }

    // An unknown key may register only through a loopback Gateway. The Agent
    // remains the authority that decides whether this identity may be created.
    const register = await client.rpc("identity.register.begin", {
      display_name: identity.displayName,
      public_key: identity.publicKey,
    });
    if (register.error) throw new Error(register.error.message);
    const challengeId = String(register.result?.challenge_id || "");
    const challenge = String(register.result?.challenge || "");
    const complete = await client.rpc("identity.register.complete", {
      challenge_id: challengeId,
      signature: identityVault.signChallenge(challenge),
    });
    if (complete.error) throw new Error(complete.error.message);
    return complete.result || {};
  }

  ipcMain.handle("localAgents:discover", async () => {
    return discoverLocalAgents();
  });

  ipcMain.handle("localAgents:create", async (_event, args: { name: string; description: string }) => {
    console.info(`[runtime] create requested for agent ${args.name}`);
    const result = await runtimeManager.createAgent(args.name, args.description);
    if (result.ok) {
      console.info(`[runtime] create succeeded for agent ${result.agentId} on port ${result.port}`);
    } else {
      console.error(`[runtime] create failed for agent ${args.name}: ${result.message}`);
    }
    return result;
  });

  ipcMain.handle("localAgents:control", async (_event, args: {
    agentId: string;
    connectionId: string;
    action: AgentLifecycleAction;
  }) => {
    if (!["start", "stop", "restart"].includes(args.action)) {
      return { ok: false, action: args.action, agentId: args.agentId, message: "Invalid lifecycle action" };
    }

    if (args.action === "start" || args.action === "restart") {
      try {
        await localAIRuntime.ensureEmbedding();
      } catch (error) {
        return {
          ok: false,
          action: args.action,
          agentId: args.agentId,
          message: `向量服务未就绪：${String(error instanceof Error ? error.message : error)}`,
        };
      }
    }

    if (args.action === "stop" || args.action === "restart") {
      const client = connections.get(args.connectionId);
      if (client) {
        client.disconnect();
        connections.delete(args.connectionId);
      }
      connectionSessions.delete(args.connectionId);
      connectionReady.delete(args.connectionId);
    }
    console.info(`[runtime] ${args.action} requested for agent ${args.agentId}`);
    const result = await runtimeManager.control(args.agentId, args.action);
    if (result.ok) {
      console.info(`[runtime] ${args.action} succeeded for agent ${args.agentId}: ${result.message}`);
    } else {
      console.error(`[runtime] ${args.action} failed for agent ${args.agentId}: ${result.message}`);
    }
    return result;
  });

  // Helper: get or warn
  function getClient(agentId: string): GatewayClient | undefined {
    const c = connections.get(agentId);
    if (!c) console.warn(`[ipc] No connection for agent ${agentId}`);
    return c;
  }

  async function waitUntilConnectionReady(agentId: string, timeoutMs = 35000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (connectionReady.get(agentId) && connections.get(agentId)?.connected) return true;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return false;
  }

  async function fetchAttachment(agentId: string, sessionId: string, attachmentId: string) {
    const cacheKey = `${agentId}\u0000${sessionId}\u0000${attachmentId}`;
    const cached = attachmentCache.get(cacheKey);
    if (cached) {
      attachmentCache.delete(cacheKey);
      attachmentCache.set(cacheKey, cached);
      return { attachment: cached };
    }
    const client = getClient(agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${agentId} not connected` } };
    const response = await client.rpc("attachment.get", {
      session_id: sessionId,
      attachment_id: attachmentId,
    });
    if (response.error) return { error: response.error };
    const raw = response.result?.attachment;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { error: { code: -32603, message: "Agent returned an invalid attachment" } };
    }
    const value = raw as Record<string, unknown>;
    const dataBase64 = typeof value.data_base64 === "string" ? value.data_base64 : "";
    const data = Buffer.from(dataBase64, "base64");
    const size = typeof value.size === "number" ? value.size : -1;
    const attachmentLimit = String(value.mime_type || "").startsWith("video/")
      ? MAX_VIDEO_ATTACHMENT_BYTES
      : MAX_ATTACHMENT_BYTES;
    if (value.id !== attachmentId || !dataBase64 || size !== data.length || size > attachmentLimit) {
      return { error: { code: -32603, message: "Agent returned inconsistent attachment data" } };
    }
    const attachment = {
      id: attachmentId,
      name: typeof value.name === "string" ? path.basename(value.name) : attachmentId,
      mimeType: typeof value.mime_type === "string" ? value.mime_type : "application/octet-stream",
      size,
      kind: typeof value.kind === "string" ? value.kind : "file",
      dataBase64,
    };
    attachmentCache.set(cacheKey, attachment);
    while (attachmentCache.size > MAX_CACHED_ATTACHMENTS) {
      const oldest = attachmentCache.keys().next().value as string | undefined;
      if (!oldest) break;
      attachmentCache.delete(oldest);
    }
    return { attachment };
  }

  async function fetchArtifact(agentId: string, sessionId: string, artifactId: string) {
    const cacheKey = `${agentId}\u0000${sessionId}\u0000${artifactId}`;
    const cached = artifactCache.get(cacheKey);
    if (cached) {
      artifactCache.delete(cacheKey);
      artifactCache.set(cacheKey, cached);
      return { artifact: cached };
    }
    const client = getClient(agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${agentId} not connected` } };
    const response = await client.rpc("artifact.get", {
      session_id: sessionId,
      artifact_id: artifactId,
    });
    if (response.error) return { error: response.error };
    const raw = response.result?.artifact;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { error: { code: -32603, message: "Agent returned an invalid artifact" } };
    }
    const value = raw as Record<string, unknown>;
    const dataBase64 = typeof value.data_base64 === "string" ? value.data_base64 : "";
    const data = Buffer.from(dataBase64, "base64");
    const size = typeof value.size === "number" ? value.size : -1;
    if (value.id !== artifactId || !dataBase64 || size !== data.length || size > MAX_ARTIFACT_BYTES) {
      return { error: { code: -32603, message: "Agent returned inconsistent artifact data" } };
    }
    const artifact = {
      id: artifactId,
      name: typeof value.name === "string" ? path.basename(value.name) : artifactId,
      mimeType: typeof value.mime_type === "string" ? value.mime_type : "application/octet-stream",
      size,
      kind: typeof value.kind === "string" ? value.kind : "file",
      description: typeof value.description === "string" ? value.description : "",
      dataBase64,
    };
    artifactCache.set(cacheKey, artifact);
    while (artifactCache.size > MAX_CACHED_ATTACHMENTS) {
      const oldest = artifactCache.keys().next().value as string | undefined;
      if (!oldest) break;
      artifactCache.delete(oldest);
    }
    return { artifact };
  }

  // ─── connect ────────────────────────────────

  ipcMain.handle(
    "gateway:connect",
    async (
      _event,
      args: { host: string; port: number; token: string; agentId: string; sessionId?: string }
    ) => {
      try {
        const desktopIdentity = identityVault.identity();
        const legacyBindingConfigKey = `identity_agent_${createHash("sha256")
          .update(args.agentId)
          .digest("hex")}`;
        const bindingConfigKey = `identity_account_agent_${createHash("sha256")
          .update(`${args.agentId}\u0000${desktopIdentity.subject}`)
          .digest("hex")}`;
        const identityWasSeenByAgent = (
          config.get(bindingConfigKey) === "1"
          || config.get(legacyBindingConfigKey) === desktopIdentity.subject
        );
        // Disconnect existing connection for this agent
        const existing = connections.get(args.agentId);
        if (existing) existing.disconnect();
        connections.delete(args.agentId);
        connectionSessions.delete(args.agentId);
        connectionReady.delete(args.agentId);
        connectionSessionSwitchers.delete(args.agentId);
        invalidateArtifactCache(args.agentId);

        const client = new GatewayClient();
        // A newly introduced Desktop identity must not silently claim an old
        // conversation. Its first connection gets a fresh session; only after
        // this Agent has verified the key may Desktop request saved sessions.
        let sessionId = identityWasSeenByAgent ? (args.sessionId || "") : "";
        let authenticated = false;
        let reauthenticating = false;
        const recoveringEventGaps = new Set<string>();
        const subscribedSessions = new Set<string>();

        const sendGatewayEvent = (event: string, data: unknown = {}) => {
          const win = getWindow();
          if (win) {
            win.webContents.send("gateway:event", { event, data, agentId: args.agentId });
          }
        };

        const rememberSubscribedSession = async (nextSessionId: string) => {
          if (!nextSessionId) return;
          subscribedSessions.delete(nextSessionId);
          subscribedSessions.add(nextSessionId);
          let protectedAttempts = 0;
          while (subscribedSessions.size > 30 && protectedAttempts < subscribedSessions.size) {
            const oldest = subscribedSessions.values().next().value as string | undefined;
            if (!oldest) break;
            if (oldest === sessionId || oldest === nextSessionId) {
              subscribedSessions.delete(oldest);
              subscribedSessions.add(oldest);
              protectedAttempts += 1;
              continue;
            }
            const released = await client.rpc("session.unsubscribe", { session_id: oldest });
            if (released.error) {
              // Running/waiting conversations are deliberately protected by
              // the Agent. Move one to the back and retry it on a later switch.
              subscribedSessions.delete(oldest);
              subscribedSessions.add(oldest);
              protectedAttempts += 1;
              continue;
            }
            subscribedSessions.delete(oldest);
            protectedAttempts = 0;
          }
        };

        // Forward events with agentId tag
        client.on("event", (
          eventName: string,
          data: unknown,
          metadata: { sequence?: number; timestamp?: number; sessionId?: string } = {},
        ) => {
          if (["artifact.created", "artifact.updated", "artifact.presented"].includes(eventName)) {
            invalidateArtifactCache(args.agentId, data);
          }
          // session.resume below replaces the incomplete local stream with an
          // authoritative snapshot, so frames arriving during recovery are
          // intentionally not projected into the renderer.
          const deliveredSessionId = data && typeof data === "object" && !Array.isArray(data)
            ? String((data as Record<string, unknown>).session_id || metadata.sessionId || sessionId)
            : String(metadata.sessionId || sessionId);
          if (recoveringEventGaps.has(deliveredSessionId)) return;
          const eventData = data && typeof data === "object" && !Array.isArray(data)
            ? {
                ...(data as Record<string, unknown>),
                session_id: (data as Record<string, unknown>).session_id || deliveredSessionId,
              }
            : data;
          const win = getWindow();
          if (win) {
            win.webContents.send("gateway:event", {
              event: eventName,
              data: eventData,
              agentId: args.agentId,
              ...metadata,
            });
          }
        });
        client.on("eventGap", (gap: { expected: number; received: number; sessionId?: string }) => {
          const gapSessionId = gap.sessionId || sessionId;
          if (!authenticated || !gapSessionId || recoveringEventGaps.has(gapSessionId)) return;
          recoveringEventGaps.add(gapSessionId);
          if (gapSessionId === sessionId) connectionReady.set(args.agentId, false);
          console.warn(
            `[gateway] event gap for ${args.agentId}/${gapSessionId}: expected ${gap.expected}, received ${gap.received}`,
          );
          let recovered = false;
          void client.rpc("session.resume", {
            session_id: gapSessionId,
            history_limit: 50,
          }).then((resume) => {
            if (resume.error) {
              if (gapSessionId === sessionId) {
                sendGatewayEvent("reconnect.error", { message: resume.error.message });
              } else {
                console.warn(
                  `[gateway] background resync failed for ${args.agentId}/${gapSessionId}: ${resume.error.message}`,
                );
              }
              return;
            }
            sendGatewayEvent("stream.resynced", {
              session_id: gapSessionId,
              resume: resume.result || {},
              expected_sequence: gap.expected,
              received_sequence: gap.received,
            });
            recovered = true;
          }).catch((error) => {
            if (gapSessionId === sessionId) {
              sendGatewayEvent("reconnect.error", { message: String(error) });
            } else {
              console.warn(
                `[gateway] background resync failed for ${args.agentId}/${gapSessionId}: ${error}`,
              );
            }
          }).finally(() => {
            recoveringEventGaps.delete(gapSessionId);
            if (gapSessionId === sessionId) {
              connectionReady.set(args.agentId, recovered);
              if (!recovered) client.reconnect();
            }
          });
        });
        client.on("reconnecting", () => {
          connectionReady.set(args.agentId, false);
          sendGatewayEvent("reconnecting");
        });
        client.on("pong", () => {
          sendGatewayEvent("pong");
        });
        client.on("connected", () => {
          // The initial socket is authenticated below. Subsequent opens are
          // transport reconnects and must restore Gateway authentication.
          if (!authenticated || reauthenticating) return;

          reauthenticating = true;
          void client.rpc("connect", {
            token: args.token,
            client: "desktop",
            session_id: sessionId,
          }).then(async (res) => {
            if (res.error) {
              sendGatewayEvent("reconnect.error", { message: res.error.message });
              return;
            }

            const result = res.result || {};
            sessionId = (result["session_id"] as string) || sessionId;
            await authenticateIdentity(client);
            await rememberSubscribedSession(sessionId);
            for (const subscribedSessionId of subscribedSessions) {
              if (subscribedSessionId === sessionId) continue;
              const subscription = await client.rpc("session.subscribe", {
                session_id: subscribedSessionId,
              });
              if (subscription.error) throw new Error(subscription.error.message);
              const backgroundResume = await client.rpc("session.resume", {
                session_id: subscribedSessionId,
                history_limit: 50,
              });
              if (backgroundResume.error) throw new Error(backgroundResume.error.message);
              sendGatewayEvent("stream.resynced", {
                session_id: subscribedSessionId,
                resume: backgroundResume.result || {},
              });
            }
            const embodiment = await registerDesktopEmbodiment(client);
            if (embodiment.error) throw new Error(embodiment.error.message);
            connectionSessions.set(args.agentId, sessionId);
            const resume = await client.rpc("session.resume", {
              session_id: sessionId,
              history_limit: 50,
            });
            if (resume.error) {
              sendGatewayEvent("reconnect.error", { message: resume.error.message });
              return;
            }
            connectionReady.set(args.agentId, true);
            sendGatewayEvent("reconnected", {
              session_id: sessionId,
              agent_name: (result["agent_name"] as string) || "",
              protocol_version: result["protocol_version"],
              capabilities: result["capabilities"],
              resume: resume.result || {},
            });
          }).catch((error) => {
            sendGatewayEvent("reconnect.error", { message: String(error) });
          }).finally(() => {
            reauthenticating = false;
          });
        });

        connections.set(args.agentId, client);

        await client.connect(args.host, args.port);

        const res = await client.rpc("connect", {
          token: args.token,
          client: "desktop",
          session_id: sessionId,
        });

        if (res.error) {
          client.disconnect();
          connections.delete(args.agentId);
          return res;
        }

        const result = res.result || {};
        sessionId = (result["session_id"] as string) || "";
        const agentName = (result["agent_name"] as string) || "";
        const identityResult = await authenticateIdentity(client);
        const person = identityResult.person as Record<string, unknown> | undefined;
        const personId = String(person?.person_id || "");
        if (!personId) throw new Error("Agent 未返回有效的人物身份");
        config.set(bindingConfigKey, "1");
        authenticated = true;
        connectionSessions.set(args.agentId, sessionId);
        await rememberSubscribedSession(sessionId);
        const embodiment = await registerDesktopEmbodiment(client);
        if (embodiment.error) throw new Error(embodiment.error.message);

        const resume = await client.rpc("session.resume", {
          session_id: sessionId,
          history_limit: 50,
        });
        if (resume.error) {
          client.disconnect();
          connections.delete(args.agentId);
          connectionSessions.delete(args.agentId);
          connectionReady.delete(args.agentId);
          return resume;
        }
        connectionReady.set(args.agentId, true);
        connectionSessionSwitchers.set(args.agentId, async (nextSessionId) => {
          const resume = await client.rpc("session.switch", {
            session_id: nextSessionId,
            history_limit: 50,
          });
          if (resume.error) return resume as unknown as Record<string, unknown>;
          sessionId = nextSessionId;
          await rememberSubscribedSession(sessionId);
          connectionSessions.set(args.agentId, sessionId);
          return {
            result: {
              session_id: sessionId,
              agent_name: agentName,
              resume: resume.result || {},
            },
          };
        });

        // Persist last connection params
        config.set("last_host", args.host);
        config.set("last_port", String(args.port));

        return {
          result: {
            ...result,
            session_id: sessionId,
            agent_name: agentName,
            resume: resume.result || {},
          },
        };
      } catch (e) {
        connections.get(args.agentId)?.disconnect();
        connections.delete(args.agentId);
        connectionSessions.delete(args.agentId);
        connectionReady.delete(args.agentId);
        connectionSessionSwitchers.delete(args.agentId);
        return { error: { code: -32099, message: `Connection failed: ${e}` } };
      }
    }
  );

  // Switching conversations is an in-connection operation. Reopening the
  // WebSocket here would make the whole Agent appear to reconnect and would
  // briefly tear down its event stream.
  ipcMain.handle(
    "gateway:switchSession",
    async (_event, args: { agentId: string; sessionId: string }) => {
      const switchSession = connectionSessionSwitchers.get(args.agentId);
      if (!switchSession) {
        return { error: { code: -32099, message: "Agent is not connected" } };
      }
      try {
        return await switchSession(args.sessionId);
      } catch (error) {
        return { error: { code: -32099, message: `Session switch failed: ${error}` } };
      }
    },
  );

  // ─── disconnect ─────────────────────────────

  ipcMain.handle("gateway:disconnect", async (_event, args: { agentId: string }) => {
    const client = connections.get(args.agentId);
    if (client) {
      client.disconnect();
      connections.delete(args.agentId);
    }
    connectionSessions.delete(args.agentId);
    connectionReady.delete(args.agentId);
    connectionSessionSwitchers.delete(args.agentId);
  });

  // ─── chat.send ──────────────────────────────

  ipcMain.handle(
    "gateway:sendMessage",
    async (_event, args: {
      content: string;
      agentId: string;
      sessionId: string;
      clientRequestId: string;
      attachments?: Array<{ id: string; name: string; mimeType: string; size: number; dataBase64?: string }>;
      artifactReferences?: Array<{
        artifactId: string;
        sessionId: string;
        selection?: ({
          kind: "text";
          page?: number;
          selectedText: string;
          contextBefore?: string;
          contextAfter?: string;
        } | {
          kind: "spreadsheet";
          sheet: string;
          range: string;
          selectedText: string;
        } | {
          kind: "html";
          selector: string;
          tag: string;
          selectedText: string;
          outerHtml: string;
          contextBefore?: string;
          contextAfter?: string;
        });
      }>;
    }) => {
      const client = getClient(args.agentId);
      if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
      const params = {
        content: args.content,
        client_request_id: args.clientRequestId,
        session_id: args.sessionId || connectionSessions.get(args.agentId) || "",
        attachments: (args.attachments || []).map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          mime_type: attachment.mimeType,
          size: attachment.size,
          data_base64: attachment.dataBase64 || "",
        })),
        artifact_references: (args.artifactReferences || []).map((reference) => ({
          artifact_id: reference.artifactId,
          session_id: reference.sessionId,
          selection: reference.selection
            ? reference.selection.kind === "spreadsheet"
              ? {
                kind: reference.selection.kind,
                sheet: reference.selection.sheet,
                range: reference.selection.range,
                selected_text: reference.selection.selectedText,
              }
              : reference.selection.kind === "html"
                ? {
                  kind: reference.selection.kind,
                  selector: reference.selection.selector,
                  tag: reference.selection.tag,
                  selected_text: reference.selection.selectedText,
                  outer_html: reference.selection.outerHtml,
                  context_before: reference.selection.contextBefore || "",
                  context_after: reference.selection.contextAfter || "",
                }
              : {
                kind: reference.selection.kind,
                page: reference.selection.page,
                selected_text: reference.selection.selectedText,
                context_before: reference.selection.contextBefore || "",
                context_after: reference.selection.contextAfter || "",
              }
            : undefined,
        })),
      };
      const first = await client.rpc("chat.send", params);
      if (first.error?.code !== -32099) return first;
      if (!await waitUntilConnectionReady(args.agentId)) return first;
      const reconnectedClient = getClient(args.agentId);
      if (!reconnectedClient) return first;
      return reconnectedClient.rpc("chat.send", params);
    }
  );

  // ─── chat.abort ─────────────────────────────

  ipcMain.handle("gateway:abortMessage", async (_event, args: { agentId: string }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("chat.abort", {
      session_id: connectionSessions.get(args.agentId) || "",
    });
  });

  ipcMain.handle("gateway:retryMessage", async (_event, args: {
    agentId: string; sessionId: string; messageId: number; clientRequestId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("chat.retry", {
      session_id: args.sessionId,
      message_id: args.messageId,
      client_request_id: args.clientRequestId,
    });
  });

  ipcMain.handle("gateway:respondInteraction", async (_event, args: {
    agentId: string;
    requestId: string;
    turnId: string;
    response: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("interaction.respond", {
      request_id: args.requestId,
      turn_id: args.turnId,
      response: args.response,
    });
  });

  ipcMain.handle("gateway:respondAction", async (_event, args: {
    agentId: string;
    actionId: string;
    turnId: string;
    decision: "allow" | "deny";
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("action.respond", {
      action_id: args.actionId,
      turn_id: args.turnId,
      decision: args.decision,
    });
  });

  // ─── chat.history ───────────────────────────

  ipcMain.handle(
    "gateway:getHistory",
    async (_event, args: { sessionId?: string; limit?: number; beforeId?: number; agentId: string }) => {
      const client = getClient(args.agentId);
      if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
      return client.rpc("chat.history", {
        session_id: args.sessionId || connectionSessions.get(args.agentId) || "",
        limit: args.limit || 50,
        before_id: args.beforeId,
      });
    }
  );

  ipcMain.handle("gateway:sendVoice", async (_event, args: {
    agentId: string;
    dataBase64: string;
    mimeType: string;
    size: number;
    clientRequestId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) {
      return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    }
    if (!args.dataBase64 || args.size <= 0 || args.size > MAX_ATTACHMENT_BYTES) {
      return { error: { code: -32602, message: "语音数据无效或超过 5 MB" } };
    }
    return client.rpc("embodiment.audio.input", {
      data_base64: args.dataBase64,
      mime_type: args.mimeType,
      size: args.size,
      client_request_id: args.clientRequestId,
    });
  });

  ipcMain.handle("gateway:pickAttachments", async () => {
    const win = getWindow();
    const result = win
      ? await dialog.showOpenDialog(win, {
          properties: ["openFile", "multiSelections"],
          filters: [
            { name: "Supported files", extensions: [
              "jpg", "jpeg", "png", "gif", "webp", "bmp", "txt", "md", "json", "yaml", "yml",
              "toml", "csv", "tsv", "xml", "html", "css", "js", "jsx", "ts", "tsx", "py", "java",
              "c", "h", "cpp", "cs", "go", "rs", "rb", "php", "swift", "sql", "sh", "ps1", "log",
              "docx", "pptx", "pdf", "xlsx",
              "mp4", "m4v", "mov", "webm", "mkv", "avi", "mpeg", "mpg",
            ] },
          ],
        })
      : await dialog.showOpenDialog({ properties: ["openFile", "multiSelections"] });
    if (result.canceled) return { attachments: [] };
    if (result.filePaths.length > 4) return { attachments: [], error: "一次最多选择 4 个附件" };

    const attachments = [];
    let total = 0;
    for (const filePath of result.filePaths) {
      const stat = await fs.stat(filePath);
      const name = path.basename(filePath);
      const extension = path.extname(filePath).toLowerCase();
      if (stat.size === 0) return { attachments: [], error: `${name} 是空文件` };
      const videoMime = VIDEO_MIMES[extension];
      const itemLimit = videoMime ? MAX_VIDEO_ATTACHMENT_BYTES : MAX_ATTACHMENT_BYTES;
      if (stat.size > itemLimit) {
        return { attachments: [], error: `${name} 超过 ${itemLimit / 1024 / 1024} MB` };
      }
      total += stat.size;
      const selectedHasVideo = Boolean(videoMime)
        || attachments.some((item) => item.kind === "video");
      const totalLimit = selectedHasVideo
        ? MAX_VIDEO_TOTAL_ATTACHMENT_BYTES
        : MAX_TOTAL_ATTACHMENT_BYTES;
      if (total > totalLimit) {
        return { attachments: [], error: `附件合计不能超过 ${totalLimit / 1024 / 1024} MB` };
      }
      const imageMime = IMAGE_MIMES[extension];
      const officeMime = OFFICE_MIMES[extension];
      if (!imageMime && !videoMime && !officeMime && !TEXT_EXTENSIONS.has(extension)) {
        return { attachments: [], error: `暂不支持 ${name} 的文件类型` };
      }
      const data = await fs.readFile(filePath);
      attachments.push({
        id: crypto.randomUUID(),
        name,
        mimeType: imageMime || videoMime || officeMime || "text/plain",
        size: stat.size,
        kind: imageMime ? "image" : videoMime ? "video" : officeMime ? "document" : "text",
        dataBase64: data.toString("base64"),
      });
    }
    return { attachments };
  });

  ipcMain.handle("gateway:getAttachment", async (_event, args: {
    agentId: string; sessionId: string; attachmentId: string;
  }) => {
    const result = await fetchAttachment(args.agentId, args.sessionId, args.attachmentId);
    if (result.error) return { error: result.error };
    return { result: { attachment: result.attachment } };
  });

  ipcMain.handle("gateway:openAttachment", async (_event, args: {
    agentId: string; sessionId: string; attachmentId: string;
  }) => {
    const result = await fetchAttachment(args.agentId, args.sessionId, args.attachmentId);
    if (result.error) return { ok: false, error: result.error.message };
    try {
      const attachment = result.attachment;
      const data = Buffer.from(attachment.dataBase64, "base64");
      const contentHash = createHash("sha256").update(data).digest("hex").slice(0, 16);
      const cacheKey = createHash("sha256")
        .update(`${args.agentId}\u0000${args.sessionId}\u0000${args.attachmentId}\u0000${contentHash}`)
        .digest("hex")
        .slice(0, 24);
      const safeName = path.basename(attachment.name)
        .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_") || attachment.id;
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "attachments", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await ensureImmutableCacheFile(cachePath, data);
      const error = await shell.openPath(cachePath);
      return error ? { ok: false, error } : { ok: true };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  });

  ipcMain.handle("gateway:getArtifact", async (_event, args: {
    agentId: string; sessionId: string; artifactId: string;
  }) => {
    const result = await fetchArtifact(args.agentId, args.sessionId, args.artifactId);
    if (result.error) return { error: result.error };
    return { result: { artifact: result.artifact } };
  });

  ipcMain.handle("gateway:listArtifacts", async (_event, args: {
    agentId: string; limit?: number; offset?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("artifact.list", {
      limit: args.limit || 100,
      offset: args.offset || 0,
    });
  });

  ipcMain.handle("gateway:listMemories", async (_event, args: {
    agentId: string; limit?: number; offset?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("memory.list", {
      limit: args.limit || 30,
      offset: args.offset || 0,
    });
  });

  ipcMain.handle("gateway:openArtifact", async (_event, args: {
    agentId: string; sessionId: string; artifactId: string;
  }) => {
    const result = await fetchArtifact(args.agentId, args.sessionId, args.artifactId);
    if (result.error) return { ok: false, error: result.error.message };
    try {
      const artifact = result.artifact;
      const data = Buffer.from(artifact.dataBase64, "base64");
      const contentHash = createHash("sha256").update(data).digest("hex").slice(0, 16);
      const cacheKey = createHash("sha256")
        .update(`${args.agentId}\u0000${args.sessionId}\u0000${args.artifactId}\u0000${contentHash}`)
        .digest("hex")
        .slice(0, 24);
      const safeName = path.basename(artifact.name)
        .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_") || artifact.id;
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "artifacts", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await ensureImmutableCacheFile(cachePath, data);
      const error = await shell.openPath(cachePath);
      return error ? { ok: false, error } : { ok: true };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  });

  ipcMain.handle(
    "gateway:listSessions",
    async (_event, args: { limit?: number; offset?: number; query?: string; agentId: string }) => {
      const client = getClient(args.agentId);
      if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
      return client.rpc("chat.sessions", {
        limit: args.limit || 30,
        offset: args.offset || 0,
        query: args.query || "",
      });
    }
  );

  ipcMain.handle("gateway:unifiedSearch", async (_event, args: {
    agentId: string; query: string; limit?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("search.query", {
      query: args.query,
      limit: args.limit || 8,
    });
  });

  // ─── assignments ────────────────────────────

  ipcMain.handle("gateway:listAssignments", async (_event, args: {
    agentId: string; status?: string; limit?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("assignment.list", {
      status: args.status || "all",
      limit: args.limit || 100,
    });
  });

  ipcMain.handle("gateway:getAssignment", async (_event, args: {
    agentId: string; assignmentId: string; eventLimit?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("assignment.get", {
      assignment_id: args.assignmentId,
      event_limit: args.eventLimit || 100,
    });
  });

  ipcMain.handle("gateway:listProjects", async (_event, args: {
    agentId: string; status?: string; limit?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("project.list", {
      status: args.status || "all",
      limit: args.limit || 100,
    });
  });

  ipcMain.handle("gateway:getProject", async (_event, args: {
    agentId: string; projectId: string; eventLimit?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("project.get", {
      project_id: args.projectId,
      event_limit: args.eventLimit || 100,
    });
  });

  ipcMain.handle("gateway:getCurrentProject", async (_event, args: {
    agentId: string; sessionId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("project.current", { session_id: args.sessionId });
  });

  ipcMain.handle("gateway:listActivities", async (_event, args: {
    agentId: string; status?: string; category?: string; limit?: number; offset?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("activity.list", {
      status: args.status || "all",
      category: args.category || "all",
      limit: args.limit || 100,
      offset: args.offset || 0,
    });
  });

  ipcMain.handle("gateway:getActivity", async (_event, args: {
    agentId: string; activityId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("activity.get", { activity_id: args.activityId });
  });

  ipcMain.handle("gateway:getAgentState", async (_event, args: {
    agentId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("agent.state.get", {});
  });

  ipcMain.handle("gateway:listCapabilities", async (_event, args: {
    agentId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("capability.list", {});
  });

  ipcMain.handle("gateway:getCapability", async (_event, args: {
    agentId: string; capabilityId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("capability.get", { capability_id: args.capabilityId });
  });

  ipcMain.handle("gateway:setCapabilityEnabled", async (_event, args: {
    agentId: string; capabilityId: string; enabled: boolean;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc(args.enabled ? "capability.enable" : "capability.disable", {
      capability_id: args.capabilityId,
    });
  });

  ipcMain.handle("gateway:inspectCapabilityPackage", async (_event, args: {
    agentId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    try {
      const win = getWindow();
      const selection = win
        ? await dialog.showOpenDialog(win, {
            title: "选择小美能力包",
            properties: ["openFile"],
            filters: [{ name: "小美能力包", extensions: ["xmcap"] }],
          })
        : await dialog.showOpenDialog({
            title: "选择小美能力包",
            properties: ["openFile"],
            filters: [{ name: "小美能力包", extensions: ["xmcap"] }],
          });
      const filePath = selection.filePaths[0];
      if (selection.canceled || !filePath) return { result: { canceled: true } };
      const stat = await fs.stat(filePath);
      if (!stat.isFile()) return { error: { code: -32602, message: "请选择一个能力包文件" } };
      if (stat.size > MAX_CAPABILITY_PACKAGE_BYTES) {
        return { error: { code: -32602, message: "能力包超过 8 MB 检查上限" } };
      }
      const data = await fs.readFile(filePath);
      const sha256 = createHash("sha256").update(data).digest("hex");
      const response = await client.rpc("capability.package.inspect", {
        file_name: path.basename(filePath),
        data_base64: data.toString("base64"),
        sha256,
      });
      const inspection = response.result?.inspection;
      if (
        !response.error
        && inspection
        && typeof inspection === "object"
        && !Array.isArray(inspection)
        && (inspection as Record<string, unknown>).valid === true
      ) {
        inspectedCapabilityPackages.set(args.agentId, { filePath, sha256 });
      }
      return response;
    } catch (error) {
      return {
        error: {
          code: -32603,
          message: String(error instanceof Error ? error.message : error),
        },
      };
    }
  });

  ipcMain.handle("gateway:listCapabilityPackages", async (_event, args: {
    agentId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("capability.package.list", {});
  });

  ipcMain.handle("gateway:installCapabilityPackage", async (_event, args: {
    agentId: string;
    sha256: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    const selected = inspectedCapabilityPackages.get(args.agentId);
    if (!selected || selected.sha256 !== args.sha256) {
      return { error: { code: -32602, message: "能力包预览已失效，请重新选择文件" } };
    }
    try {
      const data = await fs.readFile(selected.filePath);
      const sha256 = createHash("sha256").update(data).digest("hex");
      if (sha256 !== selected.sha256 || data.length > MAX_CAPABILITY_PACKAGE_BYTES) {
        inspectedCapabilityPackages.delete(args.agentId);
        return { error: { code: -32602, message: "能力包内容已改变，请重新检查" } };
      }
      const installed = await client.rpc("capability.package.install", {
        file_name: path.basename(selected.filePath),
        data_base64: data.toString("base64"),
        sha256,
      });
      if (installed.error) return installed;
      const rawPackage = installed.result?.package;
      if (!rawPackage || typeof rawPackage !== "object" || Array.isArray(rawPackage)) {
        return { error: { code: -32603, message: "Agent 返回了无效的安装结果" } };
      }
      const packageValue = rawPackage as Record<string, unknown>;
      const activated = await client.rpc("capability.package.activate", {
        package_id: String(packageValue.id || ""),
        version: String(packageValue.version || ""),
        sha256: String(packageValue.sha256 || ""),
      });
      if (!activated.error) {
        inspectedCapabilityPackages.delete(args.agentId);
        return {
          ...activated,
          result: {
            ...(activated.result || {}),
            operation: installed.result?.operation,
            affected_agents: installed.result?.affected_agents || [],
          },
        };
      }
      return activated;
    } catch (error) {
      return {
        error: {
          code: -32603,
          message: String(error instanceof Error ? error.message : error),
        },
      };
    }
  });

  ipcMain.handle("gateway:setCapabilityPackageActive", async (_event, args: {
    agentId: string;
    packageId: string;
    version: string;
    sha256: string;
    active: boolean;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc(
      args.active ? "capability.package.activate" : "capability.package.deactivate",
      args.active
        ? { package_id: args.packageId, version: args.version, sha256: args.sha256 }
        : { package_id: args.packageId },
    );
  });

  ipcMain.handle("gateway:uninstallCapabilityPackage", async (_event, args: {
    agentId: string;
    packageId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("capability.package.uninstall", { package_id: args.packageId });
  });

  ipcMain.handle("gateway:openAssignmentArtifact", async (_event, args: {
    agentId: string; assignmentId: string; artifactId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { ok: false, error: `Agent ${args.agentId} not connected` };
    const response = await client.rpc("assignment.artifact.get", {
      assignment_id: args.assignmentId,
      artifact_id: args.artifactId,
    });
    if (response.error) return { ok: false, error: response.error.message };
    const raw = response.result?.artifact;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { ok: false, error: "Agent returned an invalid assignment artifact" };
    }
    const value = raw as Record<string, unknown>;
    const dataBase64 = typeof value.data_base64 === "string" ? value.data_base64 : "";
    const data = Buffer.from(dataBase64, "base64");
    const size = typeof value.size === "number" ? value.size : -1;
    if (value.id !== args.artifactId || !dataBase64 || size !== data.length || size > MAX_ARTIFACT_BYTES) {
      return { ok: false, error: "Agent returned inconsistent assignment artifact data" };
    }
    try {
      const safeName = path.basename(
        typeof value.name === "string" ? value.name : args.artifactId,
      ).replace(/[<>:"/\\|?*\x00-\x1f]/g, "_") || args.artifactId;
      const cacheKey = createHash("sha256")
        .update(`${args.agentId}\u0000${args.assignmentId}\u0000${args.artifactId}\u0000${createHash("sha256").update(data).digest("hex").slice(0, 16)}`)
        .digest("hex")
        .slice(0, 24);
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "assignments", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await ensureImmutableCacheFile(cachePath, data);
      const error = await shell.openPath(cachePath);
      return error ? { ok: false, error } : { ok: true };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  });

  ipcMain.handle("gateway:requestAssignmentCancel", async (_event, args: {
    agentId: string; assignmentId: string; reason?: string; expectedRevision?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("assignment.request_cancel", {
      assignment_id: args.assignmentId,
      reason: args.reason || "",
      expected_revision: args.expectedRevision,
    });
  });

  ipcMain.handle("gateway:requestAssignmentResume", async (_event, args: {
    agentId: string;
    assignmentId: string;
    response?: string;
    decision?: "approve" | "deny";
    expectedRevision?: number;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("assignment.request_resume", {
      assignment_id: args.assignmentId,
      response: args.response || "",
      decision: args.decision,
      expected_revision: args.expectedRevision,
    });
  });

  ipcMain.handle(
    "notification:show",
    async (_event, args: { title: string; body: string; agentId: string; sessionId: string }) => {
      if (config.get("desktop.notificationsEnabled") === "false") {
        return { shown: false };
      }
      const win = getWindow();
      if (!win || win.isDestroyed() || win.isFocused() || !Notification.isSupported()) {
        return { shown: false };
      }

      const title = sanitizeNotificationText(args?.title, 80) || "xiaomei-brain";
      const body = sanitizeNotificationText(args?.body, 160);
      const notification = new Notification({ title, body });
      activeNotifications.add(notification);
      const releaseNotification = () => activeNotifications.delete(notification);
      notification.on("click", () => {
        releaseNotification();
        const target = getWindow();
        if (!target || target.isDestroyed()) return;
        if (target.isMinimized()) target.restore();
        target.show();
        target.focus();
        target.webContents.send("notification:selected", {
          agentId: args.agentId,
          sessionId: args.sessionId,
        });
      });
      notification.on("show", () => {
        console.info(`[notification] shown for agent ${args.agentId}`);
      });
      notification.on("close", releaseNotification);
      notification.on("failed", (_event, error) => {
        console.error(`[notification] failed for agent ${args.agentId}: ${error}`);
        releaseNotification();
      });
      notification.show();
      return { shown: true };
    }
  );

  // ─── identity.list ──────────────────────────

  ipcMain.handle("gateway:listIdentities", async (_event, args: { agentId: string }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("identity.list", {});
  });

  ipcMain.handle("gateway:listLegacySessions", async (_event, args: { agentId: string }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("identity.legacy_sessions.list", {});
  });

  ipcMain.handle("gateway:claimLegacySession", async (_event, args: {
    agentId: string;
    sessionId: string;
  }) => {
    const client = getClient(args.agentId);
    if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    return client.rpc("identity.legacy_sessions.claim", { session_id: args.sessionId });
  });

  const channelRpc = (
    args: { agentId: string },
    method: string,
    params: Record<string, unknown>,
  ) => {
    const client = getClient(args.agentId);
    if (!client) {
      return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
    }
    return client.rpc(method, params);
  };

  ipcMain.handle("gateway:getChannelConfig", async (_event, args: {
    agentId: string; channel: string;
  }) => channelRpc(args, "channel.config.get", { channel: args.channel }));

  ipcMain.handle("gateway:testChannel", async (_event, args: {
    agentId: string; channel: string; appId: string; appSecret: string;
  }) => channelRpc(args, "channel.test", {
    channel: args.channel,
    app_id: args.appId,
    app_secret: args.appSecret,
  }));

  ipcMain.handle("gateway:configureChannel", async (_event, args: {
    agentId: string;
    channel: string;
    appId: string;
    appSecret: string;
    displayName: string;
    accountId?: string;
  }) => channelRpc(args, "channel.configure", {
    channel: args.channel,
    app_id: args.appId,
    app_secret: args.appSecret,
    display_name: args.displayName,
    account_id: args.accountId || "default",
  }));

  ipcMain.handle("gateway:getChannelStatus", async (_event, args: {
    agentId: string; channel: string;
  }) => channelRpc(args, "channel.status", { channel: args.channel }));

  ipcMain.handle("gateway:removeChannel", async (_event, args: {
    agentId: string; channel: string;
  }) => channelRpc(args, "channel.remove", { channel: args.channel }));

  ipcMain.handle("gateway:beginIdentityLink", async (_event, args: {
    agentId: string; provider: string;
  }) => channelRpc(args, "identity.link.begin", { provider: args.provider }));

  ipcMain.handle("gateway:getIdentityLinkStatus", async (_event, args: {
    agentId: string; requestId: string;
  }) => channelRpc(args, "identity.link.status", { request_id: args.requestId }));

  ipcMain.handle("gateway:cancelIdentityLink", async (_event, args: {
    agentId: string; requestId: string;
  }) => channelRpc(args, "identity.link.cancel", { request_id: args.requestId }));

  ipcMain.handle("gateway:listIdentityLinks", async (_event, args: {
    agentId: string; provider: string;
  }) => channelRpc(args, "identity.link.list", { provider: args.provider }));

  ipcMain.handle("gateway:revokeIdentityLink", async (_event, args: {
    agentId: string; provider: string; bindingId: string;
  }) => channelRpc(args, "identity.link.revoke", {
    provider: args.provider,
    binding_id: args.bindingId,
  }));

  // ─── Config (local JSON) ────────────────────

  // Model resources live on the Agent host. Desktop only forwards RPC
  // requests and never reads or edits the Agent's JSON files directly.
  ipcMain.handle("gateway:getModelConfig", async (_event, args: {
    agentId: string;
  }) => channelRpc(args, "model.config.get", {}));

  ipcMain.handle("gateway:getModelCatalog", async (_event, args: {
    agentId: string; providerId?: string;
  }) => channelRpc(args, "model.catalog", {
    provider_id: args.providerId || "",
  }));

  ipcMain.handle("gateway:testModelProvider", async (_event, args: {
    agentId: string;
    providerId: string;
    baseUrl: string;
    apiKey: string;
    apiMode: string;
    modelId: string;
  }) => channelRpc(args, "model.provider.test", {
    provider_id: args.providerId,
    base_url: args.baseUrl,
    api_key: args.apiKey,
    api_mode: args.apiMode,
    model_id: args.modelId,
  }));

  ipcMain.handle("gateway:configureModelProvider", async (_event, args: {
    agentId: string;
    providerId: string;
    baseUrl: string;
    apiKey: string;
    apiMode: string;
    models: Array<Record<string, unknown>>;
    baseHash?: string;
  }) => channelRpc(args, "model.provider.configure", {
    provider_id: args.providerId,
    base_url: args.baseUrl,
    api_key: args.apiKey,
    api_mode: args.apiMode,
    models: args.models,
    base_hash: args.baseHash || "",
  }));

  ipcMain.handle("gateway:removeModelProvider", async (_event, args: {
    agentId: string; providerId: string; baseHash?: string;
  }) => channelRpc(args, "model.provider.remove", {
    provider_id: args.providerId,
    base_hash: args.baseHash || "",
  }));

  ipcMain.handle("gateway:setModelSelection", async (_event, args: {
    agentId: string;
    primary: string;
    vision?: string;
    thinking?: {
      enabled: boolean;
      effort: "default" | "low" | "medium" | "high" | "max";
    };
    baseHash?: string;
  }) => channelRpc(args, "model.selection.set", {
    primary: args.primary,
    vision: args.vision || "",
    thinking: args.thinking,
    base_hash: args.baseHash || "",
  }));

  ipcMain.handle("gateway:listMediaServices", async (_event, args: {
    agentId: string; capability?: "image" | "tts" | "music" | "video";
  }) => channelRpc(args, "media.service.list", {
    capability: args.capability || "",
  }));

  ipcMain.handle("gateway:getMediaRuntimeStatus", async (_event, args: {
    agentId: string;
  }) => channelRpc(args, "media.runtime.status", {}));

  ipcMain.handle("gateway:getMediaService", async (_event, args: {
    agentId: string; serviceId: string;
  }) => channelRpc(args, "media.service.get", {
    service_id: args.serviceId,
  }));

  ipcMain.handle("gateway:testMediaService", async (_event, args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
  }) => channelRpc(args, "media.service.test", {
    service_id: args.serviceId,
    config: args.config,
  }));

  ipcMain.handle("gateway:configureMediaService", async (_event, args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
    enabled?: boolean;
  }) => channelRpc(args, "media.service.configure", {
    service_id: args.serviceId,
    config: args.config,
    enabled: args.enabled !== false,
  }));

  ipcMain.handle("gateway:removeMediaService", async (_event, args: {
    agentId: string; serviceId: string;
  }) => channelRpc(args, "media.service.remove", {
    service_id: args.serviceId,
  }));

  ipcMain.handle("gateway:listToolServices", async (_event, args: {
    agentId: string; capability?: "web_search";
  }) => channelRpc(args, "tool.service.list", {
    capability: args.capability || "",
  }));

  ipcMain.handle("gateway:getToolService", async (_event, args: {
    agentId: string; serviceId: string;
  }) => channelRpc(args, "tool.service.get", {
    service_id: args.serviceId,
  }));

  ipcMain.handle("gateway:testToolService", async (_event, args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
  }) => channelRpc(args, "tool.service.test", {
    service_id: args.serviceId,
    config: args.config,
  }));

  ipcMain.handle("gateway:configureToolService", async (_event, args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
    enabled?: boolean;
  }) => channelRpc(args, "tool.service.configure", {
    service_id: args.serviceId,
    config: args.config,
    enabled: args.enabled !== false,
  }));

  ipcMain.handle("gateway:removeToolService", async (_event, args: {
    agentId: string; serviceId: string;
  }) => channelRpc(args, "tool.service.remove", {
    service_id: args.serviceId,
  }));

  ipcMain.handle("store:getConfig", async (_event, key: string) => {
    return config.get(key);
  });

  // ─── Terminal ────────────────────────────────

  ipcMain.handle(
    "terminal:spawn",
    async (_event, args: {
      cols: number;
      rows: number;
      mode?: "shell" | "agent-logs";
      agentId?: string;
    }) => {
      const win = getWindow();
      if (!win) return { error: "No window" };
      let launch;
      if (args.mode === "agent-logs") {
        if (!args.agentId || !/^[A-Za-z0-9_-]+$/.test(args.agentId)) {
          return { error: "Invalid local Agent ID" };
        }
        try {
          launch = await runtimeManager.buildCommand([
            "logs",
            args.agentId,
            "--follow",
            "--lines",
            "100",
          ]);
        } catch (error) {
          return { error: String(error instanceof Error ? error.message : error) };
        }
      }

      const result = terminalMgr.spawn(
        args.cols || 80,
        args.rows || 24,
        (data: string) => {
          win.webContents.send("terminal:data", data);
        },
        (code: number) => {
          win.webContents.send("terminal:exit", code);
        },
        launch,
      );
      return result;
    }
  );

  ipcMain.handle(
    "terminal:write",
    async (_event, data: string) => {
      terminalMgr.write(data);
    }
  );

  ipcMain.handle(
    "terminal:resize",
    async (_event, args: { cols: number; rows: number }) => {
      terminalMgr.resize(args.cols, args.rows);
    }
  );

  ipcMain.handle("terminal:dispose", async () => {
    terminalMgr.kill();
  });
}
