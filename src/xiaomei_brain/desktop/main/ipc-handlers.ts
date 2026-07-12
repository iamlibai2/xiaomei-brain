import { ipcMain, BrowserWindow } from "electron";
import { GatewayClient } from "./gateway-client";
import { ConfigStore } from "./config-store";

export function registerIpcHandlers(
  gateway: GatewayClient,
  config: ConfigStore,
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

      // Persist last connection params (JSON file — no SQLite)
      config.set("last_host", args.host);
      config.set("last_port", String(args.port));

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

  // ─── Config (local JSON) ────────────────────

  ipcMain.handle("store:getConfig", async (_event, key: string) => {
    return config.get(key);
  });

  // ─── Gateway events → renderer ──────────────

  gateway.on("event", (eventName: string, data: unknown) => {
    const win = getWindow();
    if (win) {
      win.webContents.send("gateway:event", { event: eventName, data });
    }
  });

  gateway.on("reconnecting", () => {
    const win = getWindow();
    if (win) {
      win.webContents.send("gateway:event", { event: "reconnecting", data: {} });
    }
  });

  gateway.on("pong", () => {
    const win = getWindow();
    if (win) {
      win.webContents.send("gateway:event", { event: "pong", data: {} });
    }
  });
}
