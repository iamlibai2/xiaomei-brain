// ── Shared data types ──

export interface JsonRpcResponse {
  jsonrpc: string;
  id: string;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
}

// ── Agent entry ──

export interface AgentEntry {
  id: string;       // `${host}:${port}`
  name: string;     // agent display name (from connect RPC agent_name)
  host: string;
  port: number;
  token: string;
}

// ── Bridge API ──

export interface GatewayBridge {
  connect(args: { host: string; port: number; token: string; userId: string; agentId: string }): Promise<JsonRpcResponse>;
  disconnect(args: { agentId: string }): Promise<void>;
  sendMessage(args: { content: string; agentId: string }): Promise<JsonRpcResponse>;
  abortMessage(args: { agentId: string }): Promise<JsonRpcResponse>;
  getHistory(args: { sessionId?: string; limit?: number; agentId: string }): Promise<JsonRpcResponse>;
  listIdentities(args: { agentId: string }): Promise<JsonRpcResponse>;
  getConfig(key: string): Promise<string | null>;

  /**
   * Subscribe to gateway push events. Callback receives { event, data, agentId }.
   */
  onEvent(callback: (raw: { event: string; data: unknown; agentId: string }) => void): () => void;
}

export interface WinBridge {
  minimize(): void;
  maximize(): void;
  close(): void;
  isMaximized(): Promise<boolean>;
  onMaximizeChange(callback: (maximized: boolean) => void): void;
}

export interface TerminalBridge {
  spawn(args: { cols: number; rows: number }): Promise<{ id: string; shell: string; cwd: string }>;
  write(data: string): Promise<void>;
  resize(args: { cols: number; rows: number }): Promise<void>;
  dispose(): Promise<void>;
  onData(callback: (data: string) => void): () => void;
  onExit(callback: (code: number) => void): () => void;
}

declare global {
  interface Window {
    gateway: GatewayBridge;
    win: WinBridge;
    terminal: TerminalBridge;
  }
}
