import { contextBridge, ipcRenderer } from "electron";

// ── CHANNEL_MAP — 声明式 IPC 通道定义 ──

interface InvokeChannel {
  invoke: string;
}

interface SendChannel {
  send: string;
}

interface EventChannel {
  event: string;
}

const CHANNEL_MAP = {
  gateway: {
    connect:         { invoke: "gateway:connect" },
    disconnect:      { invoke: "gateway:disconnect" },
    sendMessage:     { invoke: "gateway:sendMessage" },
    abortMessage:    { invoke: "gateway:abortMessage" },
    getHistory:      { invoke: "gateway:getHistory" },
    listIdentities:  { invoke: "gateway:listIdentities" },
    getConfig:       { invoke: "store:getConfig" },
    onEvent:         { event: "gateway:event" },
  },
  win: {
    minimize:          { send: "window:minimize" },
    maximize:          { send: "window:maximize" },
    close:             { send: "window:close" },
    isMaximized:       { invoke: "window:isMaximized" },
    onMaximizeChange:  { event: "window:maximizeChanged" },
  },
} as const;

// ── buildBridge ──

function isInvoke(def: unknown): def is InvokeChannel {
  return typeof def === "object" && def !== null && "invoke" in def;
}

function isSend(def: unknown): def is SendChannel {
  return typeof def === "object" && def !== null && "send" in def;
}

function isEvent(def: unknown): def is EventChannel {
  return typeof def === "object" && def !== null && "event" in def;
}

function buildBridge(map: typeof CHANNEL_MAP): void {
  for (const [namespace, methods] of Object.entries(map)) {
    const api: Record<string, unknown> = {};

    for (const [name, def] of Object.entries(methods)) {
      if (isInvoke(def)) {
        api[name] = (args: unknown) => ipcRenderer.invoke(def.invoke, args);
      } else if (isSend(def)) {
        api[name] = (...args: unknown[]) => ipcRenderer.send(def.send, ...args);
      } else if (isEvent(def)) {
        api[name] = (callback: (...cbArgs: unknown[]) => void) => {
          const handler = (_event: Electron.IpcRendererEvent, ...cbArgs: unknown[]) => {
            callback(...cbArgs);
          };
          ipcRenderer.on(def.event, handler);
          return () => {
            ipcRenderer.removeListener(def.event, handler);
          };
        };
      }
    }

    contextBridge.exposeInMainWorld(namespace, api);
  }
}

buildBridge(CHANNEL_MAP);
