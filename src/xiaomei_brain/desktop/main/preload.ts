import { contextBridge, ipcRenderer } from "electron";

export interface GatewayAPI {
  connect: (args: {
    host: string;
    port: number;
    token: string;
    userId: string;
  }) => Promise<unknown>;
  disconnect: () => Promise<void>;
  sendMessage: (args: { content: string }) => Promise<unknown>;
  abortMessage: () => Promise<unknown>;
  getHistory: (args: {
    sessionId?: string;
    limit?: number;
  }) => Promise<unknown>;
  listIdentities: () => Promise<unknown>;
  getSessions: () => Promise<unknown>;
  getMessages: (args: {
    sessionId: string;
    limit?: number;
  }) => Promise<unknown>;
  getConfig: (key: string) => Promise<unknown>;
  onEvent: (callback: (event: string, data: unknown) => void) => void;
  removeEventListener: () => void;
}

const api: GatewayAPI = {
  connect: (args) => ipcRenderer.invoke("gateway:connect", args),
  disconnect: () => ipcRenderer.invoke("gateway:disconnect"),
  sendMessage: (args) => ipcRenderer.invoke("gateway:sendMessage", args),
  abortMessage: () => ipcRenderer.invoke("gateway:abortMessage"),
  getHistory: (args) => ipcRenderer.invoke("gateway:getHistory", args),
  listIdentities: () => ipcRenderer.invoke("gateway:listIdentities"),
  getSessions: () => ipcRenderer.invoke("store:getSessions"),
  getMessages: (args) => ipcRenderer.invoke("store:getMessages", args),
  getConfig: (key) => ipcRenderer.invoke("store:getConfig", key),

  onEvent: (callback) => {
    const handler = (_event: unknown, data: { event: string; data: unknown }) => {
      callback(data.event, data.data);
    };
    ipcRenderer.on("gateway:event", handler);
    (api as unknown as Record<string, unknown>)["_eventHandler"] = handler;
  },

  removeEventListener: () => {
    const handler = (api as unknown as Record<string, unknown>)["_eventHandler"];
    if (handler) {
      ipcRenderer.removeListener("gateway:event", handler as (...args: unknown[]) => void);
    }
  },
};

contextBridge.exposeInMainWorld("gateway", api);
