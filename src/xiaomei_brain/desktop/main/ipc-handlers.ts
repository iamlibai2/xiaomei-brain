import { ipcMain, BrowserWindow, Notification, app, dialog, shell } from "electron";
import { createHash } from "crypto";
import { promises as fs } from "fs";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { TerminalManager } from "./terminal-manager";
import { discoverLocalAgents } from "./local-agent-discovery";
import { AgentLifecycleAction, RuntimeManager } from "./runtime-manager";
import { sanitizeNotificationText } from "./notification-text";
import { IdentityVault } from "./identity-vault";

const connections = new Map<string, GatewayClient>();
const connectionSessions = new Map<string, string>();
const connectionReady = new Map<string, boolean>();
const activeNotifications = new Set<Notification>();
const attachmentCache = new Map<string, {
  id: string; name: string; mimeType: string; size: number; kind: string; dataBase64: string;
}>();
const artifactCache = new Map<string, {
  id: string; name: string; mimeType: string; size: number; kind: string; description: string; dataBase64: string;
}>();
const MAX_CACHED_ATTACHMENTS = 32;
const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_ARTIFACT_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const IMAGE_MIMES: Record<string, string> = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
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
};

export function registerIpcHandlers(
  _gateway: GatewayClient,
  config: ConfigStore,
  getWindow: () => BrowserWindow | null
): void {
  const terminalMgr = new TerminalManager();
  const runtimeManager = new RuntimeManager(config);
  const identityVault = new IdentityVault();
  void runtimeManager.warmup().catch((error) => {
    console.error("[runtime] background initialization failed", error);
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
  }) => {
    try {
      return {
        ok: true,
        status: identityVault.changePassword(args.currentPassword, args.newPassword),
      };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("identity:exportBackup", async () => {
    try {
      const identity = identityVault.identity();
      const win = getWindow();
      const result = win
        ? await dialog.showSaveDialog(win, {
            title: "导出加密身份备份",
            defaultPath: `${identity.displayName}-xiaomei-identity.json`,
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          })
        : await dialog.showSaveDialog({
            title: "导出加密身份备份",
            defaultPath: `${identity.displayName}-xiaomei-identity.json`,
            filters: [{ name: "xiaomei-brain 身份备份", extensions: ["json"] }],
          });
      if (result.canceled || !result.filePath) return { ok: false, canceled: true };
      identityVault.exportBackup(result.filePath);
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
    if (value.id !== attachmentId || !dataBase64 || size !== data.length || size > MAX_ATTACHMENT_BYTES) {
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

        const client = new GatewayClient();
        // A newly introduced Desktop identity must not silently claim an old
        // conversation. Its first connection gets a fresh session; only after
        // this Agent has verified the key may Desktop request saved sessions.
        let sessionId = identityWasSeenByAgent ? (args.sessionId || "") : "";
        let authenticated = false;
        let reauthenticating = false;
        let recoveringEventGap = false;

        const sendGatewayEvent = (event: string, data: unknown = {}) => {
          const win = getWindow();
          if (win) {
            win.webContents.send("gateway:event", { event, data, agentId: args.agentId });
          }
        };

        // Forward events with agentId tag
        client.on("event", (
          eventName: string,
          data: unknown,
          metadata: { sequence?: number; timestamp?: number } = {},
        ) => {
          // session.resume below replaces the incomplete local stream with an
          // authoritative snapshot, so frames arriving during recovery are
          // intentionally not projected into the renderer.
          if (recoveringEventGap) return;
          const eventData = data && typeof data === "object" && !Array.isArray(data)
            ? {
                ...(data as Record<string, unknown>),
                session_id: (data as Record<string, unknown>).session_id || sessionId,
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
        client.on("eventGap", (gap: { expected: number; received: number }) => {
          if (!authenticated || recoveringEventGap || !sessionId) return;
          recoveringEventGap = true;
          connectionReady.set(args.agentId, false);
          console.warn(
            `[gateway] event gap for ${args.agentId}: expected ${gap.expected}, received ${gap.received}`,
          );
          let recovered = false;
          void client.rpc("session.resume", {
            session_id: sessionId,
            history_limit: 50,
          }).then((resume) => {
            if (resume.error) {
              sendGatewayEvent("reconnect.error", { message: resume.error.message });
              return;
            }
            sendGatewayEvent("stream.resynced", {
              session_id: sessionId,
              resume: resume.result || {},
              expected_sequence: gap.expected,
              received_sequence: gap.received,
            });
            recovered = true;
          }).catch((error) => {
            sendGatewayEvent("reconnect.error", { message: String(error) });
          }).finally(() => {
            recoveringEventGap = false;
            connectionReady.set(args.agentId, recovered);
            if (!recovered) client.reconnect();
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
        return { error: { code: -32099, message: `Connection failed: ${e}` } };
      }
    }
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
  });

  // ─── chat.send ──────────────────────────────

  ipcMain.handle(
    "gateway:sendMessage",
    async (_event, args: {
      content: string;
      agentId: string;
      clientRequestId: string;
      attachments?: Array<{ id: string; name: string; mimeType: string; size: number; dataBase64?: string }>;
    }) => {
      const client = getClient(args.agentId);
      if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
      const params = {
        content: args.content,
        client_request_id: args.clientRequestId,
        session_id: connectionSessions.get(args.agentId) || "",
        attachments: (args.attachments || []).map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          mime_type: attachment.mimeType,
          size: attachment.size,
          data_base64: attachment.dataBase64 || "",
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

  ipcMain.handle("gateway:pickAttachments", async () => {
    const win = getWindow();
    const result = win
      ? await dialog.showOpenDialog(win, {
          properties: ["openFile", "multiSelections"],
          filters: [
            { name: "Images and text files", extensions: [
              "jpg", "jpeg", "png", "gif", "webp", "bmp", "txt", "md", "json", "yaml", "yml",
              "toml", "csv", "tsv", "xml", "html", "css", "js", "jsx", "ts", "tsx", "py", "java",
              "c", "h", "cpp", "cs", "go", "rs", "rb", "php", "swift", "sql", "sh", "ps1", "log",
              "docx", "pptx",
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
      if (stat.size > MAX_ATTACHMENT_BYTES) return { attachments: [], error: `${name} 超过 5 MB` };
      total += stat.size;
      if (total > MAX_TOTAL_ATTACHMENT_BYTES) return { attachments: [], error: "附件合计不能超过 8 MB" };
      const imageMime = IMAGE_MIMES[extension];
      const officeMime = OFFICE_MIMES[extension];
      if (!imageMime && !officeMime && !TEXT_EXTENSIONS.has(extension)) {
        return { attachments: [], error: `暂不支持 ${name} 的文件类型` };
      }
      const data = await fs.readFile(filePath);
      attachments.push({
        id: crypto.randomUUID(),
        name,
        mimeType: imageMime || officeMime || "text/plain",
        size: stat.size,
        kind: imageMime ? "image" : officeMime ? "document" : "text",
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
      const cacheKey = createHash("sha256")
        .update(`${args.agentId}\u0000${args.sessionId}\u0000${args.attachmentId}`)
        .digest("hex")
        .slice(0, 24);
      const safeName = path.basename(attachment.name)
        .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_") || attachment.id;
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "attachments", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await fs.writeFile(cachePath, Buffer.from(attachment.dataBase64, "base64"));
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
      const cacheKey = createHash("sha256")
        .update(`${args.agentId}\u0000${args.sessionId}\u0000${args.artifactId}`)
        .digest("hex")
        .slice(0, 24);
      const safeName = path.basename(artifact.name)
        .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_") || artifact.id;
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "artifacts", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await fs.writeFile(cachePath, Buffer.from(artifact.dataBase64, "base64"));
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
        .update(`${args.agentId}\u0000${args.assignmentId}\u0000${args.artifactId}`)
        .digest("hex")
        .slice(0, 24);
      const cacheDir = path.join(app.getPath("temp"), "xiaomei-brain", "assignments", cacheKey);
      await fs.mkdir(cacheDir, { recursive: true });
      const cachePath = path.join(cacheDir, safeName);
      await fs.writeFile(cachePath, data);
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
    agentId: string; primary: string; vision?: string; baseHash?: string;
  }) => channelRpc(args, "model.selection.set", {
    primary: args.primary,
    vision: args.vision || "",
    base_hash: args.baseHash || "",
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
