import { create } from "zustand";
import { produce } from "immer";

// ── Module-level streaming state ──
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

export interface SessionInfo {
  id: string;
  agent_name: string;
  last_active: number;
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
  loadSessions: () => Promise<void>;
  loadSessionMessages: (sessionId: string) => Promise<void>;
  newTask: (agentName: string) => Promise<void>;
  setActiveNav: (nav: string) => void;
  setMode: (mode: HomeMode) => void;
  setPage: (page: "connect" | "chat") => void;
}

// ── Store ──

export const useCoreStore = create<CoreState & CoreActions>((set, get) => ({
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
      const sessionId = (result.session_id as string) || "";
      const agentName = (result.agent_name as string) || "";
      set(produce((s: CoreState) => {
        s.connection.status = "connected";
        s.connection.sessionId = sessionId;
        s.connection.agentName = agentName;
        s.connection.error = "";
        s.activeSessionId = sessionId;
      }));
      // 加载历史会话和当前会话消息
      await get().loadSessions();
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
    const userMsg: DisplayMessage = { id: "user-" + Date.now(), role: "user", content: text, streaming: false };
    get().appendMessage(userMsg);
    // 持久化用户消息
    const sid = get().activeSessionId;
    if (sid) {
      window.gateway.saveMessage({ sessionId: sid, role: "user", content: text });
    }
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
  loadSessions: async () => {
    const sessions = await window.gateway.getSessions();
    set(produce((s: CoreState) => {
      s.sessions = sessions.map((ses: { id: string; agent_name: string; last_active: number }) => ({
        id: ses.id,
        agent_name: ses.agent_name,
        last_active: ses.last_active,
      }));
    }));
    // 加载当前会话的消息
    const activeId = get().activeSessionId;
    if (activeId) {
      await get().loadSessionMessages(activeId);
    }
  },

  loadSessionMessages: async (sessionId: string) => {
    const msgs = await window.gateway.getMessages({ sessionId });
    const displayMsgs: DisplayMessage[] = msgs.map((m: { id: number; role: string; content: string }) => ({
      id: `db-${m.id}`,
      role: m.role as "user" | "agent",
      content: m.content,
      streaming: false,
    }));
    set(produce((s: CoreState) => {
      s.activeSessionId = sessionId;
      s.messages = displayMsgs;
    }));
  },

  newTask: async (agentName: string) => {
    // 如果当前会话已经是空白的，不重复创建，直接复用
    const { messages, activeSessionId } = get();
    if (activeSessionId && messages.length === 0) return;
    const res = await window.gateway.createSession({ agentName });
    set(produce((s: CoreState) => {
      s.activeSessionId = res.id;
      s.messages = [];
    }));
    await get().loadSessions();
  },

  // ── UI ──
  setActiveNav: (nav) => set(produce((s: CoreState) => { s.activeNav = nav; })),
  setMode: (mode) => set(produce((s: CoreState) => { s.mode = mode; })),
  setPage: (page) => set(produce((s: CoreState) => { s.page = page; })),
}));

// ── Gateway event handler ──

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
      let finalText = "";
      if (_streamingId) {
        finalText = _streamRef || text;
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
        finalText = text;
        store().appendMessage({ id: "msg-" + Date.now(), role: "agent", content: text, streaming: false });
      }
      // 持久化 agent 消息
      const sid = useCoreStore.getState().activeSessionId;
      if (sid && finalText) {
        window.gateway.saveMessage({ sessionId: sid, role: "agent", content: finalText });
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
