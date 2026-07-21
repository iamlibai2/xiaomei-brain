import { ipcMain, BrowserWindow, Notification, dialog } from "electron";
import { promises as fs } from "fs";
import path from "path";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { TerminalManager } from "./terminal-manager";
import { discoverLocalAgents } from "./local-agent-discovery";
import { AgentLifecycleAction, RuntimeManager } from "./runtime-manager";
import { sanitizeNotificationText } from "./notification-text";

const connections = new Map<string, GatewayClient>();
const connectionSessions = new Map<string, string>();
const connectionUsers = new Map<string, string>();
const connectionReady = new Map<string, boolean>();
const activeNotifications = new Set<Notification>();
const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
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
  void runtimeManager.warmup().catch((error) => {
    console.error("[runtime] background initialization failed", error);
  });

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
      connectionUsers.delete(args.connectionId);
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

  // ─── connect ────────────────────────────────

  ipcMain.handle(
    "gateway:connect",
    async (
      _event,
      args: { host: string; port: number; token: string; userId: string; agentId: string; sessionId?: string }
    ) => {
      try {
        // Disconnect existing connection for this agent
        const existing = connections.get(args.agentId);
        if (existing) existing.disconnect();
        connections.delete(args.agentId);
        connectionSessions.delete(args.agentId);
        connectionUsers.delete(args.agentId);
        connectionReady.delete(args.agentId);

        const client = new GatewayClient();
        let sessionId = args.sessionId || "";
        let authenticated = false;
        let reauthenticating = false;

        const sendGatewayEvent = (event: string, data: unknown = {}) => {
          const win = getWindow();
          if (win) {
            win.webContents.send("gateway:event", { event, data, agentId: args.agentId });
          }
        };

        // Forward events with agentId tag
        client.on("event", (eventName: string, data: unknown) => {
          const eventData = data && typeof data === "object" && !Array.isArray(data)
            ? {
                ...(data as Record<string, unknown>),
                session_id: (data as Record<string, unknown>).session_id || sessionId,
              }
            : data;
          sendGatewayEvent(eventName, eventData);
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
            user_id: args.userId,
            session_id: sessionId,
          }).then(async (res) => {
            if (res.error) {
              sendGatewayEvent("reconnect.error", { message: res.error.message });
              return;
            }

            const result = res.result || {};
            sessionId = (result["session_id"] as string) || sessionId;
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
          user_id: args.userId,
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
        authenticated = true;
        connectionSessions.set(args.agentId, sessionId);
        connectionUsers.set(args.agentId, args.userId);

        const resume = await client.rpc("session.resume", {
          session_id: sessionId,
          history_limit: 50,
        });
        if (resume.error) {
          client.disconnect();
          connections.delete(args.agentId);
          connectionSessions.delete(args.agentId);
          connectionUsers.delete(args.agentId);
          connectionReady.delete(args.agentId);
          return resume;
        }
        connectionReady.set(args.agentId, true);

        // Persist last connection params
        config.set("last_host", args.host);
        config.set("last_port", String(args.port));

        return {
          result: {
            session_id: sessionId,
            agent_name: agentName,
            resume: resume.result || {},
          },
        };
      } catch (e) {
        connections.get(args.agentId)?.disconnect();
        connections.delete(args.agentId);
        connectionSessions.delete(args.agentId);
        connectionUsers.delete(args.agentId);
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
    connectionUsers.delete(args.agentId);
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
        user_id: connectionUsers.get(args.agentId) || "",
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

  ipcMain.handle(
    "notification:show",
    async (_event, args: { title: string; body: string; agentId: string; sessionId: string }) => {
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

  // ─── Config (local JSON) ────────────────────

  ipcMain.handle("store:getConfig", async (_event, key: string) => {
    return config.get(key);
  });

  // ─── Terminal ────────────────────────────────

  ipcMain.handle(
    "terminal:spawn",
    async (_event, args: { cols: number; rows: number }) => {
      const win = getWindow();
      if (!win) return { error: "No window" };

      const result = terminalMgr.spawn(
        args.cols || 80,
        args.rows || 24,
        (data: string) => {
          win.webContents.send("terminal:data", data);
        },
        (code: number) => {
          win.webContents.send("terminal:exit", code);
        }
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
