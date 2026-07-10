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

export interface GatewayAPI {
  connect: (args: {
    host: string;
    port: number;
    token: string;
    userId: string;
  }) => Promise<JsonRpcResponse>;
  disconnect: () => Promise<void>;
  sendMessage: (args: { content: string }) => Promise<JsonRpcResponse>;
  abortMessage: () => Promise<JsonRpcResponse>;
  getHistory: (args: {
    sessionId?: string;
    limit?: number;
  }) => Promise<JsonRpcResponse>;
  listIdentities: () => Promise<JsonRpcResponse>;
  getSessions: () => Promise<Session[]>;
  getMessages: (args: {
    sessionId: string;
    limit?: number;
  }) => Promise<Message[]>;
  getConfig: (key: string) => Promise<string | null>;
  onEvent: (callback: (event: string, data: unknown) => void) => void;
  removeEventListener: () => void;
}

declare global {
  interface Window {
    gateway: GatewayAPI;
    win: {
      minimize: () => void;
      maximize: () => void;
      close: () => void;
      isMaximized: () => Promise<boolean>;
      onMaximizeChange: (callback: (maximized: boolean) => void) => void;
    };
  }
}
