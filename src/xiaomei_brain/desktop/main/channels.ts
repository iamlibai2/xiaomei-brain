/**
 * CHANNEL_MAP — 声明式 IPC 通道定义
 *
 * 这是唯一需要手写的地方。新增 API 只需在这里加一行，
 * buildBridge() 自动生成 preload API，类型自动推导到 renderer。
 */

export interface InvokeChannel {
  invoke: string;
}

export interface SendChannel {
  send: string;
}

export interface EventChannel {
  event: string;
}

export type ChannelDef = InvokeChannel | SendChannel | EventChannel;

export const CHANNEL_MAP = {
  gateway: {
    connect:         { invoke: "gateway:connect" },
    disconnect:      { invoke: "gateway:disconnect" },
    sendMessage:     { invoke: "gateway:sendMessage" },
    abortMessage:    { invoke: "gateway:abortMessage" },
    getHistory:      { invoke: "gateway:getHistory" },
    listIdentities:  { invoke: "gateway:listIdentities" },
    getSessions:     { invoke: "store:getSessions" },
    getMessages:     { invoke: "store:getMessages" },
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
