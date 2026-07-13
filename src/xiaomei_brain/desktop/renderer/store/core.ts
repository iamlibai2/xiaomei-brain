import { create } from "zustand";
import { produce } from "immer";
import type { AgentEntry } from "../types";

// ── Persistence (manual, avoid zustand/persist rehydration during render) ──

const STORAGE_KEY = "xiaomei-brain-agents";

function loadPersisted(): { agents?: AgentEntry[]; userId?: string; activeAgentId?: string | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* corrupted data */ }
  return {};
}

function savePersisted(state: CoreState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      agents: state.agents,
      userId: state.userId,
      activeAgentId: state.activeAgentId,
    }));
  } catch { /* quota exceeded */ }
}

// ── Module-level per-agent streaming state ──
const _streamingByAgent: Record<string, { ref: string; id: string | null }> = {};

// ── Types ──

export interface DisplayMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  streaming: boolean;
}

export type HomeMode = "working" | "coding" | "design";

export interface ConnectionState {
  status: "disconnected" | "connecting" | "connected" | "error";
  agentName: string;
  error: string;
}

interface CoreState {
  connectionByAgent: Record<string, ConnectionState>;
  messagesByAgent: Record<string, DisplayMessage[]>;
  sending: boolean;
  activeAgentId: string | null;
  agents: AgentEntry[];
  userId: string;
  mode: HomeMode;
  page: "connect" | "chat";
  terminalOpen: boolean;
  activeNav: string;
  unreadByAgent: Record<string, number>;
}

interface CoreActions {
  connect: (host: string, port: number, token: string, userId: string) => Promise<boolean>;
  connectToAgent: (agentId: string) => Promise<void>;
  switchAgent: (agentId: string) => Promise<void>;
  addAgent: (host: string, port: number, token: string) => void;
  removeAgent: (agentId: string) => void;
  disconnectAgent: (agentId: string) => Promise<void>;
  sendMessage: (text: string) => void;
  abortMessage: () => Promise<void>;
  newTask: () => void;
  setMode: (mode: HomeMode) => void;
  setPage: (page: "connect" | "chat") => void;
  setTerminalOpen: (open: boolean) => void;
  setActiveNav: (nav: string) => void;
  clearUnread: (agentId: string) => void;
}

// ── Store ──

const persisted = loadPersisted();

export const useCoreStore = create<CoreState & CoreActions>()((set, get) => ({
  connectionByAgent: {},
  messagesByAgent: {},
  sending: false,
  activeAgentId: persisted.activeAgentId ?? null,
  agents: persisted.agents ?? [],
  userId: persisted.userId ?? "",
  mode: "working" as HomeMode,
  page: (persisted.agents && persisted.agents.length > 0) ? "chat" : "connect",
  terminalOpen: false,
  activeNav: "assistant",
  unreadByAgent: {},

  // ── Connect (first-time from ConnectPage) ──

  connect: async (host, port, token, userId) => {
    const agentId = `${host}:${port}`;

    set(produce((s: CoreState) => {
      s.userId = userId;
      s.connectionByAgent[agentId] = { status: "connecting", agentName: "", error: "" };
    }));

    try {
      const res = await window.gateway.connect({ host, port, token, userId, agentId });
      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: "", error: res.error!.message };
        }));
        return false;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const agentName = (result.agent_name as string) || host;

      const existing = get().agents.find(a => a.id === agentId);
      if (!existing) {
        set(produce((s: CoreState) => {
          s.agents.push({ id: agentId, name: agentName, host, port, token });
          s.activeAgentId = agentId;
          s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
          if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        }));
      } else {
        set(produce((s: CoreState) => {
          s.activeAgentId = agentId;
          s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
        }));
      }

      return true;
    } catch (err) {
      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "error", agentName: "", error: String(err) };
      }));
      return false;
    }
  },

  // ── Connect to existing agent (auto-reconnect) ──

  connectToAgent: async (agentId) => {
    const agent = get().agents.find(a => a.id === agentId);
    if (!agent) return;

    const current = get().connectionByAgent[agentId];
    if (current?.status === "connected" || current?.status === "connecting") return;

    set(produce((s: CoreState) => {
      const prev = s.connectionByAgent[agentId];
      s.connectionByAgent[agentId] = { status: "connecting", agentName: prev?.agentName || "", error: "" };
    }));

    try {
      const res = await window.gateway.connect({
        host: agent.host, port: agent.port, token: agent.token,
        userId: get().userId, agentId,
      });

      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: res.error!.message };
        }));
        return;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const agentName = (result.agent_name as string) || agent.name;

      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
      }));
    } catch (err) {
      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: String(err) };
      }));
    }
  },

  // ── Switch active agent ──

  switchAgent: async (agentId) => {
    set(produce((s: CoreState) => {
      s.activeAgentId = agentId;
      s.unreadByAgent[agentId] = 0;
    }));

    const state = get();
    if (state.connectionByAgent[agentId]?.status !== "connected") {
      await get().connectToAgent(agentId);
    }
  },

  // ── Add agent ──

  addAgent: (host, port, token) => {
    const agentId = `${host}:${port}`;
    if (get().agents.find(a => a.id === agentId)) return;

    set(produce((s: CoreState) => {
      s.agents.push({ id: agentId, name: agentId, host, port, token });
      if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
    }));

    get().connectToAgent(agentId);
  },

  // ── Remove agent ──

  removeAgent: (agentId) => {
    window.gateway.disconnect({ agentId }).catch(() => {});

    set(produce((s: CoreState) => {
      delete s.connectionByAgent[agentId];
      delete s.messagesByAgent[agentId];
      s.agents = s.agents.filter(a => a.id !== agentId);
      if (s.activeAgentId === agentId) {
        s.activeAgentId = s.agents.length > 0 ? s.agents[0].id : null;
      }
    }));

    delete _streamingByAgent[agentId];
  },

  // ── Disconnect agent ──

  disconnectAgent: async (agentId) => {
    await window.gateway.disconnect({ agentId });
    set(produce((s: CoreState) => {
      const c = s.connectionByAgent[agentId];
      if (c) c.status = "disconnected";
    }));
  },

  // ── Send message ──

  sendMessage: (text) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;

    set(produce((s: CoreState) => {
      if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
      s.messagesByAgent[agentId].push({
        id: "user-" + Date.now(), role: "user", content: text, streaming: false,
      });
      s.sending = true;
    }));

    window.gateway.sendMessage({ content: text, agentId });
  },

  // ── Abort message ──

  abortMessage: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;

    await window.gateway.abortMessage({ agentId });

    const ss = _streamingByAgent[agentId];
    if (ss) { ss.id = null; ss.ref = ""; }
    set(produce((s: CoreState) => { s.sending = false; }));
  },

  // ── New task ──

  newTask: () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    set(produce((s: CoreState) => {
      s.messagesByAgent[agentId] = [];
    }));
  },

  // ── UI ──

  setMode: (mode) => set(produce((s: CoreState) => { s.mode = mode; })),
  setPage: (page) => set(produce((s: CoreState) => { s.page = page; })),
  setTerminalOpen: (open) => set(produce((s: CoreState) => { s.terminalOpen = open; })),
  setActiveNav: (nav) => set(produce((s: CoreState) => { s.activeNav = nav; })),
  clearUnread: (agentId) => set(produce((s: CoreState) => { s.unreadByAgent[agentId] = 0; })),
}));

// Persist agents / userId / activeAgentId to localStorage on every change
useCoreStore.subscribe((state) => savePersisted(state));

// ── Gateway event handler ──

export function initGatewayEvents() {
  window.gateway.onEvent((raw: { event: string; data: unknown; agentId: string }) => {
    const { event, data: rawData, agentId } = raw;
    const d = (rawData || {}) as Record<string, unknown>;
    const text = (d.text || "") as string;
    const store = useCoreStore.getState;
    const setState = useCoreStore.setState;

    if (!agentId) return;

    if (!_streamingByAgent[agentId]) {
      _streamingByAgent[agentId] = { ref: "", id: null };
    }
    const stream = _streamingByAgent[agentId];

    if (!store().messagesByAgent[agentId]) {
      setState(produce((s: CoreState) => { s.messagesByAgent[agentId] = []; }));
    }

    if (event === "chat.chunk") {
      stream.ref += text;
      if (!stream.id) {
        stream.id = "streaming-" + Date.now();
        setState(produce((s: CoreState) => {
          s.messagesByAgent[agentId].push({
            id: stream.id!, role: "agent", content: stream.ref, streaming: true,
          });
        }));
      } else {
        setState(produce((s: CoreState) => {
          const idx = s.messagesByAgent[agentId].findIndex(m => m.id === stream.id);
          if (idx !== -1) s.messagesByAgent[agentId][idx].content = stream.ref;
        }));
      }
    } else if (event === "session.message") {
      if (stream.id) {
        const finalText = stream.ref || text;
        setState(produce((s: CoreState) => {
          const idx = s.messagesByAgent[agentId].findIndex(m => m.id === stream.id);
          if (idx !== -1) {
            s.messagesByAgent[agentId][idx].content = finalText;
            s.messagesByAgent[agentId][idx].streaming = false;
          }
        }));
        stream.id = null;
        stream.ref = "";
      } else if (text) {
        // Skip if the last agent message already has the same content (duplicate session.message)
        const msgs = store().messagesByAgent[agentId];
        const lastMsg = msgs && msgs.length > 0 ? msgs[msgs.length - 1] : null;
        const isDuplicate = lastMsg && lastMsg.role === "agent" && lastMsg.content === text;
        if (!isDuplicate) {
          setState(produce((s: CoreState) => {
            s.messagesByAgent[agentId].push({
              id: "msg-" + Date.now(), role: "agent", content: text, streaming: false,
            });
          }));
        }
      }
      if (agentId === store().activeAgentId) {
        setState(produce((s: CoreState) => { s.sending = false; }));
      } else {
        // Increment unread for background agent
        const current = store().unreadByAgent[agentId] || 0;
        setState(produce((s: CoreState) => { s.unreadByAgent[agentId] = current + 1; }));
      }
    } else if (event === "chat.error") {
      const err = (d.text || "Unknown error") as string;
      setState(produce((s: CoreState) => {
        s.messagesByAgent[agentId].push({
          id: "err-" + Date.now(), role: "agent", content: `Error: ${err}`, streaming: false,
        });
      }));
      stream.id = null;
      stream.ref = "";
      if (agentId === store().activeAgentId) {
        setState(produce((s: CoreState) => { s.sending = false; }));
      }
    }
  });
}
