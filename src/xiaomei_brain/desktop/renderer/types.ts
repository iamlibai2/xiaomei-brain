// ── Shared data types ──

export interface JsonRpcResponse {
  jsonrpc: string;
  id: string;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
}

// ── Bridge API ──

export interface GatewayBridge {
  connect(args: { host: string; port: number; token: string; userId: string }): Promise<JsonRpcResponse>;
  disconnect(): Promise<void>;
  sendMessage(args: { content: string }): Promise<JsonRpcResponse>;
  abortMessage(): Promise<JsonRpcResponse>;
  getHistory(args: { sessionId?: string; limit?: number }): Promise<JsonRpcResponse>;
  listIdentities(): Promise<JsonRpcResponse>;
  getConfig(key: string): Promise<string | null>;

  /**
   * 订阅 gateway 推送事件。
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
