import { create } from "zustand";
import { produce } from "immer";

// ── Module-level streaming state（非响应式，不需要触发 re-render）──
let _streamRef = "";
let _streamingId: string | null = null;
let _sessionMessageReceived = false;

// ── Types ──

export interface DisplayMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  streaming: boolean;
}

export type HomeMode = "working" | "coding" | "design";

interface SessionInfo {
  id: string;
  name: string;
  time: string;
  active?: boolean;
}

export interface ConnectionState {
  status: "disconnected" | "connecting" | "connected" | "error";
  sessionId: string;
  agentName: string;
  error: string;
}

interface CoreState {
  connection: ConnectionState;
  messages: DisplayMessage[];
  sending: boolean;
  sessions: SessionInfo[];
  activeSessionId: string | null;
  activeNav: string;
  mode: HomeMode;
  page: "connect" | "chat";
}

interface CoreActions {
  connect: (host: string, port: number, token: string, userId: string) => Promise<boolean>;
  disconnect: () => Promise<void>;
  appendMessage: (msg: DisplayMessage) => void;
  setSending: (v: boolean) => void;
  sendMessage: (text: string) => void;
  abortMessage: () => Promise<void>;
  setSessions: (sessions: SessionInfo[]) => void;
  setActiveSession: (id: string | null) => void;
  setActiveNav: (nav: string) => void;
  setMode: (mode: HomeMode) => void;
  setPage: (page: "connect" | "chat") => void;
}

// ── Store ──

export const useCoreStore = create<CoreState & CoreActions>((set, get) => ({
  // ── Initial state ──
  connection: { status: "disconnected", sessionId: "", agentName: "", error: "" },
  messages: [],
  sending: false,
  sessions: [],
  activeSessionId: null,
  activeNav: "assistant",
  mode: "working" as HomeMode,
  page: "connect" as "connect" | "chat",

  // ── Connection ──
  connect: async (host, port, token, userId) => {
    set(produce((s: CoreState) => {
      s.connection.status = "connecting";
      s.connection.error = "";
    }));
    try {
      const res = await window.gateway.connect({ host, port, token, userId });
      if (res.error) {
        set(produce((s: CoreState) => {
          s.connection.status = "error";
          s.connection.error = res.error!.message;
        }));
        return false;
      }
      const result = (res.result || {}) as Record<string, unknown>;
      set(produce((s: CoreState) => {
        s.connection.status = "connected";
        s.connection.sessionId = (result.session_id as string) || "";
        s.connection.agentName = (result.agent_name as string) || "";
        s.connection.error = "";
      }));
      return true;
    } catch (err) {
      set(produce((s: CoreState) => {
        s.connection.status = "error";
        s.connection.error = String(err);
      }));
      return false;
    }
  },

  disconnect: async () => {
    await window.gateway.disconnect();
    set(produce((s: CoreState) => {
      s.connection = { status: "disconnected", sessionId: "", agentName: "", error: "" };
    }));
  },

  // ── Messages ──
  appendMessage: (msg) => set(produce((s: CoreState) => { s.messages.push(msg); })),

  setSending: (v) => set(produce((s: CoreState) => { s.sending = v; })),

  sendMessage: (text) => {
    _sessionMessageReceived = false;
    get().appendMessage({ id: "user-" + Date.now(), role: "user", content: text, streaming: false });
    get().setSending(true);
    window.gateway.sendMessage({ content: text });
  },

  abortMessage: async () => {
    await window.gateway.abortMessage();
    _streamingId = null;
    _streamRef = "";
    set(produce((s: CoreState) => { s.sending = false; }));
  },

  // ── Sessions ──
  setSessions: (sessions) => set(produce((s: CoreState) => { s.sessions = sessions; })),
  setActiveSession: (id) => set(produce((s: CoreState) => { s.activeSessionId = id; })),

  // ── UI ──
  setActiveNav: (nav) => set(produce((s: CoreState) => { s.activeNav = nav; })),
  setMode: (mode) => set(produce((s: CoreState) => { s.mode = mode; })),
  setPage: (page) => set(produce((s: CoreState) => { s.page = page; })),
}));

// ── Gateway event handler ──
// 在 App 挂载时调用一次，订阅 gateway 推送事件

export function initGatewayEvents() {
  window.gateway.onEvent((raw: { event: string; data: unknown }) => {
    const event = raw.event;
    const d = (raw.data || {}) as Record<string, unknown>;
    const text = (d.text || "") as string;
    const store = useCoreStore.getState;

    if (event === "chat.chunk") {
      _sessionMessageReceived = false;
      _streamRef += text;
      if (!_streamingId) {
        _streamingId = "streaming-" + Date.now();
        store().appendMessage({ id: _streamingId, role: "agent", content: _streamRef, streaming: true });
      } else {
        useCoreStore.setState(produce((s: CoreState) => {
          const idx = s.messages.findIndex(m => m.id === _streamingId);
          if (idx !== -1) s.messages[idx].content = _streamRef;
        }));
      }
    } else if (event === "session.message") {
      if (_sessionMessageReceived) return;
      _sessionMessageReceived = true;
      if (_streamingId) {
        const finalText = _streamRef || text;
        useCoreStore.setState(produce((s: CoreState) => {
          const idx = s.messages.findIndex(m => m.id === _streamingId);
          if (idx !== -1) {
            s.messages[idx].content = finalText;
            s.messages[idx].streaming = false;
          }
        }));
        _streamingId = null;
        _streamRef = "";
      } else if (text) {
        store().appendMessage({ id: "msg-" + Date.now(), role: "agent", content: text, streaming: false });
      }
      store().setSending(false);
    } else if (event === "chat.error") {
      const err = (d.text || "Unknown error") as string;
      store().appendMessage({ id: "err-" + Date.now(), role: "agent", content: `Error: ${err}`, streaming: false });
      _streamingId = null;
      _streamRef = "";
      store().setSending(false);
    }
  });
}
