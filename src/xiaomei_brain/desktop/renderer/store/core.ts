import { create } from "zustand";
import { produce } from "immer";
import type { AgentCreationResult, AgentEntry, AgentLifecycleAction, LocalAgentInfo, SessionEntry } from "../types";

// ── Persistence (manual, avoid zustand/persist rehydration during render) ──

const STORAGE_KEY = "xiaomei-brain-agents";
const STORAGE_VERSION = 3;

interface PersistedState {
  version?: number;
  agents?: AgentEntry[];
  userId?: string;
  activeAgentId?: string | null;
  activeSessionByAgent?: Record<string, string | null>;
}

function loadPersisted(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const state = JSON.parse(raw) as PersistedState;
      if (state.version === STORAGE_VERSION) return state;

      // Session lists are now authoritative in each Agent's brain.db. Keep
      // only the selected real session ID when migrating older Desktop data.
      return {
        version: STORAGE_VERSION,
        agents: state.agents,
        userId: state.userId,
        activeAgentId: state.activeAgentId,
        activeSessionByAgent: state.activeSessionByAgent ?? {},
      };
    }
  } catch { /* corrupted data */ }
  return {};
}

function savePersisted(state: CoreState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      version: STORAGE_VERSION,
      agents: state.agents,
      userId: state.userId,
      activeAgentId: state.activeAgentId,
      activeSessionByAgent: state.activeSessionByAgent,
    }));
  } catch { /* quota exceeded */ }
}

// ── Module-level streaming state, isolated by Agent + session + turn ──
interface StreamingState { ref: string; id: string | null }
const _streamingByTurn: Record<string, StreamingState> = {};

function streamingKey(agentId: string, sessionId: string, turnId: string): string {
  return `${agentId}\u0000${sessionId || "legacy"}\u0000${turnId || "legacy"}`;
}

function clearAgentStreams(agentId: string): void {
  const prefix = `${agentId}\u0000`;
  for (const key of Object.keys(_streamingByTurn)) {
    if (key.startsWith(prefix)) delete _streamingByTurn[key];
  }
}

function toolResultFailed(result: string): boolean {
  return result.startsWith("Error:")
    || result.startsWith("Blocked")
    || result.includes("timed out")
    || result.toLowerCase().includes("failed");
}

function historyMessages(
  result: Record<string, unknown> | undefined,
  sessionId: string,
  activeInteractionIds: Set<string> = new Set(),
): DisplayMessage[] {
  const rows = Array.isArray(result?.messages) ? result.messages : [];
  return rows.flatMap((value, index) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    if (row.role === "interaction" && row.interaction && typeof row.interaction === "object") {
      const interaction = row.interaction as Record<string, unknown>;
      const id = typeof interaction.id === "string" ? interaction.id : "";
      const question = typeof interaction.question === "string" ? interaction.question : "";
      if (!id || !question) return [];
      const rawStatus = typeof interaction.status === "string" ? interaction.status : "expired";
      let status = ["pending", "answered", "cancelled", "expired"].includes(rawStatus)
        ? rawStatus as InteractionRequest["status"]
        : "expired";
      if (status === "pending" && !activeInteractionIds.has(id)) status = "expired";
      return [{
        id,
        role: "agent",
        content: "",
        streaming: false,
        interaction: {
          id,
          question,
          choices: Array.isArray(interaction.choices)
            ? interaction.choices.filter((choice): choice is string => typeof choice === "string")
            : [],
          sessionId: typeof interaction.session_id === "string" ? interaction.session_id : sessionId,
          turnId: typeof interaction.turn_id === "string" ? interaction.turn_id : "",
          status,
          response: typeof interaction.response === "string" ? interaction.response : "",
        },
      } satisfies DisplayMessage];
    }
    if (row.role === "tool") {
      const toolCallId = typeof row.tool_call_id === "string" ? row.tool_call_id : "";
      const name = typeof row.tool_name === "string" ? row.tool_name : "";
      if (!toolCallId || !name || name === "clarify") return [];
      const summary = typeof row.content === "string" ? row.content : "";
      const failed = toolResultFailed(summary);
      return [{
        id: `history-tool-${sessionId}-${toolCallId}`,
        role: "agent",
        content: "",
        streaming: false,
        tool: {
          id: toolCallId,
          name,
          arguments: {},
          status: failed ? "error" : "complete",
          summary: summary.slice(0, 800),
          truncated: summary.length > 800,
          error: failed ? summary.slice(0, 800) : "",
        },
      } satisfies DisplayMessage];
    }
    const role = row.role === "user" ? "user" : row.role === "assistant" ? "agent" : null;
    if (!role || typeof row.content !== "string") return [];
    if (role === "agent" && !row.content.trim()) return [];
    return [{
      id: typeof row.id === "number"
        ? `history-${sessionId}-${row.id}`
        : `history-${sessionId}-${String(row.created_at || index)}-${index}`,
      role,
      content: row.content,
      streaming: false,
    } satisfies DisplayMessage];
  });
}

function resumeMessages(result: Record<string, unknown> | undefined, sessionId: string): DisplayMessage[] {
  const inflight = result?.inflight && typeof result.inflight === "object"
    ? result.inflight as Record<string, unknown>
    : null;
  const items = inflight && Array.isArray(inflight.items) ? inflight.items : [];
  const activeInteractionIds = new Set<string>();
  const activeToolIds = new Set<string>();
  for (const value of items) {
    if (!value || typeof value !== "object") continue;
    const item = value as Record<string, unknown>;
    if (item.type === "interaction" && typeof item.id === "string") activeInteractionIds.add(item.id);
    if (item.type === "tool" && typeof item.id === "string") activeToolIds.add(item.id);
  }

  const history = historyMessages(result, sessionId, activeInteractionIds).filter((message) => {
    if (message.interaction && activeInteractionIds.has(message.interaction.id)) return false;
    if (message.tool && activeToolIds.has(message.tool.id)) return false;
    return true;
  });
  if (!inflight) return history;

  const turnId = typeof inflight.turn_id === "string" ? inflight.turn_id : "";
  const inflightMessages = items.flatMap((value, index): DisplayMessage[] => {
    if (!value || typeof value !== "object") return [];
    const item = value as Record<string, unknown>;
    if (item.type === "message" && typeof item.text === "string" && item.text) {
      return [{
        id: `inflight-${turnId}-message-${index}`,
        role: "agent",
        content: item.text,
        streaming: false,
      }];
    }
    if (item.type === "tool") {
      const id = typeof item.id === "string" ? item.id : "";
      const name = typeof item.name === "string" ? item.name : "";
      if (!id || !name || name === "clarify") return [];
      const status = item.status === "running" || item.status === "error" ? item.status : "complete";
      return [{
        id: `inflight-${turnId}-tool-${id}`,
        role: "agent",
        content: "",
        streaming: false,
        tool: {
          id,
          name,
          arguments: item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
            ? item.arguments as Record<string, unknown>
            : {},
          status,
          summary: typeof item.summary === "string" ? item.summary : "",
          truncated: item.truncated === true,
          error: typeof item.error === "string" ? item.error : "",
        },
      }];
    }
    if (item.type === "interaction") {
      const id = typeof item.id === "string" ? item.id : "";
      const question = typeof item.question === "string" ? item.question : "";
      if (!id || !question) return [];
      const rawStatus = typeof item.status === "string" ? item.status : "pending";
      const status = ["pending", "answered", "cancelled", "expired"].includes(rawStatus)
        ? rawStatus as InteractionRequest["status"]
        : "pending";
      return [{
        id,
        role: "agent",
        content: "",
        streaming: false,
        interaction: {
          id,
          question,
          choices: Array.isArray(item.choices)
            ? item.choices.filter((choice): choice is string => typeof choice === "string")
            : [],
          sessionId,
          turnId,
          status,
          response: typeof item.response === "string" ? item.response : "",
        },
      }];
    }
    return [];
  });
  return [...history, ...inflightMessages];
}

function restoreStreamFromResume(
  agentId: string,
  sessionId: string,
  result: Record<string, unknown> | undefined,
): void {
  const inflight = result?.inflight && typeof result.inflight === "object"
    ? result.inflight as Record<string, unknown>
    : null;
  if (!inflight) return;
  const turnId = typeof inflight.turn_id === "string" ? inflight.turn_id : "";
  const items = Array.isArray(inflight.items) ? inflight.items : [];
  const lastIndex = items.length - 1;
  const last = lastIndex >= 0 && items[lastIndex] && typeof items[lastIndex] === "object"
    ? items[lastIndex] as Record<string, unknown>
    : null;
  const key = streamingKey(agentId, sessionId, turnId);
  _streamingByTurn[key] = last?.type === "message" && typeof last.text === "string"
    ? { ref: last.text, id: `inflight-${turnId}-message-${lastIndex}` }
    : { ref: "", id: null };
}

function historyPagination(result: Record<string, unknown> | undefined): HistoryPaginationState {
  return {
    hasMore: result?.has_more === true,
    beforeId: typeof result?.next_before_id === "number" ? result.next_before_id : null,
    loading: false,
    error: "",
  };
}

function defaultSessionName(messages: DisplayMessage[]): string {
  const firstUserMessage = messages.find((message) => message.role === "user")?.content.trim();
  if (firstUserMessage) {
    return firstUserMessage.length > 24 ? `${firstUserMessage.slice(0, 24)}...` : firstUserMessage;
  }
  return new Date().toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function sessionEntries(result: Record<string, unknown> | undefined): SessionEntry[] {
  const rows = Array.isArray(result?.sessions) ? result.sessions : [];
  return rows.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    if (typeof row.session_id !== "string" || !row.session_id) return [];
    const createdAt = typeof row.created_at === "number" ? row.created_at * 1000 : Date.now();
    const updatedAt = typeof row.updated_at === "number" ? row.updated_at * 1000 : createdAt;
    const rawTitle = typeof row.first_user_message === "string"
      ? row.first_user_message.replace(/\s+/g, " ").trim()
      : "";
    const name = rawTitle
      ? rawTitle.length > 24 ? `${rawTitle.slice(0, 24)}...` : rawTitle
      : new Date(createdAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    return [{
      id: row.session_id,
      name,
      createdAt,
      updatedAt,
      messageCount: typeof row.message_count === "number" ? row.message_count : undefined,
    } satisfies SessionEntry];
  });
}

function pinActiveSession(
  sessions: SessionEntry[],
  activeSessionId: string,
  activeMessages: DisplayMessage[],
): SessionEntry[] {
  if (!activeSessionId) return sessions;
  const result = [...sessions];
  const existingIndex = result.findIndex((session) => session.id === activeSessionId);
  const active = existingIndex >= 0
    ? result.splice(existingIndex, 1)[0]
    : {
        id: activeSessionId,
        name: defaultSessionName(activeMessages),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messageCount: activeMessages.length,
      };
  result.unshift(active);
  return result;
}

function touchSession(
  state: CoreState,
  agentId: string,
  sessionId: string,
  messageDelta: number,
  firstUserText?: string,
): void {
  if (!sessionId) return;
  if (!state.sessionsByAgent[agentId]) state.sessionsByAgent[agentId] = [];
  let session = state.sessionsByAgent[agentId].find((entry) => entry.id === sessionId);
  const now = Date.now();
  if (!session) {
    session = {
      id: sessionId,
      name: defaultSessionName([]),
      createdAt: now,
      updatedAt: now,
      messageCount: 0,
    };
    state.sessionsByAgent[agentId].push(session);
  }
  if (firstUserText && (session.messageCount || 0) === 0) {
    const title = firstUserText.replace(/\s+/g, " ").trim();
    if (title) session.name = title.length > 24 ? `${title.slice(0, 24)}...` : title;
  }
  session.updatedAt = now;
  session.messageCount = Math.max(0, (session.messageCount || 0) + messageDelta);
  const activeSessionId = state.activeSessionByAgent[agentId];
  state.sessionsByAgent[agentId].sort((left, right) => {
    if (left.id === activeSessionId) return -1;
    if (right.id === activeSessionId) return 1;
    return (right.updatedAt || right.createdAt) - (left.updatedAt || left.createdAt);
  });
}

async function fetchAgentSessions(
  agentId: string,
  activeSessionId: string,
  activeMessages: DisplayMessage[],
  fallback: SessionEntry[],
): Promise<{ sessions: SessionEntry[]; listState: SessionListState }> {
  const response = await window.gateway.listSessions({ agentId, limit: 30, offset: 0, query: "" });
  const fetched = response.error ? [...fallback] : sessionEntries(response.result);
  const sessions = pinActiveSession(fetched, activeSessionId, activeMessages);
  return {
    sessions,
    listState: {
      query: "",
      loading: false,
      loadingMore: false,
      hasMore: response.result?.has_more === true,
      nextOffset: typeof response.result?.next_offset === "number" ? response.result.next_offset : null,
      error: response.error?.message || "",
    },
  };
}

// ── Types ──

export interface DisplayMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  streaming: boolean;
  interaction?: InteractionRequest;
  tool?: ToolActivity;
}

export interface ToolActivity {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "complete" | "error";
  summary: string;
  truncated: boolean;
  error: string;
}

export interface InteractionRequest {
  id: string;
  question: string;
  choices: string[];
  sessionId: string;
  turnId: string;
  status: "pending" | "responding" | "answered" | "cancelled" | "expired" | "error";
  response: string;
  error?: string;
}

export type HomeMode = "working" | "coding" | "design";

export interface ConnectionState {
  status: "disconnected" | "connecting" | "connected" | "error";
  agentName: string;
  error: string;
}

export interface HistoryPaginationState {
  hasMore: boolean;
  beforeId: number | null;
  loading: boolean;
  error: string;
}

export interface SessionListState {
  query: string;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  nextOffset: number | null;
  error: string;
}

export interface AgentLifecycleState {
  status: "idle" | "starting" | "stopping" | "restarting" | "error";
  error: string;
}

interface CoreState {
  connectionByAgent: Record<string, ConnectionState>;
  messagesByAgent: Record<string, DisplayMessage[]>;
  sendingByAgent: Record<string, boolean>;
  draftByAgent: Record<string, string>;
  activeAgentId: string | null;
  agents: AgentEntry[];
  userId: string;
  mode: HomeMode;
  page: "connect" | "chat";
  terminalOpen: boolean;
  activeNav: string;
  unreadByAgent: Record<string, number>;
  sessionsByAgent: Record<string, SessionEntry[]>;
  sessionListByAgent: Record<string, SessionListState>;
  activeSessionByAgent: Record<string, string | null>;
  historyPaginationByAgent: Record<string, Record<string, HistoryPaginationState>>;
  localAvailabilityByAgent: Record<string, boolean>;
  localInfoByAgent: Record<string, LocalAgentInfo>;
  lifecycleByAgent: Record<string, AgentLifecycleState>;
  localDiscoveryComplete: boolean;
  localDiscoveryError: string;
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
  respondToInteraction: (requestId: string, response: string) => Promise<void>;
  setDraft: (text: string) => void;
  newSession: (name?: string) => Promise<void>;
  switchSession: (sessionId: string) => Promise<void>;
  loadOlderMessages: () => Promise<void>;
  searchSessions: (query: string) => Promise<void>;
  loadMoreSessions: () => Promise<void>;
  setMode: (mode: HomeMode) => void;
  setPage: (page: "connect" | "chat") => void;
  setTerminalOpen: (open: boolean) => void;
  setActiveNav: (nav: string) => void;
  clearUnread: (agentId: string) => void;
  refreshLocalAgents: () => Promise<void>;
  createLocalAgent: (name: string, description: string) => Promise<AgentCreationResult>;
  controlLocalAgent: (agentId: string, action: AgentLifecycleAction) => Promise<void>;
}

// ── Store ──

const persisted = loadPersisted();

export const useCoreStore = create<CoreState & CoreActions>()((set, get) => ({
  connectionByAgent: {},
  messagesByAgent: {},
  sendingByAgent: {},
  draftByAgent: {},
  activeAgentId: persisted.activeAgentId ?? null,
  agents: persisted.agents ?? [],
  userId: persisted.userId ?? "",
  mode: "working" as HomeMode,
  page: (persisted.agents && persisted.agents.length > 0) ? "chat" : "connect",
  terminalOpen: false,
  activeNav: "assistant",
  unreadByAgent: {},
  sessionsByAgent: {},
  sessionListByAgent: {},
  activeSessionByAgent: persisted.activeSessionByAgent ?? {},
  historyPaginationByAgent: {},
  localAvailabilityByAgent: {},
  localInfoByAgent: {},
  lifecycleByAgent: {},
  localDiscoveryComplete: false,
  localDiscoveryError: "",

  refreshLocalAgents: async () => {
    try {
      const localAgents = await window.localAgents.discover();
      set(produce((s: CoreState) => {
        const discoveredIds = new Set<string>();

        for (const localAgent of localAgents as LocalAgentInfo[]) {
          const existing = s.agents.find((agent) =>
            agent.port === localAgent.port
            && ["localhost", "127.0.0.1"].includes(agent.host.toLowerCase()));
          const agentId = existing?.id || `${localAgent.host}:${localAgent.port}`;
          discoveredIds.add(agentId);

          if (existing) {
            existing.name = localAgent.name;
            existing.description = localAgent.description;
            existing.source = "local";
            existing.localAgentId = localAgent.agentId;
          } else {
            s.agents.push({
              id: agentId,
              name: localAgent.name,
              description: localAgent.description,
              host: localAgent.host,
              port: localAgent.port,
              token: "",
              source: "local",
              localAgentId: localAgent.agentId,
            });
          }

          s.localAvailabilityByAgent[agentId] = localAgent.online;
          s.localInfoByAgent[agentId] = localAgent;
          if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
          if (!s.connectionByAgent[agentId]) {
            s.connectionByAgent[agentId] = {
              status: "disconnected",
              agentName: localAgent.name,
              error: "",
            };
          }
        }

        for (const agent of s.agents) {
          if (agent.source === "local" && !discoveredIds.has(agent.id)) {
            s.localAvailabilityByAgent[agent.id] = false;
          }
        }

        if (!s.activeAgentId && s.agents.length > 0) s.activeAgentId = s.agents[0].id;
        if (s.agents.length > 0) s.page = "chat";
        s.localDiscoveryComplete = true;
        s.localDiscoveryError = "";
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.localDiscoveryComplete = true;
        s.localDiscoveryError = String(error);
      }));
    }
  },

  createLocalAgent: async (name, description) => {
    const result = await window.localAgents.create({ name, description });
    if (!result.ok || !result.agentId) return result;

    await get().refreshLocalAgents();
    set(produce((s: CoreState) => {
      const created = s.agents.find((agent) => agent.localAgentId === result.agentId);
      if (created) {
        s.activeAgentId = created.id;
        s.page = "chat";
      }
    }));
    return result;
  },

  controlLocalAgent: async (agentId, action) => {
    const agent = get().agents.find((entry) => entry.id === agentId);
    if (!agent || agent.source !== "local" || !agent.localAgentId) return;

    const pendingStatus = action === "start"
      ? "starting"
      : action === "stop"
        ? "stopping"
        : "restarting";
    set(produce((s: CoreState) => {
      s.lifecycleByAgent[agentId] = { status: pendingStatus, error: "" };
      if (action !== "start" && s.connectionByAgent[agentId]) {
        s.connectionByAgent[agentId].status = "disconnected";
      }
    }));

    const result = await window.localAgents.control({
      agentId: agent.localAgentId,
      connectionId: agentId,
      action,
    });
    if (!result.ok) {
      await get().refreshLocalAgents();
      set(produce((s: CoreState) => {
        s.lifecycleByAgent[agentId] = { status: "error", error: result.message };
      }));
      return;
    }

    const expectedOnline = action !== "stop";
    let reachedExpectedState = false;
    let observedAgentProcess = false;
    let agentProcessExited = false;
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await get().refreshLocalAgents();
      const state = get();
      const processIsRunning = Boolean(state.localInfoByAgent[agentId]?.pid);
      if (processIsRunning) observedAgentProcess = true;
      if (expectedOnline && observedAgentProcess && !processIsRunning) {
        agentProcessExited = true;
        break;
      }
      if (state.localAvailabilityByAgent[agentId] === expectedOnline) {
        reachedExpectedState = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    if (!reachedExpectedState) {
      set(produce((s: CoreState) => {
        s.lifecycleByAgent[agentId] = {
          status: "error",
          error: agentProcessExited
            ? "Agent process exited during startup; check logs/agent.err.log"
            : `Agent did not become ${expectedOnline ? "online" : "offline"} in time`,
        };
      }));
      return;
    }

    set(produce((s: CoreState) => {
      s.lifecycleByAgent[agentId] = { status: "idle", error: "" };
    }));
    if (expectedOnline) await get().connectToAgent(agentId);
  },

  // ── Connect (first-time from ConnectPage) ──

  connect: async (host, port, token, userId) => {
    const agentId = `${host}:${port}`;

    set(produce((s: CoreState) => {
      s.userId = userId;
      s.connectionByAgent[agentId] = { status: "connecting", agentName: "", error: "" };
    }));

    try {
      const requestedSessionId = get().activeSessionByAgent[agentId] || undefined;
      const res = await window.gateway.connect({ host, port, token, userId, agentId, sessionId: requestedSessionId });
      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: "", error: res.error!.message };
        }));
        return false;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const agentName = (result.agent_name as string) || host;
      const sessionId = (result.session_id as string) || requestedSessionId || "";
      const resume = result.resume && typeof result.resume === "object"
        ? result.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      const pagination = historyPagination(resume);
      const sessionResult = await fetchAgentSessions(
        agentId,
        sessionId,
        messages,
        get().sessionsByAgent[agentId] || [],
      );

      const existing = get().agents.find(a => a.id === agentId);
      set(produce((s: CoreState) => {
        if (!existing) {
          s.agents.push({ id: agentId, name: agentName, host, port, token, source: "manual" });
        }
        s.activeAgentId = agentId;
        s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
        s.messagesByAgent[agentId] = messages;
        s.sessionsByAgent[agentId] = sessionResult.sessions;
        s.sessionListByAgent[agentId] = sessionResult.listState;
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = pagination;
        }
        s.sendingByAgent[agentId] = resume?.state === "running" || resume?.state === "waiting_user";
      }));
      restoreStreamFromResume(agentId, sessionId, resume);

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

    if (agent.source === "local" && get().localAvailabilityByAgent[agentId] === false) {
      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = {
          status: "disconnected",
          agentName: agent.name,
          error: "",
        };
      }));
      return;
    }

    const current = get().connectionByAgent[agentId];
    if (current?.status === "connected" || current?.status === "connecting") return;

    set(produce((s: CoreState) => {
      const prev = s.connectionByAgent[agentId];
      s.connectionByAgent[agentId] = { status: "connecting", agentName: prev?.agentName || "", error: "" };
    }));

    try {
      const requestedSessionId = get().activeSessionByAgent[agentId] || undefined;
      const res = await window.gateway.connect({
        host: agent.host, port: agent.port, token: agent.token,
        userId: get().userId, agentId, sessionId: requestedSessionId,
      });

      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: res.error!.message };
        }));
        return;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const agentName = (result.agent_name as string) || agent.name;
      const sessionId = (result.session_id as string) || requestedSessionId || "";
      const resume = result.resume && typeof result.resume === "object"
        ? result.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      const pagination = historyPagination(resume);
      const sessionResult = await fetchAgentSessions(
        agentId,
        sessionId,
        messages,
        get().sessionsByAgent[agentId] || [],
      );

      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
        const savedAgent = s.agents.find(a => a.id === agentId);
        if (savedAgent && savedAgent.source !== "local") savedAgent.name = agentName;
        s.messagesByAgent[agentId] = messages;
        s.sessionsByAgent[agentId] = sessionResult.sessions;
        s.sessionListByAgent[agentId] = sessionResult.listState;
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = pagination;
        }
        s.sendingByAgent[agentId] = resume?.state === "running" || resume?.state === "waiting_user";
      }));
      restoreStreamFromResume(agentId, sessionId, resume);
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
      s.agents.push({ id: agentId, name: agentId, host, port, token, source: "manual" });
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
      delete s.sendingByAgent[agentId];
      delete s.draftByAgent[agentId];
      delete s.sessionsByAgent[agentId];
      delete s.sessionListByAgent[agentId];
      delete s.activeSessionByAgent[agentId];
      delete s.historyPaginationByAgent[agentId];
      delete s.localAvailabilityByAgent[agentId];
      delete s.localInfoByAgent[agentId];
      delete s.lifecycleByAgent[agentId];
      s.agents = s.agents.filter(a => a.id !== agentId);
      if (s.activeAgentId === agentId) {
        s.activeAgentId = s.agents.length > 0 ? s.agents[0].id : null;
      }
    }));

    clearAgentStreams(agentId);
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
    const clientRequestId = crypto.randomUUID();

    set(produce((s: CoreState) => {
      if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
      s.messagesByAgent[agentId].push({
        id: `user-${clientRequestId}`, role: "user", content: text, streaming: false,
      });
      touchSession(s, agentId, s.activeSessionByAgent[agentId] || "", 1, text);
      s.sendingByAgent[agentId] = true;
      s.draftByAgent[agentId] = "";
    }));

    void window.gateway.sendMessage({ content: text, agentId, clientRequestId }).then((res) => {
      if (!res.error && res.result?.accepted !== false) return;

      const message = res.error?.message || "Message was not accepted";
      set(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        s.messagesByAgent[agentId].push({
          id: `send-error-${Date.now()}`,
          role: "agent",
          content: `Error: ${message}`,
          streaming: false,
        });
        s.sendingByAgent[agentId] = false;
      }));
    }).catch((error) => {
      set(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        s.messagesByAgent[agentId].push({
          id: `send-error-${Date.now()}`,
          role: "agent",
          content: `Error: ${error}`,
          streaming: false,
        });
        s.sendingByAgent[agentId] = false;
      }));
    });
  },

  // ── Abort message ──

  abortMessage: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;

    const res = await window.gateway.abortMessage({ agentId });
    if (res.error) {
      set(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        s.messagesByAgent[agentId].push({
          id: `abort-error-${Date.now()}`,
          role: "agent",
          content: `Error: ${res.error!.message}`,
          streaming: false,
        });
      }));
      return;
    }

    clearAgentStreams(agentId);
    set(produce((s: CoreState) => { s.sendingByAgent[agentId] = false; }));
  },

  respondToInteraction: async (requestId, response) => {
    const agentId = get().activeAgentId;
    if (!agentId || !response.trim()) return;
    const interaction = (get().messagesByAgent[agentId] || [])
      .find((entry) => entry.interaction?.id === requestId)?.interaction;
    if (!interaction?.turnId) return;
    set(produce((s: CoreState) => {
      const message = (s.messagesByAgent[agentId] || [])
        .find((entry) => entry.interaction?.id === requestId);
      if (message?.interaction) {
        message.interaction.status = "responding";
        message.interaction.error = "";
      }
    }));
    const result = await window.gateway.respondInteraction({
      agentId,
      requestId,
      turnId: interaction.turnId,
      response: response.trim(),
    });
    if (result.error) {
      set(produce((s: CoreState) => {
        const message = (s.messagesByAgent[agentId] || [])
          .find((entry) => entry.interaction?.id === requestId);
        if (message?.interaction) {
          message.interaction.status = "error";
          message.interaction.error = result.error!.message;
        }
      }));
    }
  },

  setDraft: (text) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    set(produce((s: CoreState) => { s.draftByAgent[agentId] = text; }));
  },

  // ── Session management ──

  newSession: async (name) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    if (get().sendingByAgent[agentId]) return;
    if (get().connectionByAgent[agentId]?.status === "connecting") return;
    const agent = get().agents.find((entry) => entry.id === agentId);
    if (!agent) return;

    set(produce((s: CoreState) => {
      s.connectionByAgent[agentId] = {
        status: "connecting",
        agentName: s.connectionByAgent[agentId]?.agentName || agent.name,
        error: "",
      };
    }));

    try {
      const res = await window.gateway.connect({
        host: agent.host,
        port: agent.port,
        token: agent.token,
        userId: get().userId,
        agentId,
      });
      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: res.error!.message };
        }));
        return;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const sessionId = (result.session_id as string) || "";
      const agentName = (result.agent_name as string) || agent.name;
      set(produce((s: CoreState) => {
        s.messagesByAgent[agentId] = [];
        s.connectionByAgent[agentId] = { status: "connected", agentName, error: "" };
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = {
            hasMore: false, beforeId: null, loading: false, error: "",
          };
          if (!s.sessionsByAgent[agentId]) s.sessionsByAgent[agentId] = [];
          if (!s.sessionsByAgent[agentId].some((session) => session.id === sessionId)) {
            const now = Date.now();
            s.sessionsByAgent[agentId].unshift({
              id: sessionId,
              name: name || defaultSessionName([]),
              createdAt: now,
              updatedAt: now,
              messageCount: 0,
            });
          }
        }
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: String(error) };
      }));
    }
  },

  switchSession: async (sessionId) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    if (get().sendingByAgent[agentId]) return;
    if (get().connectionByAgent[agentId]?.status === "connecting") return;
    if (get().activeSessionByAgent[agentId] === sessionId) return;
    const agent = get().agents.find((entry) => entry.id === agentId);
    if (!agent) return;

    set(produce((s: CoreState) => {
      s.connectionByAgent[agentId] = {
        status: "connecting",
        agentName: s.connectionByAgent[agentId]?.agentName || agent.name,
        error: "",
      };
    }));

    try {
      const res = await window.gateway.connect({
        host: agent.host,
        port: agent.port,
        token: agent.token,
        userId: get().userId,
        agentId,
        sessionId,
      });
      if (res.error) {
        set(produce((s: CoreState) => {
          s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: res.error!.message };
        }));
        return;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      const resume = result.resume && typeof result.resume === "object"
        ? result.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      const pagination = historyPagination(resume);
      set(produce((s: CoreState) => {
        s.messagesByAgent[agentId] = messages;
        s.activeSessionByAgent[agentId] = sessionId;
        if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
        s.historyPaginationByAgent[agentId][sessionId] = pagination;
        s.connectionByAgent[agentId] = {
          status: "connected",
          agentName: (result.agent_name as string) || agent.name,
          error: "",
        };
        s.sendingByAgent[agentId] = resume?.state === "running" || resume?.state === "waiting_user";
      }));
      restoreStreamFromResume(agentId, sessionId, resume);
    } catch (error) {
      set(produce((s: CoreState) => {
        s.connectionByAgent[agentId] = { status: "error", agentName: agent.name, error: String(error) };
      }));
    }
  },

  // ── UI ──

  searchSessions: async (query) => {
    const agentId = get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    const normalizedQuery = query.trim();
    set(produce((s: CoreState) => {
      s.sessionListByAgent[agentId] = {
        query: normalizedQuery,
        loading: true,
        loadingMore: false,
        hasMore: false,
        nextOffset: null,
        error: "",
      };
    }));

    try {
      const response = await window.gateway.listSessions({
        agentId,
        limit: 30,
        offset: 0,
        query: normalizedQuery,
      });
      if (response.error) throw new Error(response.error.message);
      const activeSessionId = get().activeSessionByAgent[agentId] || "";
      const sessions = pinActiveSession(
        sessionEntries(response.result),
        activeSessionId,
        get().messagesByAgent[agentId] || [],
      );
      set(produce((s: CoreState) => {
        if (s.sessionListByAgent[agentId]?.query !== normalizedQuery) return;
        s.sessionsByAgent[agentId] = sessions;
        s.sessionListByAgent[agentId] = {
          query: normalizedQuery,
          loading: false,
          loadingMore: false,
          hasMore: response.result?.has_more === true,
          nextOffset: typeof response.result?.next_offset === "number" ? response.result.next_offset : null,
          error: "",
        };
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        const list = s.sessionListByAgent[agentId];
        if (list?.query === normalizedQuery) {
          list.loading = false;
          list.error = String(error);
        }
      }));
    }
  },

  loadMoreSessions: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const list = get().sessionListByAgent[agentId];
    if (!list?.hasMore || list.loading || list.loadingMore || list.nextOffset === null) return;
    const query = list.query;
    const offset = list.nextOffset;
    set(produce((s: CoreState) => {
      const current = s.sessionListByAgent[agentId];
      if (current) {
        current.loadingMore = true;
        current.error = "";
      }
    }));

    try {
      const response = await window.gateway.listSessions({ agentId, limit: 30, offset, query });
      if (response.error) throw new Error(response.error.message);
      const nextSessions = sessionEntries(response.result);
      set(produce((s: CoreState) => {
        const current = s.sessionListByAgent[agentId];
        if (!current || current.query !== query || current.nextOffset !== offset) return;
        const existingIds = new Set((s.sessionsByAgent[agentId] || []).map((session) => session.id));
        s.sessionsByAgent[agentId].push(...nextSessions.filter((session) => !existingIds.has(session.id)));
        current.loadingMore = false;
        current.hasMore = response.result?.has_more === true;
        current.nextOffset = typeof response.result?.next_offset === "number" ? response.result.next_offset : null;
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        const current = s.sessionListByAgent[agentId];
        if (current?.query === query) {
          current.loadingMore = false;
          current.error = String(error);
        }
      }));
    }
  },

  loadOlderMessages: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId];
    if (!sessionId) return;
    const pagination = get().historyPaginationByAgent[agentId]?.[sessionId];
    if (!pagination?.hasMore || pagination.loading || !pagination.beforeId) return;

    set(produce((s: CoreState) => {
      const page = s.historyPaginationByAgent[agentId]?.[sessionId];
      if (page) {
        page.loading = true;
        page.error = "";
      }
    }));

    try {
      const response = await window.gateway.getHistory({
        agentId,
        sessionId,
        limit: 50,
        beforeId: pagination.beforeId,
      });
      if (response.error) throw new Error(response.error.message);
      const olderMessages = historyMessages(response.result, sessionId);
      const nextPage = historyPagination(response.result);

      set(produce((s: CoreState) => {
        if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
        s.historyPaginationByAgent[agentId][sessionId] = nextPage;
        if (s.activeSessionByAgent[agentId] !== sessionId) return;
        const currentMessages = s.messagesByAgent[agentId] || [];
        const currentIds = new Set(currentMessages.map((message) => message.id));
        const uniqueOlder = olderMessages.filter((message) => !currentIds.has(message.id));
        s.messagesByAgent[agentId] = [...uniqueOlder, ...currentMessages];
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        const page = s.historyPaginationByAgent[agentId]?.[sessionId];
        if (page) {
          page.loading = false;
          page.error = String(error);
        }
      }));
    }
  },

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
  window.notifications.onSelect((target) => {
    const state = useCoreStore.getState();
    if (!state.agents.some((agent) => agent.id === target.agentId)) return;

    state.setPage("chat");
    state.setActiveNav("assistant");
    state.setTerminalOpen(false);
    void state.switchAgent(target.agentId).then(async () => {
      const nextState = useCoreStore.getState();
      if (target.sessionId && nextState.activeSessionByAgent[target.agentId] !== target.sessionId) {
        await nextState.switchSession(target.sessionId);
      }
    });
  });

  window.gateway.onEvent((raw: { event: string; data: unknown; agentId: string }) => {
    const { event, data: rawData, agentId } = raw;
    const d = (rawData || {}) as Record<string, unknown>;
    const text = (d.text || "") as string;
    const store = useCoreStore.getState;
    const setState = useCoreStore.setState;

    if (!agentId) return;

    const eventSessionId = typeof d.session_id === "string" && d.session_id
      ? d.session_id
      : store().activeSessionByAgent[agentId] || "";
    const eventTurnId = typeof d.turn_id === "string" ? d.turn_id : "";
    const activeStreamKey = streamingKey(agentId, eventSessionId, eventTurnId);
    if (!_streamingByTurn[activeStreamKey]) {
      _streamingByTurn[activeStreamKey] = { ref: "", id: null };
    }
    const stream = _streamingByTurn[activeStreamKey];

    if (event === "reconnecting") {
      setState(produce((s: CoreState) => {
        const previous = s.connectionByAgent[agentId];
        s.connectionByAgent[agentId] = {
          status: "connecting",
          agentName: previous?.agentName || "",
          error: "",
        };
      }));
      return;
    }

    if (event === "reconnected") {
      const sessionId = typeof d.session_id === "string" ? d.session_id : "";
      const resume = d.resume && typeof d.resume === "object"
        ? d.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      clearAgentStreams(agentId);
      setState(produce((s: CoreState) => {
        const previous = s.connectionByAgent[agentId];
        s.connectionByAgent[agentId] = {
          status: "connected",
          agentName: (d.agent_name as string) || previous?.agentName || "",
          error: "",
        };
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          s.messagesByAgent[agentId] = messages;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = historyPagination(resume);
          if (!s.sessionsByAgent[agentId]) s.sessionsByAgent[agentId] = [];
          if (!s.sessionsByAgent[agentId].some((session) => session.id === sessionId)) {
            const now = Date.now();
            s.sessionsByAgent[agentId].unshift({
              id: sessionId,
              name: defaultSessionName([]),
              createdAt: now,
              updatedAt: now,
              messageCount: 0,
            });
          }
        }
        s.sendingByAgent[agentId] = resume?.state === "running" || resume?.state === "waiting_user";
      }));
      restoreStreamFromResume(agentId, sessionId, resume);
      return;
    }

    if (event === "reconnect.error") {
      setState(produce((s: CoreState) => {
        const previous = s.connectionByAgent[agentId];
        s.connectionByAgent[agentId] = {
          status: "error",
          agentName: previous?.agentName || "",
          error: (d.message as string) || "Reconnect authentication failed",
        };
      }));
      return;
    }

    if (event === "message.start") {
      stream.ref = "";
      stream.id = null;
      setState(produce((s: CoreState) => { s.sendingByAgent[agentId] = true; }));
      return;
    }

    if (event === "interaction.requested") {
      const payload = d;
      const requestId = typeof payload.id === "string" ? payload.id : "";
      const question = typeof payload.question === "string" ? payload.question : "";
      if (!requestId || !question) return;
      const choices = Array.isArray(payload.choices)
        ? payload.choices.filter((choice): choice is string => typeof choice === "string")
        : [];
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        if (s.messagesByAgent[agentId].some((message) => message.interaction?.id === requestId)) return;

        // A tool call can happen in the middle of one ReAct stream. Close
        // any text emitted before the question so content produced after
        // the answer starts a new message below the interaction card.
        if (activeStreamId) {
          const activeMessage = s.messagesByAgent[agentId]
            .find((message) => message.id === activeStreamId);
          if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
          }
        }
        s.messagesByAgent[agentId].push({
          id: requestId,
          role: "agent",
          content: "",
          streaming: false,
          interaction: {
            id: requestId,
            question,
              choices,
              sessionId: typeof payload.session_id === "string" ? payload.session_id : "",
              turnId: typeof payload.turn_id === "string" ? payload.turn_id : "",
              status: "pending",
            response: "",
          },
        });
        inserted = true;
      }));
      if (inserted && activeStreamId && stream.id === activeStreamId) {
        stream.id = null;
        stream.ref = "";
      }
      return;
    }

    if (event === "interaction.updated") {
      const payload = d;
      const requestId = typeof payload.id === "string" ? payload.id : "";
      const status = typeof payload.status === "string" ? payload.status : "";
      const response = typeof payload.response === "string" ? payload.response : "";
      if (!requestId) return;
      setState(produce((s: CoreState) => {
        const message = (s.messagesByAgent[agentId] || [])
          .find((entry) => entry.interaction?.id === requestId);
        if (!message?.interaction) return;
        if (["answered", "cancelled", "expired"].includes(status)) {
          message.interaction.status = status as "answered" | "cancelled" | "expired";
        }
        message.interaction.response = response;
        message.interaction.error = "";
      }));
      return;
    }

    if (event === "tool.start") {
      const toolCallId = typeof d.tool_call_id === "string" ? d.tool_call_id : "";
      const name = typeof d.name === "string" ? d.name : "";
      if (!toolCallId || !name || name === "clarify") return;
      const args = d.arguments && typeof d.arguments === "object" && !Array.isArray(d.arguments)
        ? d.arguments as Record<string, unknown>
        : {};
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        if (s.messagesByAgent[agentId].some((message) => message.tool?.id === toolCallId)) return;
        if (activeStreamId) {
          const activeMessage = s.messagesByAgent[agentId]
            .find((message) => message.id === activeStreamId);
          if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
          }
        }
        s.messagesByAgent[agentId].push({
          id: `tool-${toolCallId}`,
          role: "agent",
          content: "",
          streaming: false,
          tool: {
            id: toolCallId,
            name,
            arguments: args,
            status: "running",
            summary: "",
            truncated: false,
            error: "",
          },
        });
        inserted = true;
      }));
      if (inserted && activeStreamId && stream.id === activeStreamId) {
        stream.id = null;
        stream.ref = "";
      }
      return;
    }

    if (event === "tool.complete") {
      const toolCallId = typeof d.tool_call_id === "string" ? d.tool_call_id : "";
      const name = typeof d.name === "string" ? d.name : "";
      if (!toolCallId || !name || name === "clarify") return;
      const summary = typeof d.summary === "string" ? d.summary : "";
      const error = d.error && typeof d.error === "object" && !Array.isArray(d.error)
        ? String((d.error as Record<string, unknown>).message || "")
        : "";
      setState(produce((s: CoreState) => {
        if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
        let message = s.messagesByAgent[agentId]
          .find((entry) => entry.tool?.id === toolCallId);
        if (!message) {
          message = {
            id: `tool-${toolCallId}`,
            role: "agent",
            content: "",
            streaming: false,
            tool: {
              id: toolCallId,
              name,
              arguments: {},
              status: "running",
              summary: "",
              truncated: false,
              error: "",
            },
          };
          s.messagesByAgent[agentId].push(message);
        }
        if (!message.tool) return;
        message.tool.status = error ? "error" : "complete";
        message.tool.summary = summary;
        message.tool.truncated = d.truncated === true;
        message.tool.error = error;
      }));
      return;
    }

    // Internal cognition metadata has its own event and must never finalize
    // the visible assistant message stream.
    if (event === "internal.display" || event === "pong") return;

    if (!store().messagesByAgent[agentId]) {
      setState(produce((s: CoreState) => { s.messagesByAgent[agentId] = []; }));
    }

    if (event === "message.delta") {
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
    } else if (event === "message.complete") {
      const status = typeof d.status === "string" ? d.status : "complete";
      const error = d.error && typeof d.error === "object"
        ? d.error as Record<string, unknown>
        : null;
      const terminalText = text || (status === "error"
        ? `Error: ${String(error?.message || "Unknown error")}`
        : "");
      let completedText = "";
      if (stream.id) {
        const finalText = stream.ref || terminalText;
        const streamingMessageExists = store().messagesByAgent[agentId]
          .some((message) => message.id === stream.id);
        if (streamingMessageExists) completedText = finalText;
        setState(produce((s: CoreState) => {
          const idx = s.messagesByAgent[agentId].findIndex(m => m.id === stream.id);
          if (idx !== -1) {
            s.messagesByAgent[agentId][idx].content = finalText;
            s.messagesByAgent[agentId][idx].streaming = false;
            touchSession(s, agentId, eventSessionId, 1);
          }
        }));
        stream.id = null;
        stream.ref = "";
      } else if (terminalText) {
        // Skip a duplicate final message if the local stream already finalized it.
        const msgs = store().messagesByAgent[agentId];
        const lastMsg = msgs && msgs.length > 0 ? msgs[msgs.length - 1] : null;
        const isDuplicate = lastMsg && lastMsg.role === "agent" && lastMsg.content === terminalText;
        if (!isDuplicate) {
          completedText = terminalText;
          setState(produce((s: CoreState) => {
            s.messagesByAgent[agentId].push({
              id: "msg-" + Date.now(), role: "agent", content: terminalText, streaming: false,
            });
            touchSession(s, agentId, eventSessionId, 1);
          }));
        }
      }
      delete _streamingByTurn[activeStreamKey];
      setState(produce((s: CoreState) => { s.sendingByAgent[agentId] = false; }));
      if (completedText && agentId !== store().activeAgentId) {
        // Increment unread for background agent
        const current = store().unreadByAgent[agentId] || 0;
        setState(produce((s: CoreState) => { s.unreadByAgent[agentId] = current + 1; }));
      }
      if (completedText) {
        const state = store();
        const agent = state.agents.find((entry) => entry.id === agentId);
        const agentName = state.connectionByAgent[agentId]?.agentName || agent?.name || "Agent";
        const summary = completedText.replace(/\s+/g, " ").trim();
        void window.notifications.show({
          title: agentName,
          body: summary,
          agentId,
          sessionId: eventSessionId,
        }).catch(() => {});
      }
    } else if (event === "error") {
      const err = (d.text || "Unknown error") as string;
      setState(produce((s: CoreState) => {
        s.messagesByAgent[agentId].push({
          id: "err-" + Date.now(), role: "agent", content: `Error: ${err}`, streaming: false,
        });
      }));
      stream.id = null;
      stream.ref = "";
      setState(produce((s: CoreState) => { s.sendingByAgent[agentId] = false; }));
    }
  });
}
