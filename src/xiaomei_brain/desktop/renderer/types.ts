// ── Shared data types ──

export interface JsonRpcResponse {
  jsonrpc: string;
  id: string;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
}

export interface Session {
  id: string;
  agent_name: string;
  created_at: number;
  last_active: number;
}

export interface Message {
  id: number;
  session_id: string;
  role: "user" | "agent" | "tool";
  content: string;
  tool_name?: string;
  tool_status?: string;
  created_at: number;
}

// ── Bridge API 类型（与 main/channels.ts 的 CHANNEL_MAP 对应）──

export interface GatewayBridge {
  connect(args: { host: string; port: number; token: string; userId: string }): Promise<JsonRpcResponse>;
  disconnect(): Promise<void>;
  sendMessage(args: { content: string }): Promise<JsonRpcResponse>;
  abortMessage(): Promise<JsonRpcResponse>;
  getHistory(args: { sessionId?: string; limit?: number }): Promise<JsonRpcResponse>;
  listIdentities(): Promise<JsonRpcResponse>;
  getSessions(): Promise<Session[]>;
  getMessages(args: { sessionId: string; limit?: number }): Promise<Message[]>;
  getConfig(key: string): Promise<string | null>;

  /**
   * 订阅 gateway 推送事件。
   * main 进程通过 webContents.send("gateway:event", { event, data }) 推送，
   * buildBridge 的 event handler 直接透传 IPC 数据。
   */
  onEvent(callback: (raw: { event: string; data: unknown }) => void): () => void;
}

export interface WinBridge {
  minimize(): void;
  maximize(): void;
  close(): void;
  isMaximized(): Promise<boolean>;
  onMaximizeChange(callback: (maximized: boolean) => void): void;
}

declare global {
  interface Window {
    gateway: GatewayBridge;
    win: WinBridge;
  }
}
