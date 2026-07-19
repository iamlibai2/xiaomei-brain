import { ipcMain, BrowserWindow, Notification } from "electron";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";
import { TerminalManager } from "./terminal-manager";
import { discoverLocalAgents } from "./local-agent-discovery";
import { AgentLifecycleAction, RuntimeManager } from "./runtime-manager";
import { sanitizeNotificationText } from "./notification-text";

const connections = new Map<string, GatewayClient>();
const connectionSessions = new Map<string, string>();
const connectionUsers = new Map<string, string>();
const activeNotifications = new Set<Notification>();

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
    }
    return runtimeManager.control(args.agentId, args.action);
  });

  // Helper: get or warn
  function getClient(agentId: string): GatewayClient | undefined {
    const c = connections.get(agentId);
    if (!c) console.warn(`[ipc] No connection for agent ${agentId}`);
    return c;
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
            ? { ...(data as Record<string, unknown>), session_id: sessionId }
            : data;
          sendGatewayEvent(eventName, eventData);
        });
        client.on("reconnecting", () => {
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
          }).then((res) => {
            if (res.error) {
              sendGatewayEvent("reconnect.error", { message: res.error.message });
              return;
            }

            const result = res.result || {};
            sessionId = (result["session_id"] as string) || sessionId;
            connectionSessions.set(args.agentId, sessionId);
            sendGatewayEvent("reconnected", {
              session_id: sessionId,
              agent_name: (result["agent_name"] as string) || "",
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

        // Persist last connection params
        config.set("last_host", args.host);
        config.set("last_port", String(args.port));

        return { result: { session_id: sessionId, agent_name: agentName } };
      } catch (e) {
        connections.get(args.agentId)?.disconnect();
        connections.delete(args.agentId);
        connectionSessions.delete(args.agentId);
        connectionUsers.delete(args.agentId);
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
  });

  // ─── chat.send ──────────────────────────────

  ipcMain.handle(
    "gateway:sendMessage",
    async (_event, args: { content: string; agentId: string }) => {
      const client = getClient(args.agentId);
      if (!client) return { error: { code: -32099, message: `Agent ${args.agentId} not connected` } };
      return client.rpc("chat.send", {
        content: args.content,
        session_id: connectionSessions.get(args.agentId) || "",
        user_id: connectionUsers.get(args.agentId) || "",
      });
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
