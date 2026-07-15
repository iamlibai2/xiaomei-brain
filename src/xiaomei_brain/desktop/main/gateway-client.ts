import WebSocket from "ws";
import { EventEmitter } from "events";

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: string;
  method: string;
  params: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
}

export class GatewayClient extends EventEmitter {
  private ws: WebSocket | null = null;
  private counter = 0;
  private pending = new Map<string, (res: JsonRpcResponse) => void>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private _connected = false;
  private _closed = false;

  get connected(): boolean {
    return this._connected;
  }

  connect(host: string, port: number): Promise<void> {
    return new Promise((resolve, reject) => {
      this._closed = false;
      const url = `ws://${host}:${port}/ws`;
      this.ws = new WebSocket(url);

      this.ws.on("open", () => {
        this._connected = true;
        this.reconnectDelay = 1000;
        this.startPing();
        resolve();
      });

      this.ws.on("message", (raw) => {
        try {
          const data = JSON.parse(raw.toString());
          this.handleMessage(data);
        } catch {
          // ignore malformed messages
        }
      });

      this.ws.on("close", () => {
        this._connected = false;
        this.stopPing();
        this.scheduleReconnect(host, port);
      });

      this.ws.on("error", (err) => {
        this._connected = false;
        reject(err);
      });
    });
  }

  disconnect(): void {
    this._closed = true;
    this._connected = false;
    this.stopPing();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    for (const [id, resolve] of this.pending) {
      resolve({ jsonrpc: "2.0", id, error: { code: -32099, message: "Disconnected" } });
    }
    this.pending.clear();
  }

  async rpc(method: string, params: Record<string, unknown> = {}): Promise<JsonRpcResponse> {
    return new Promise((resolve) => {
      const id = this.nextId();
      const req: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
      this.pending.set(id, resolve);
      this.ws?.send(JSON.stringify(req));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          resolve({ jsonrpc: "2.0", id, error: { code: -32099, message: "Timeout" } });
        }
      }, 30000);
    });
  }

  // ─── private ─────────────────────────────────

  private handleMessage(data: Record<string, unknown>): void {
    if (data["method"] === "event") {
      const params = (data["params"] || {}) as Record<string, unknown>;
      this.emit("event", params["event"] as string, params["data"] || {});
      return;
    }

    const id = data["id"] as string;
    if (id && this.pending.has(id)) {
      const resolve = this.pending.get(id)!;
      this.pending.delete(id);
      resolve(data as unknown as JsonRpcResponse);
    }

    if (data["type"] === "pong") {
      this.emit("pong");
    }
  }

  private nextId(): string {
    this.counter += 1;
    return `gw-${this.counter}`;
  }

  private pingTimer: ReturnType<typeof setInterval> | null = null;

  private startPing(): void {
    this.pingTimer = setInterval(() => {
      if (this._connected && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 20000);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleReconnect(host: string, port: number): void {
    if (this._closed || this.reconnectTimer) return;
    this.emit("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this._closed) return;
      this.connect(host, port).catch(() => {
        if (this._closed) return;
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
        this.scheduleReconnect(host, port);
      });
    }, this.reconnectDelay);
  }
}
