import { ipcMain, BrowserWindow } from "electron";
import { GatewayClient } from "./gateway-client";
import { Store } from "./store";

export function registerIpcHandlers(
  gateway: GatewayClient,
  store: Store,
  getWindow: () => BrowserWindow | null
): void {
  // ─── connect ────────────────────────────────

  ipcMain.handle(
    "gateway:connect",
    async (
      _event,
      args: { host: string; port: number; token: string; userId: string }
    ) => {
      try {
        await gateway.connect(args.host, args.port);
      } catch (e) {
        return { error: { code: -32099, message: `Connection failed: ${e}` } };
      }

      const res = await gateway.rpc("connect", {
        token: args.token,
        client: "desktop",
        user_id: args.userId,
      });

      if (res.error) return res;

      const result = res.result || {};
      const sessionId = (result["session_id"] as string) || "";
      const agentName = (result["agent_name"] as string) || "";

      store.upsertSession(sessionId, agentName);
      store.setConfig("last_host", args.host);
      store.setConfig("last_port", String(args.port));

      return { result: { session_id: sessionId, agent_name: agentName } };
    }
  );

  // ─── disconnect ─────────────────────────────

  ipcMain.handle("gateway:disconnect", async () => {
    gateway.disconnect();
  });

  // ─── chat.send ──────────────────────────────

  ipcMain.handle(
    "gateway:sendMessage",
    async (_event, args: { content: string }) => {
      const res = await gateway.rpc("chat.send", {
        content: args.content,
      });
      return res;
    }
  );

  // ─── chat.abort ─────────────────────────────

  ipcMain.handle("gateway:abortMessage", async () => {
    const res = await gateway.rpc("chat.abort", {});
    return res;
  });

  // ─── chat.history ───────────────────────────

  ipcMain.handle(
    "gateway:getHistory",
    async (_event, args: { sessionId?: string; limit?: number }) => {
      const res = await gateway.rpc("chat.history", {
        session_id: args.sessionId || "",
        limit: args.limit || 50,
      });
      return res;
    }
  );

  // ─── identity.list ──────────────────────────

  ipcMain.handle("gateway:listIdentities", async () => {
    const res = await gateway.rpc("identity.list", {});
    return res;
  });

  // ─── Sessions (local) ───────────────────────

  ipcMain.handle("store:getSessions", async () => {
    return store.getSessions();
  });

  ipcMain.handle(
    "store:getMessages",
    async (_event, args: { sessionId: string; limit?: number }) => {
      return store.getMessages(args.sessionId, args.limit || 200);
    }
  );

  // ─── Config ─────────────────────────────────

  ipcMain.handle("store:getConfig", async (_event, key: string) => {
    return store.getConfig(key);
  });

  // ─── Gateway events → renderer ──────────────

  const events = [
    "chat.chunk",
    "session.message",
    "tool.start",
    "tool.complete",
    "chat.error",
    "reconnecting",
    "pong",
  ];

  for (const eventName of events) {
    gateway.on(eventName, (data: unknown) => {
      const win = getWindow();
      if (win) {
        win.webContents.send("gateway:event", { event: eventName, data });
      }
    });
  }
}
