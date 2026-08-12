import { create } from "zustand";
import { produce } from "immer";
import i18n from "../i18n";
import type { AgentCreationResult, AgentEntry, AgentLifecycleAction, ChatArtifactReference, ChatAttachment, ChatInvocationSelection, LocalAgentInfo, SessionEntry } from "../types";
import { playMessageSound } from "../message-sound";
import { executeEmbodimentCommand } from "../embodiment/command-registry";

// ── Persistence (manual, avoid zustand/persist rehydration during render) ──

const STORAGE_KEY = "xiaomei-brain-agents";
const STORAGE_VERSION = 4;
let lastPersistedSnapshot = "";

interface PersistedState {
  version?: number;
  agents?: AgentEntry[];
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
        activeAgentId: state.activeAgentId,
        activeSessionByAgent: state.activeSessionByAgent ?? {},
      };
    }
  } catch { /* corrupted data */ }
  return {};
}

function savePersisted(state: CoreState) {
  try {
    const snapshot = JSON.stringify({
      version: STORAGE_VERSION,
      agents: state.agents,
      activeAgentId: state.activeAgentId,
      activeSessionByAgent: state.activeSessionByAgent,
    });
    if (snapshot === lastPersistedSnapshot) return;
    lastPersistedSnapshot = snapshot;
    localStorage.setItem(STORAGE_KEY, snapshot);
  } catch { /* quota exceeded */ }
}

// ── Module-level streaming state, isolated by Agent + session + turn ──
interface StreamingState { ref: string; id: string | null }
const _streamingByTurn: Record<string, StreamingState> = {};
const _streamRenderTimers: Record<string, number> = {};
const _sessionSwitchRequestByAgent: Record<string, number> = {};
const STREAM_RENDER_INTERVAL_MS = 32;

function streamingKey(agentId: string, sessionId: string, turnId: string): string {
  return `${agentId}\u0000${sessionId || "legacy"}\u0000${turnId || "legacy"}`;
}

function pendingResponseId(turnId: string): string {
  return `agent-response-${turnId || "pending"}`;
}

function pendingRequestResponseId(clientRequestId: string): string {
  return `agent-response-request-${clientRequestId}`;
}

function responsePhaseForStream(content: string): DisplayMessage["responsePhase"] {
  const lastAnsiStart = content.lastIndexOf("\u001b[2m");
  const lastAnsiEnd = content.lastIndexOf("\u001b[0m");
  const lastPlainStart = content.lastIndexOf("[2m");
  const lastPlainEnd = content.lastIndexOf("[0m");
  return Math.max(lastAnsiStart, lastPlainStart) > Math.max(lastAnsiEnd, lastPlainEnd)
    ? "thinking"
    : undefined;
}

function attachmentDraftKey(agentId: string, sessionId: string | null | undefined): string {
  return `${agentId}\u0000${sessionId || "new"}`;
}

function conversationStateKey(agentId: string, sessionId: string | null | undefined): string {
  return `${agentId}\u0000${sessionId || "new"}`;
}

function messagesForSession(
  state: CoreState,
  agentId: string,
  sessionId: string,
): DisplayMessage[] {
  touchConversationState(state, agentId, sessionId);
  if (state.activeSessionByAgent[agentId] === sessionId) {
    if (!state.messagesByAgent[agentId]) state.messagesByAgent[agentId] = [];
    return state.messagesByAgent[agentId];
  }
  const key = conversationStateKey(agentId, sessionId);
  if (!state.messagesByConversation[key]) state.messagesByConversation[key] = [];
  return state.messagesByConversation[key];
}

function readMessagesForSession(
  state: CoreState,
  agentId: string,
  sessionId: string,
): DisplayMessage[] {
  return state.activeSessionByAgent[agentId] === sessionId
    ? state.messagesByAgent[agentId] || []
    : state.messagesByConversation[conversationStateKey(agentId, sessionId)] || [];
}

function setSessionSending(
  state: CoreState,
  agentId: string,
  sessionId: string,
  sending: boolean,
): void {
  touchConversationState(state, agentId, sessionId);
  state.sendingByConversation[conversationStateKey(agentId, sessionId)] = sending;
  const prefix = `${agentId}\u0000`;
  state.sendingByAgent[agentId] = Object.entries(state.sendingByConversation)
    .some(([key, value]) => key.startsWith(prefix) && value);
}

function touchConversationState(state: CoreState, agentId: string, sessionId: string): void {
  const key = conversationStateKey(agentId, sessionId);
  state.recentConversationKeys = state.recentConversationKeys.filter((value) => value !== key);
  state.recentConversationKeys.push(key);
  let protectedAttempts = 0;
  while (state.recentConversationKeys.length > 30
    && protectedAttempts < state.recentConversationKeys.length) {
    const oldest = state.recentConversationKeys[0];
    const separator = oldest.indexOf("\u0000");
    const oldestAgentId = separator >= 0 ? oldest.slice(0, separator) : "";
    const oldestSessionId = separator >= 0 ? oldest.slice(separator + 1) : "";
    const isActive = state.activeSessionByAgent[oldestAgentId] === oldestSessionId;
    if (isActive || state.sendingByConversation[oldest]) {
      state.recentConversationKeys.push(state.recentConversationKeys.shift()!);
      protectedAttempts += 1;
      continue;
    }
    state.recentConversationKeys.shift();
    delete state.messagesByConversation[oldest];
    delete state.draftByConversation[oldest];
    delete state.unreadByConversation[oldest];
    delete state.attachmentsByConversation[oldest];
    delete state.artifactReferencesByConversation[oldest];
    delete state.attachmentErrorByConversation[oldest];
    delete state.invocationByConversation[oldest];
    delete state.sendingByConversation[oldest];
    protectedAttempts = 0;
  }
}

function displayAttachments(values: unknown): DisplayAttachment[] {
  if (!Array.isArray(values)) return [];
  return values.flatMap((value): DisplayAttachment[] => {
    if (!value || typeof value !== "object") return [];
    const item = value as Record<string, unknown>;
    if (typeof item.id !== "string" || typeof item.name !== "string") return [];
    const mimeType = typeof item.mime_type === "string"
      ? item.mime_type
      : typeof item.mimeType === "string" ? item.mimeType : "application/octet-stream";
    const kind = item.kind === "image"
      ? "image"
      : item.kind === "document"
        ? "document"
        : item.kind === "audio"
          ? "audio"
          : item.kind === "video"
            ? "video"
            : "text";
    const rawAnnotation = item.annotation;
    const annotation = rawAnnotation && typeof rawAnnotation === "object" && !Array.isArray(rawAnnotation)
      ? rawAnnotation as Record<string, unknown>
      : null;
    const selectedText = annotation
      ? (typeof annotation.selected_text === "string"
        ? annotation.selected_text
        : typeof annotation.selectedText === "string" ? annotation.selectedText : "")
      : "";
    return [{
      id: item.id,
      name: item.name,
      mimeType,
      size: typeof item.size === "number" ? item.size : 0,
      kind,
      annotation: selectedText ? {
        selectedText,
        page: typeof annotation?.page === "number" ? annotation.page : undefined,
        sheet: typeof annotation?.sheet === "string" ? annotation.sheet : undefined,
        range: typeof annotation?.range === "string" ? annotation.range : undefined,
      } : undefined,
    }];
  });
}

function publicResponseText(value: string): string {
  return value
    .replace(/\u001b\[2m[\s\S]*?\u001b\[0m/g, "")
    .replace(/\u001b\[[0-9;]*m/g, "")
    .trim();
}

function displayInvocation(value: unknown): ChatInvocationSelection | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const item = value as Record<string, unknown>;
  const kind = item.kind;
  const id = typeof item.id === "string" ? item.id.trim() : "";
  if (!id || !["capability", "skill", "execution"].includes(String(kind))) return undefined;
  return {
    kind: kind as ChatInvocationSelection["kind"],
    id,
    name: typeof item.name === "string" && item.name.trim() ? item.name : id,
    processTemplateId: typeof item.process_template_id === "string" && item.process_template_id
      ? item.process_template_id
      : typeof item.processTemplateId === "string" ? item.processTemplateId : undefined,
    processName: typeof item.process_name === "string" && item.process_name
      ? item.process_name
      : typeof item.processName === "string" ? item.processName : undefined,
  };
}

function displayArtifact(value: unknown): DisplayArtifact | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== "string" || typeof item.name !== "string") return undefined;
  const allowedKinds = ["image", "audio", "video", "text", "document", "file", "visualization"];
  return {
    id: item.id,
    name: item.name,
    mimeType: typeof item.mime_type === "string" ? item.mime_type : "application/octet-stream",
    size: typeof item.size === "number" ? item.size : 0,
    kind: allowedKinds.includes(String(item.kind)) ? item.kind as DisplayArtifact["kind"] : "file",
    description: typeof item.description === "string" ? item.description : "",
    toolCallId: typeof item.tool_call_id === "string" ? item.tool_call_id : "",
    turnId: typeof item.turn_id === "string" ? item.turn_id : "",
  };
}

export interface ArtifactSnapshot extends DisplayArtifact {
  sessionId: string;
  createdAt: number;
  updatedAt: number;
}

function artifactSnapshot(value: unknown): ArtifactSnapshot | null {
  const artifact = displayArtifact(value);
  if (!artifact || !value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  return {
    ...artifact,
    sessionId: typeof item.session_id === "string" ? item.session_id : "",
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    updatedAt: typeof item.updated_at === "number"
      ? item.updated_at
      : typeof item.created_at === "number" ? item.created_at : 0,
  };
}

function upsertArtifact(state: CoreState, agentId: string, artifact: ArtifactSnapshot): void {
  if (!state.artifactsByAgent[agentId]) state.artifactsByAgent[agentId] = [];
  const index = state.artifactsByAgent[agentId].findIndex((item) => (
    item.id === artifact.id && item.sessionId === artifact.sessionId
  ));
  if (index >= 0) state.artifactsByAgent[agentId][index] = artifact;
  else state.artifactsByAgent[agentId].push(artifact);
  state.artifactsByAgent[agentId].sort((left, right) => right.updatedAt - left.updatedAt);
}

function clearAgentStreams(agentId: string): void {
  const prefix = `${agentId}\u0000`;
  for (const key of Object.keys(_streamingByTurn)) {
    if (key.startsWith(prefix)) delete _streamingByTurn[key];
  }
  for (const key of Object.keys(_streamRenderTimers)) {
    if (!key.startsWith(prefix)) continue;
    window.clearTimeout(_streamRenderTimers[key]);
    delete _streamRenderTimers[key];
  }
}

function clearSessionStreams(agentId: string, sessionId: string): void {
  const prefix = `${agentId}\u0000${sessionId || "legacy"}\u0000`;
  for (const key of Object.keys(_streamingByTurn)) {
    if (key.startsWith(prefix)) delete _streamingByTurn[key];
  }
  for (const key of Object.keys(_streamRenderTimers)) {
    if (!key.startsWith(prefix)) continue;
    window.clearTimeout(_streamRenderTimers[key]);
    delete _streamRenderTimers[key];
  }
}

function toolResultFailed(result: string): boolean {
  return result.startsWith("Error:")
    || result.startsWith("Blocked")
    || result.includes("timed out")
    || result.toLowerCase().includes("failed");
}

function actionRequest(
  payload: Record<string, unknown>,
  sessionId: string,
  turnId: string,
  status: ActionRequest["status"],
): ActionRequest {
  return {
    id: typeof payload.id === "string" ? payload.id : "",
    toolCallId: typeof payload.tool_call_id === "string" ? payload.tool_call_id : "",
    toolName: typeof payload.tool_name === "string" ? payload.tool_name : "",
    arguments: payload.arguments && typeof payload.arguments === "object" && !Array.isArray(payload.arguments)
      ? payload.arguments as Record<string, unknown>
      : {},
    summary: typeof payload.summary === "string" ? payload.summary : "",
    reason: typeof payload.reason === "string" ? payload.reason : "",
    riskLevel: typeof payload.risk_level === "string" ? payload.risk_level : "medium",
    sessionId: typeof payload.session_id === "string" ? payload.session_id : sessionId,
    turnId: typeof payload.turn_id === "string" ? payload.turn_id : turnId,
    status,
    decision: typeof payload.decision === "string" ? payload.decision : "",
    result: typeof payload.result === "string" ? payload.result : "",
    error: typeof payload.error === "string" ? payload.error : "",
  };
}

function capabilitySetupRequest(
  value: unknown,
  fallbackSessionId: string,
): CapabilitySetupRequest | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const payload = value as Record<string, unknown>;
  const rawAction = payload.action;
  if (!rawAction || typeof rawAction !== "object" || Array.isArray(rawAction)) return null;
  const action = rawAction as Record<string, unknown>;
  const id = typeof payload.id === "string" ? payload.id : "";
  const capabilityId = typeof payload.capability_id === "string" ? payload.capability_id : "";
  const section = typeof action.section === "string" ? action.section : "";
  if (!id || !capabilityId || !section || action.type !== "open_settings") return null;
  return {
    id,
    capabilityId,
    capabilityName: typeof payload.capability_name === "string"
      ? payload.capability_name
      : capabilityId,
    status: typeof payload.capability_status === "string" ? payload.capability_status : "needs_setup",
    summary: typeof payload.summary === "string" ? payload.summary : i18n.t("capabilityUi.continueTask"),
    sessionId: typeof payload.session_id === "string" ? payload.session_id : fallbackSessionId,
    turnId: typeof payload.turn_id === "string" ? payload.turn_id : "",
    sourceMessageId: typeof payload.source_message_id === "number"
      ? payload.source_message_id
      : undefined,
    resumeStatus: ["pending", "resumed", "unavailable"].includes(String(payload.resume_status))
      ? payload.resume_status as CapabilitySetupRequest["resumeStatus"]
      : "unavailable",
    action: {
      type: "open_settings",
      section,
      target: typeof action.target === "string" ? action.target : "",
      label: typeof action.label === "string" ? action.label : i18n.t("capabilityUi.goToSettings"),
    },
  };
}

function memoryReferences(value: unknown): MemoryReference[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw): MemoryReference[] => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as Record<string, unknown>;
    if (typeof item.summary !== "string" || !item.summary.trim()) return [];
    return [{
      id: typeof item.id === "string" ? item.id : String(item.id || ""),
      summary: item.summary,
      source: typeof item.source === "string" ? item.source : "",
      memoryType: typeof item.memory_type === "string" ? item.memory_type : "",
      tags: Array.isArray(item.tags)
        ? item.tags.filter((tag): tag is string => typeof tag === "string").slice(0, 5)
        : [],
      createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    }];
  }).slice(0, 8);
}

function personMemorySnapshot(value: unknown): PersonMemorySnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== "string" || typeof item.summary !== "string" || !item.summary.trim()) return null;
  return {
    id: item.id,
    summary: item.summary,
    source: typeof item.source === "string" ? item.source : "",
    memoryType: typeof item.memory_type === "string" ? item.memory_type : "",
    tags: Array.isArray(item.tags)
      ? item.tags.filter((tag): tag is string => typeof tag === "string").slice(0, 8)
      : [],
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    lastAccessed: typeof item.last_accessed === "number" ? item.last_accessed : 0,
    memoryLayer: item.memory_layer === "short_term" ? "short_term" : "long_term",
    expiresAt: typeof item.expires_at === "number" ? item.expires_at : 0,
    reinforcementCount: typeof item.reinforcement_count === "number"
      ? item.reinforcement_count
      : 1,
  };
}

function interactionDisplayText(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const item = value as Record<string, unknown>;
    for (const key of ["label", "title", "name", "value", "text", "description"]) {
      if (typeof item[key] === "string" && item[key].trim()) return item[key].trim();
    }
    return "";
  }
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text) return "";
  try {
    const parsed = JSON.parse(text) as unknown;
    const normalized = interactionDisplayText(parsed);
    if (normalized) return normalized;
  } catch {
    // Older malformed choices were persisted using Python's dict repr.
  }
  const legacy = text.match(/^\{\s*['"](?:label|title|name|value|text|description)['"]\s*:\s*(['"])([\s\S]*)\1\s*\}$/);
  return legacy ? legacy[2].trim() : text;
}

function interactionChoices(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(interactionDisplayText).filter(Boolean);
}

function historyMessages(
  result: Record<string, unknown> | undefined,
  sessionId: string,
  activeInteractionIds: Set<string> = new Set(),
  activeActionIds: Set<string> = new Set(),
): DisplayMessage[] {
  const rows = Array.isArray(result?.messages) ? result.messages : [];
  return rows.flatMap((value, index): DisplayMessage[] => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    if (row.role === "interaction" && row.action && typeof row.action === "object") {
      const action = row.action as Record<string, unknown>;
      const id = typeof action.id === "string" ? action.id : "";
      const summary = typeof action.summary === "string" ? action.summary : "";
      if (!id || !summary) return [];
      const rawStatus = typeof action.status === "string" ? action.status : "expired";
      let status = ["pending", "completed", "failed", "rejected", "cancelled", "expired"].includes(rawStatus)
        ? rawStatus as ActionRequest["status"]
        : "expired";
      if (status === "pending" && !activeActionIds.has(id)) status = "expired";
      return [{
        id,
        role: "agent",
        content: "",
        streaming: false,
        action: actionRequest(action, sessionId, typeof action.turn_id === "string" ? action.turn_id : "", status),
      } satisfies DisplayMessage];
    }
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
          choices: interactionChoices(interaction.choices),
          sessionId: typeof interaction.session_id === "string" ? interaction.session_id : sessionId,
          turnId: typeof interaction.turn_id === "string" ? interaction.turn_id : "",
          status,
          response: interactionDisplayText(interaction.response),
        },
      } satisfies DisplayMessage];
    }
    if (row.role === "interaction" && row.capability_setup && typeof row.capability_setup === "object") {
      const setup = capabilitySetupRequest(row.capability_setup, sessionId);
      if (!setup) return [];
      return [{
        id: setup.id,
        role: "agent",
        content: "",
        streaming: false,
        createdAt: typeof row.created_at === "number" ? row.created_at * 1000 : undefined,
        turnId: setup.turnId || undefined,
        capabilitySetup: setup,
      } satisfies DisplayMessage];
    }
    if (row.role === "artifact") {
      const artifact = displayArtifact(row.artifact);
      if (!artifact) return [];
      return [{
        id: `artifact-${artifact.id}`,
        role: "agent",
        content: "",
        streaming: false,
        artifact,
        turnId: artifact.turnId || undefined,
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
        turnId: typeof row.turn_id === "string" ? row.turn_id : undefined,
        tool: {
          id: toolCallId,
          name,
          arguments: {},
          status: failed ? "error" : "complete",
          summary: summary.slice(0, 800),
          truncated: summary.length > 800,
          error: failed ? summary.slice(0, 800) : "",
          durationMs: typeof row.duration_ms === "number" ? Math.max(0, row.duration_ms) : undefined,
        },
      } satisfies DisplayMessage];
    }
    const role = row.role === "user" ? "user" : row.role === "assistant" ? "agent" : null;
    if (!role || typeof row.content !== "string") return [];
    const reasoningContent = role === "agent" && typeof row.reasoning_content === "string"
      ? row.reasoning_content
      : "";
    if (role === "agent" && !row.content.trim() && !reasoningContent.trim()) return [];
    const rawDeliveryStatus = typeof row.status === "string" ? row.status : "";
    const deliveryStatus = ["queued", "processing", "completed", "failed", "interrupted"].includes(rawDeliveryStatus)
      ? rawDeliveryStatus as DisplayMessage["deliveryStatus"]
      : undefined;
    const deliveryError = row.error && typeof row.error === "object" && !Array.isArray(row.error)
      ? String((row.error as Record<string, unknown>).message || "")
      : "";
    const deliveryErrorCode = row.error && typeof row.error === "object" && !Array.isArray(row.error)
      ? String((row.error as Record<string, unknown>).code || "")
      : "";
    const displayMessage = {
      id: typeof row.id === "number"
        ? `history-${sessionId}-${row.id}`
        : `history-${sessionId}-${String(row.created_at || index)}-${index}`,
      role,
      content: row.content,
      reasoningContent: reasoningContent || undefined,
      invocation: role === "user" ? displayInvocation(row.invocation) : undefined,
      streaming: false,
      createdAt: typeof row.created_at === "number" ? row.created_at * 1000 : undefined,
      attachments: displayAttachments(row.attachments),
      memoryReferences: role === "agent" ? memoryReferences(row.memory_references) : undefined,
      turnId: typeof row.turn_id === "string" ? row.turn_id : undefined,
      steeredIntoTurnId: typeof row.steered_into_turn_id === "string"
        ? row.steered_into_turn_id
        : undefined,
      deliveryStatus: role === "user" ? deliveryStatus : undefined,
      deliveryErrorCode: role === "user" ? deliveryErrorCode : undefined,
      deliveryError: role === "user" ? deliveryError : undefined,
      sourceMessageId: role === "user" && typeof row.id === "number" ? row.id : undefined,
      retryOf: role === "user" && typeof row.retry_of === "number" ? row.retry_of : undefined,
    } satisfies DisplayMessage;
    if (
      role === "user"
      && deliveryStatus === "failed"
      && deliveryErrorCode.startsWith("MODEL_")
    ) {
      return [
        displayMessage,
        {
          id: `history-service-error-${sessionId}-${String(row.id || index)}`,
          role: "agent",
          content: deliveryError,
          streaming: false,
          createdAt: typeof row.created_at === "number" ? row.created_at * 1000 : undefined,
          turnId: typeof row.turn_id === "string" ? row.turn_id : undefined,
          serviceError: {
            code: deliveryErrorCode,
            message: deliveryError || i18n.t("home.modelUnavailable"),
            retryMessageId: typeof row.id === "number" ? row.id : undefined,
          },
        } satisfies DisplayMessage,
      ];
    }
    return [displayMessage];
  });
}

function resumeMessages(result: Record<string, unknown> | undefined, sessionId: string): DisplayMessage[] {
  const inflight = result?.inflight && typeof result.inflight === "object"
    ? result.inflight as Record<string, unknown>
    : null;
  const items = inflight && Array.isArray(inflight.items) ? inflight.items : [];
  const activeInteractionIds = new Set<string>();
  const activeToolIds = new Set<string>();
  const activeActionIds = new Set<string>();
  const activeCapabilitySetupIds = new Set<string>();
  for (const value of items) {
    if (!value || typeof value !== "object") continue;
    const item = value as Record<string, unknown>;
    if (item.type === "interaction" && typeof item.id === "string") activeInteractionIds.add(item.id);
    if (item.type === "tool" && typeof item.id === "string") activeToolIds.add(item.id);
    if (item.type === "action" && typeof item.id === "string") activeActionIds.add(item.id);
    if (item.type === "capability_setup" && typeof item.id === "string") activeCapabilitySetupIds.add(item.id);
  }

  const history = historyMessages(result, sessionId, activeInteractionIds, activeActionIds).filter((message) => {
    if (message.interaction && activeInteractionIds.has(message.interaction.id)) return false;
    if (message.tool && activeToolIds.has(message.tool.id)) return false;
    if (message.action && activeActionIds.has(message.action.id)) return false;
    if (message.capabilitySetup && activeCapabilitySetupIds.has(message.capabilitySetup.id)) return false;
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
        turnId,
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
        turnId,
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
          startedAt: typeof item.started_at === "number" ? item.started_at : undefined,
          completedAt: typeof item.completed_at === "number" ? item.completed_at : undefined,
          durationMs: typeof item.duration_ms === "number" ? Math.max(0, item.duration_ms) : undefined,
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
        turnId,
        interaction: {
          id,
          question,
          choices: interactionChoices(item.choices),
          sessionId,
          turnId,
          status,
          response: interactionDisplayText(item.response),
        },
      }];
    }
    if (item.type === "capability_setup") {
      const setup = capabilitySetupRequest(item, sessionId);
      if (!setup) return [];
      return [{
        id: setup.id,
        role: "agent",
        content: "",
        streaming: false,
        turnId,
        capabilitySetup: setup,
      }];
    }
    if (item.type === "action") {
      const id = typeof item.id === "string" ? item.id : "";
      const summary = typeof item.summary === "string" ? item.summary : "";
      if (!id || !summary) return [];
      const rawStatus = typeof item.status === "string" ? item.status : "pending";
      const status = ["pending", "completed", "failed", "rejected", "cancelled", "expired"].includes(rawStatus)
        ? rawStatus as ActionRequest["status"]
        : "pending";
      return [{
        id,
        role: "agent",
        content: "",
        streaming: false,
        turnId,
        action: actionRequest(item, sessionId, turnId, status),
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
      channel: typeof row.channel === "string" ? row.channel : undefined,
    } satisfies SessionEntry];
  });
}

function includeActiveSession(
  sessions: SessionEntry[],
  activeSessionId: string,
  activeMessages: DisplayMessage[],
): SessionEntry[] {
  if (!activeSessionId) return sessions;
  const result = [...sessions];
  const existingIndex = result.findIndex((session) => session.id === activeSessionId);
  if (existingIndex < 0) {
    const now = Date.now();
    result.push({
      id: activeSessionId,
      name: defaultSessionName(activeMessages),
      createdAt: now,
      updatedAt: now,
      messageCount: activeMessages.length,
    });
  }
  return result.sort(
    (left, right) => (right.updatedAt || right.createdAt) - (left.updatedAt || left.createdAt),
  );
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
  state.sessionsByAgent[agentId].sort((left, right) => {
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
  const sessions = includeActiveSession(fetched, activeSessionId, activeMessages);
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
  reasoningContent?: string;
  responsePhase?: "waiting" | "replying" | "thinking";
  invocation?: ChatInvocationSelection;
  streaming: boolean;
  createdAt?: number;
  interaction?: InteractionRequest;
  capabilitySetup?: CapabilitySetupRequest;
  tool?: ToolActivity;
  action?: ActionRequest;
  artifact?: DisplayArtifact;
  attachments?: DisplayAttachment[];
  memoryReferences?: MemoryReference[];
  turnId?: string;
  steeredIntoTurnId?: string;
  deliveryStatus?: "queued" | "processing" | "completed" | "failed" | "interrupted";
  deliveryErrorCode?: string;
  deliveryError?: string;
  serviceError?: {
    code: string;
    message: string;
    retryMessageId?: number;
  };
  sourceMessageId?: number;
  retryOf?: number;
}

export interface MemoryReference {
  id: string;
  summary: string;
  source: string;
  memoryType: string;
  tags: string[];
  createdAt: number;
}

export interface PersonMemorySnapshot extends MemoryReference {
  lastAccessed: number;
  memoryLayer: "short_term" | "long_term";
  expiresAt: number;
  reinforcementCount: number;
}

export interface DisplayAttachment {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  kind: "image" | "audio" | "video" | "text" | "document";
  previewUrl?: string;
  annotation?: {
    selectedText: string;
    page?: number;
    sheet?: string;
    range?: string;
  };
}

export interface DisplayArtifact {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  kind: "image" | "audio" | "video" | "text" | "document" | "file" | "visualization";
  description: string;
  toolCallId: string;
  turnId: string;
}

export interface ToolActivity {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "complete" | "error";
  summary: string;
  truncated: boolean;
  error: string;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
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

export interface CapabilitySetupRequest {
  id: string;
  capabilityId: string;
  capabilityName: string;
  status: string;
  summary: string;
  sessionId: string;
  turnId: string;
  sourceMessageId?: number;
  resumeStatus: "pending" | "resumed" | "unavailable";
  action: {
    type: "open_settings";
    section: string;
    target: string;
    label: string;
  };
}

export interface ActionRequest {
  id: string;
  toolCallId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  summary: string;
  reason: string;
  riskLevel: string;
  sessionId: string;
  turnId: string;
  status: "pending" | "responding" | "completed" | "failed" | "rejected" | "cancelled" | "expired" | "error";
  decision: string;
  result: string;
  error: string;
}

export type AssignmentStatus =
  | "offered" | "clarifying" | "accepted" | "queued" | "in_progress"
  | "waiting_person" | "paused" | "completed" | "declined" | "cancelled" | "failed";

export interface AssignmentSnapshot {
  id: string;
  title: string;
  objective: string;
  status: AssignmentStatus;
  originSessionId: string;
  acceptanceCriteria: string[];
  requestedDueAt: number | null;
  progressSummary: string;
  completedSteps: number | null;
  totalSteps: number | null;
  waitingReason: string;
  terminalReason: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
}

export type ProjectStatus = "active" | "completed" | "discontinued";

export interface ProjectSnapshot {
  id: string;
  name: string;
  summary: string;
  projectType: string;
  status: ProjectStatus;
  workspaceKind: "managed" | "linked" | "virtual";
  progressSummary: string;
  currentStepId: string;
  waitingReason: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
}

export interface ProjectStepSnapshot {
  stepId: string;
  parentStepId: string | null;
  title: string;
  position: number;
  status: "pending" | "running" | "waiting_review" | "completed" | "needs_revision" | "skipped";
  summary: string;
  completedUnits: number | null;
  totalUnits: number | null;
  updatedAt: number;
}

export interface ProjectAssetSnapshot {
  id: string;
  role: "source" | "working" | "cache" | "review" | "deliverable";
  kind: string;
  name: string;
  mimeType: string;
  size: number;
  status: "available" | "superseded" | "removed" | "failed";
  updatedAt: number;
}

export interface ProjectReviewSnapshot {
  assessment: string;
  planChanges: string[];
  deviations: string[];
  nextAction: string;
  createdAt: number;
}

export interface ProjectProcessStageSnapshot {
  id: string;
  title: string;
  position: number;
  required: boolean;
  requirementLabels: string[];
  status: "pending" | "incomplete" | "satisfied";
  summary: string;
  missing: string[];
}

export interface ProjectProcessSnapshot {
  id: string;
  projectId: string;
  name: string;
  ordered: boolean;
  status: "active" | "satisfied" | "abandoned";
  revision: number;
  stages: ProjectProcessStageSnapshot[];
  updatedAt: number;
  satisfiedAt: number | null;
}

export interface ProjectDetailSnapshot {
  project: ProjectSnapshot;
  process: ProjectProcessSnapshot | null;
  steps: ProjectStepSnapshot[];
  assets: ProjectAssetSnapshot[];
  assignments: AssignmentSnapshot[];
  activities: ActivitySnapshot[];
  latestReview: ProjectReviewSnapshot | null;
}

export type ActivityStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type ActivityCategory = "work" | "cognition" | "sleep" | "communication";

export interface ActivityStepSnapshot {
  id: string;
  title: string;
  status: "pending" | "running" | "completed" | "skipped" | "failed";
  summary: string;
}

export interface ActivitySnapshot {
  id: string;
  category: ActivityCategory;
  kind: string;
  title: string;
  status: ActivityStatus;
  sourceType: string;
  sourceId: string;
  personId: string | null;
  originSessionId: string;
  originTurnId: string;
  progressSummary: string;
  currentStep: string;
  completedSteps: number | null;
  totalSteps: number | null;
  steps: ActivityStepSnapshot[];
  pauseReason: string;
  resultSummary: string;
  errorMessage: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
}

export type AgentLivingState =
  | "dormant"
  | "waking"
  | "awake"
  | "idle"
  | "working"
  | "sleeping"
  | "dreaming";

export interface AgentIntentSnapshot {
  type: string;
  summary: string;
  actionable: boolean;
  decidedAt: number;
}

export interface AgentStateMetric {
  key: string;
  label: string;
  value: number;
  description: string;
}

export interface AgentInternalStateSnapshot {
  energy: number;
  energyDescription: string;
  moodSummary: string;
  emotions: AgentStateMetric[];
  somatic: string;
  desires: AgentStateMetric[];
  hormones: AgentStateMetric[];
  contradictions: string[];
  impulse: string;
  behaviorTendencies: string[];
  rawContext: string;
  observedAt: number;
}

export interface AgentRelationshipSnapshot {
  personId: string;
  displayName: string;
  relationType: string;
  status: string;
  depth: number;
  trust: number;
  closeness: number;
  interactionCount: number;
  description: string;
  depthDescription: string;
  trustDescription: string;
  closenessDescription: string;
  lastInteractionAt: number;
  rawContext: string;
}

export interface AgentStateSnapshot {
  living: AgentLivingState;
  livingSince: number;
  focus: string;
  focusSummary: string;
  focusSince: number;
  lastIntent: AgentIntentSnapshot | null;
  internal: AgentInternalStateSnapshot | null;
  relationship?: AgentRelationshipSnapshot | null;
}

function stateMetrics(value: unknown): AgentStateMetric[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw): AgentStateMetric[] => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const item = raw as Record<string, unknown>;
    if (typeof item.key !== "string" || typeof item.label !== "string") return [];
    return [{
      key: item.key,
      label: item.label,
      value: Math.max(0, Math.min(1, typeof item.value === "number" ? item.value : 0)),
      description: typeof item.description === "string" ? item.description : "",
    }];
  });
}

function agentStateSnapshot(value: unknown): AgentStateSnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const states = new Set([
    "dormant", "waking", "awake", "idle", "working", "sleeping", "dreaming",
  ]);
  if (!states.has(String(item.living))) return null;
  const rawIntent = item.last_intent;
  const intent = rawIntent && typeof rawIntent === "object" && !Array.isArray(rawIntent)
    ? rawIntent as Record<string, unknown>
    : null;
  const rawInternal = item.internal;
  const internal = rawInternal && typeof rawInternal === "object" && !Array.isArray(rawInternal)
    ? rawInternal as Record<string, unknown>
    : null;
  const hasRelationship = Object.prototype.hasOwnProperty.call(item, "relationship");
  const rawRelationship = item.relationship;
  const relationship = rawRelationship && typeof rawRelationship === "object" && !Array.isArray(rawRelationship)
    ? rawRelationship as Record<string, unknown>
    : null;
  return {
    living: item.living as AgentLivingState,
    livingSince: typeof item.living_since === "number" ? item.living_since : 0,
    focus: typeof item.focus === "string" ? item.focus : "",
    focusSummary: typeof item.focus_summary === "string" ? item.focus_summary : "",
    focusSince: typeof item.focus_since === "number" ? item.focus_since : 0,
    lastIntent: intent ? {
      type: typeof intent.type === "string" ? intent.type : "",
      summary: typeof intent.summary === "string" ? intent.summary : "",
      actionable: Boolean(intent.actionable),
      decidedAt: typeof intent.decided_at === "number" ? intent.decided_at : 0,
    } : null,
    internal: internal ? {
      energy: Math.max(0, Math.min(1, typeof internal.energy === "number" ? internal.energy : 0)),
      energyDescription: typeof internal.energy_description === "string" ? internal.energy_description : "",
      moodSummary: typeof internal.mood_summary === "string" ? internal.mood_summary : "",
      emotions: stateMetrics(internal.emotions),
      somatic: typeof internal.somatic === "string" ? internal.somatic : "",
      desires: stateMetrics(internal.desires),
      hormones: stateMetrics(internal.hormones),
      contradictions: Array.isArray(internal.contradictions)
        ? internal.contradictions.filter((entry): entry is string => typeof entry === "string")
        : [],
      impulse: typeof internal.impulse === "string" ? internal.impulse : "",
      behaviorTendencies: Array.isArray(internal.behavior_tendencies)
        ? internal.behavior_tendencies.filter((entry): entry is string => typeof entry === "string")
        : [],
      rawContext: typeof internal.raw_context === "string" ? internal.raw_context : "",
      observedAt: typeof internal.observed_at === "number" ? internal.observed_at : 0,
    } : null,
    relationship: hasRelationship
      ? relationship ? {
        personId: typeof relationship.person_id === "string" ? relationship.person_id : "",
        displayName: typeof relationship.display_name === "string" ? relationship.display_name : "",
        relationType: typeof relationship.relation_type === "string" ? relationship.relation_type : i18n.t("rightSidebarUi.relationship"),
        status: typeof relationship.status === "string" ? relationship.status : "",
        depth: Math.max(0, Math.min(1, typeof relationship.depth === "number" ? relationship.depth : 0)),
        trust: Math.max(0, Math.min(1, typeof relationship.trust === "number" ? relationship.trust : 0)),
        closeness: Math.max(0, Math.min(1, typeof relationship.closeness === "number" ? relationship.closeness : 0)),
        interactionCount: typeof relationship.interaction_count === "number" ? relationship.interaction_count : 0,
        description: typeof relationship.description === "string" ? relationship.description : "",
        depthDescription: typeof relationship.depth_description === "string" ? relationship.depth_description : "",
        trustDescription: typeof relationship.trust_description === "string" ? relationship.trust_description : "",
        closenessDescription: typeof relationship.closeness_description === "string" ? relationship.closeness_description : "",
        lastInteractionAt: typeof relationship.last_interaction_at === "number" ? relationship.last_interaction_at : 0,
        rawContext: typeof relationship.raw_context === "string" ? relationship.raw_context : "",
      } : null
      : undefined,
  };
}

function activitySnapshot(value: unknown): ActivitySnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const categories = new Set(["work", "cognition", "sleep", "communication"]);
  const statuses = new Set(["queued", "running", "paused", "completed", "failed", "cancelled"]);
  if (
    typeof item.id !== "string"
    || typeof item.title !== "string"
    || !categories.has(String(item.category))
    || !statuses.has(String(item.status))
  ) return null;
  const steps = Array.isArray(item.steps) ? item.steps.flatMap((raw): ActivityStepSnapshot[] => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
    const step = raw as Record<string, unknown>;
    if (typeof step.id !== "string" || typeof step.title !== "string") return [];
    return [{
      id: step.id,
      title: step.title,
      status: String(step.status || "pending") as ActivityStepSnapshot["status"],
      summary: typeof step.summary === "string" ? step.summary : "",
    }];
  }) : [];
  return {
    id: item.id,
    category: item.category as ActivityCategory,
    kind: typeof item.kind === "string" ? item.kind : "activity",
    title: item.title,
    status: item.status as ActivityStatus,
    sourceType: typeof item.source_type === "string" ? item.source_type : "",
    sourceId: typeof item.source_id === "string" ? item.source_id : "",
    personId: typeof item.person_id === "string" ? item.person_id : null,
    originSessionId: typeof item.origin_session_id === "string" ? item.origin_session_id : "",
    originTurnId: typeof item.origin_turn_id === "string" ? item.origin_turn_id : "",
    progressSummary: typeof item.progress_summary === "string" ? item.progress_summary : "",
    currentStep: typeof item.current_step === "string" ? item.current_step : "",
    completedSteps: typeof item.completed_steps === "number" ? item.completed_steps : null,
    totalSteps: typeof item.total_steps === "number" ? item.total_steps : null,
    steps,
    pauseReason: typeof item.pause_reason === "string" ? item.pause_reason : "",
    resultSummary: typeof item.result_summary === "string" ? item.result_summary : "",
    errorMessage: typeof item.error_message === "string" ? item.error_message : "",
    revision: typeof item.revision === "number" ? item.revision : 0,
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    updatedAt: typeof item.updated_at === "number" ? item.updated_at : 0,
    completedAt: typeof item.completed_at === "number" ? item.completed_at : null,
  };
}

function upsertActivity(state: CoreState, agentId: string, activity: ActivitySnapshot): boolean {
  if (!state.activitiesByAgent[agentId]) state.activitiesByAgent[agentId] = [];
  const existing = state.activitiesByAgent[agentId].findIndex((item) => item.id === activity.id);
  if (existing >= 0 && state.activitiesByAgent[agentId][existing].revision >= activity.revision) return false;
  if (existing >= 0) state.activitiesByAgent[agentId][existing] = activity;
  else state.activitiesByAgent[agentId].push(activity);
  state.activitiesByAgent[agentId].sort((left, right) => right.updatedAt - left.updatedAt);
  return true;
}

function assignmentSnapshot(value: unknown): AssignmentSnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== "string" || typeof item.title !== "string" || typeof item.status !== "string") return null;
  const statuses = new Set<string>([
    "offered", "clarifying", "accepted", "queued", "in_progress", "waiting_person",
    "paused", "completed", "declined", "cancelled", "failed",
  ]);
  if (!statuses.has(item.status)) return null;
  return {
    id: item.id,
    title: item.title,
    objective: typeof item.objective === "string" ? item.objective : "",
    status: item.status as AssignmentStatus,
    originSessionId: typeof item.origin_session_id === "string"
      ? item.origin_session_id
      : typeof item.session_id === "string" ? item.session_id : "",
    acceptanceCriteria: Array.isArray(item.acceptance_criteria)
      ? item.acceptance_criteria.filter((entry): entry is string => typeof entry === "string")
      : [],
    requestedDueAt: typeof item.requested_due_at === "number" ? item.requested_due_at : null,
    progressSummary: typeof item.progress_summary === "string" ? item.progress_summary : "",
    completedSteps: typeof item.completed_steps === "number" ? item.completed_steps : null,
    totalSteps: typeof item.total_steps === "number" ? item.total_steps : null,
    waitingReason: typeof item.waiting_reason === "string" ? item.waiting_reason : "",
    terminalReason: typeof item.terminal_reason === "string" ? item.terminal_reason : "",
    revision: typeof item.revision === "number" ? item.revision : 0,
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    updatedAt: typeof item.updated_at === "number" ? item.updated_at : 0,
    completedAt: typeof item.completed_at === "number" ? item.completed_at : null,
  };
}

function upsertAssignment(state: CoreState, agentId: string, assignment: AssignmentSnapshot): boolean {
  if (!state.assignmentsByAgent[agentId]) state.assignmentsByAgent[agentId] = [];
  const existing = state.assignmentsByAgent[agentId].findIndex((item) => item.id === assignment.id);
  if (existing >= 0 && state.assignmentsByAgent[agentId][existing].revision >= assignment.revision) return false;
  if (existing >= 0) state.assignmentsByAgent[agentId][existing] = assignment;
  else state.assignmentsByAgent[agentId].push(assignment);
  state.assignmentsByAgent[agentId].sort((left, right) => right.updatedAt - left.updatedAt);
  return true;
}

function projectSnapshot(value: unknown): ProjectSnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== "string" || typeof item.name !== "string") return null;
  if (!["active", "completed", "discontinued"].includes(String(item.status))) return null;
  return {
    id: item.id,
    name: item.name,
    summary: typeof item.summary === "string" ? item.summary : "",
    projectType: typeof item.project_type === "string" ? item.project_type : "",
    status: item.status as ProjectStatus,
    workspaceKind: (["managed", "linked", "virtual"].includes(String(item.workspace_kind))
      ? item.workspace_kind : "managed") as ProjectSnapshot["workspaceKind"],
    progressSummary: typeof item.progress_summary === "string" ? item.progress_summary : "",
    currentStepId: typeof item.current_step_id === "string" ? item.current_step_id : "",
    waitingReason: typeof item.waiting_reason === "string" ? item.waiting_reason : "",
    revision: typeof item.revision === "number" ? item.revision : 0,
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    updatedAt: typeof item.updated_at === "number" ? item.updated_at : 0,
    completedAt: typeof item.completed_at === "number" ? item.completed_at : null,
  };
}

function projectProcessSnapshot(value: unknown): ProjectProcessSnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const rawProcess = value as Record<string, unknown>;
  if (typeof rawProcess.id !== "string" || typeof rawProcess.name !== "string"
    || typeof rawProcess.project_id !== "string") return null;
  const stages = Array.isArray(rawProcess.stages) ? rawProcess.stages.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const stage = value as Record<string, unknown>;
    if (typeof stage.id !== "string" || typeof stage.title !== "string") return [];
    const submission = stage.submission && typeof stage.submission === "object"
      && !Array.isArray(stage.submission)
      ? stage.submission as Record<string, unknown> : null;
    const requirements = Array.isArray(stage.requirements) ? stage.requirements : [];
    return [{
      id: stage.id,
      title: stage.title,
      position: typeof stage.position === "number" ? stage.position : 0,
      required: stage.required !== false,
      requirementLabels: requirements.flatMap((entry) => (
        entry && typeof entry === "object" && !Array.isArray(entry)
          && typeof (entry as Record<string, unknown>).label === "string"
          ? [String((entry as Record<string, unknown>).label)] : []
      )),
      status: String(stage.status || "pending") as ProjectProcessStageSnapshot["status"],
      summary: submission && typeof submission.summary === "string" ? submission.summary : "",
      missing: submission && Array.isArray(submission.missing)
        ? submission.missing.filter((entry): entry is string => typeof entry === "string") : [],
    }];
  }) : [];
  return {
    id: rawProcess.id,
    projectId: rawProcess.project_id,
    name: rawProcess.name,
    ordered: rawProcess.ordered === true,
    status: String(rawProcess.status || "active") as ProjectProcessSnapshot["status"],
    revision: typeof rawProcess.revision === "number" ? rawProcess.revision : 0,
    stages,
    updatedAt: typeof rawProcess.updated_at === "number" ? rawProcess.updated_at : 0,
    satisfiedAt: typeof rawProcess.satisfied_at === "number" ? rawProcess.satisfied_at : null,
  };
}

function projectDetailSnapshot(value: unknown): ProjectDetailSnapshot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const project = projectSnapshot(item.project);
  if (!project) return null;
  const process = projectProcessSnapshot(item.process);
  const steps = Array.isArray(item.steps) ? item.steps.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const step = value as Record<string, unknown>;
    if (typeof step.step_id !== "string" || typeof step.title !== "string") return [];
    return [{
      stepId: step.step_id,
      parentStepId: typeof step.parent_step_id === "string" ? step.parent_step_id : null,
      title: step.title,
      position: typeof step.position === "number" ? step.position : 0,
      status: String(step.status || "pending") as ProjectStepSnapshot["status"],
      summary: typeof step.summary === "string" ? step.summary : "",
      completedUnits: typeof step.completed_units === "number" ? step.completed_units : null,
      totalUnits: typeof step.total_units === "number" ? step.total_units : null,
      updatedAt: typeof step.updated_at === "number" ? step.updated_at : 0,
    }];
  }) : [];
  const assets = Array.isArray(item.assets) ? item.assets.flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const asset = value as Record<string, unknown>;
    if (typeof asset.id !== "string" || typeof asset.name !== "string") return [];
    return [{
      id: asset.id,
      role: String(asset.role || "working") as ProjectAssetSnapshot["role"],
      kind: typeof asset.kind === "string" ? asset.kind : "file",
      name: asset.name,
      mimeType: typeof asset.mime_type === "string" ? asset.mime_type : "",
      size: typeof asset.size === "number" ? asset.size : 0,
      status: String(asset.status || "available") as ProjectAssetSnapshot["status"],
      updatedAt: typeof asset.updated_at === "number" ? asset.updated_at : 0,
    }];
  }) : [];
  let latestReview: ProjectReviewSnapshot | null = null;
  if (Array.isArray(item.events)) {
    const reviews: ProjectReviewSnapshot[] = [];
    for (const value of item.events) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const event = value as Record<string, unknown>;
      if (event.type !== "reviewed" || !event.payload || typeof event.payload !== "object"
        || Array.isArray(event.payload)) continue;
      const payload = event.payload as Record<string, unknown>;
      reviews.push({
        assessment: typeof payload.assessment === "string" ? payload.assessment : "",
        planChanges: Array.isArray(payload.plan_changes)
          ? payload.plan_changes.filter((entry): entry is string => typeof entry === "string") : [],
        deviations: Array.isArray(payload.deviations)
          ? payload.deviations.filter((entry): entry is string => typeof entry === "string") : [],
        nextAction: typeof payload.next_action === "string" ? payload.next_action : "",
        createdAt: typeof event.created_at === "number" ? event.created_at : 0,
      });
    }
    reviews.sort((left, right) => left.createdAt - right.createdAt);
    const newest = reviews.at(-1);
    if (newest) {
      // A final acceptance review is often intentionally terse. Keep its
      // assessment and next action, while retaining the most recent structured
      // scope changes from the preceding substantive review.
      const latestPlanChanges = [...reviews].reverse()
        .find((review) => review.planChanges.length > 0)?.planChanges || [];
      const latestDeviations = [...reviews].reverse()
        .find((review) => review.deviations.length > 0)?.deviations || [];
      latestReview = {
        ...newest,
        planChanges: latestPlanChanges,
        deviations: latestDeviations,
      };
    }
  }
  return {
    project,
    process,
    steps,
    assets,
    assignments: Array.isArray(item.assignments)
      ? item.assignments.map(assignmentSnapshot).filter((entry): entry is AssignmentSnapshot => entry !== null)
      : [],
    activities: Array.isArray(item.activities)
      ? item.activities.map(activitySnapshot).filter((entry): entry is ActivitySnapshot => entry !== null)
      : [],
    latestReview,
  };
}

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

export interface PersonMemoryListState {
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  nextOffset: number | null;
  error: string;
}

interface CoreState {
  connectionByAgent: Record<string, ConnectionState>;
  messagesByAgent: Record<string, DisplayMessage[]>;
  messagesByConversation: Record<string, DisplayMessage[]>;
  assignmentsByAgent: Record<string, AssignmentSnapshot[]>;
  assignmentLoadingByAgent: Record<string, boolean>;
  assignmentErrorByAgent: Record<string, string>;
  currentProjectByAgent: Record<string, ProjectDetailSnapshot | null>;
  projectLoadingByAgent: Record<string, boolean>;
  projectErrorByAgent: Record<string, string>;
  activitiesByAgent: Record<string, ActivitySnapshot[]>;
  activityLoadingByAgent: Record<string, boolean>;
  activityErrorByAgent: Record<string, string>;
  artifactsByAgent: Record<string, ArtifactSnapshot[]>;
  artifactLoadingByAgent: Record<string, boolean>;
  artifactErrorByAgent: Record<string, string>;
  personMemoriesByAgent: Record<string, PersonMemorySnapshot[]>;
  personMemoryListByAgent: Record<string, PersonMemoryListState>;
  agentStateByAgent: Record<string, AgentStateSnapshot>;
  speakingByAgent: Record<string, { body: string; startedAt: number }>;
  sendingByAgent: Record<string, boolean>;
  sendingByConversation: Record<string, boolean>;
  draftByAgent: Record<string, string>;
  draftByConversation: Record<string, string>;
  attachmentsByConversation: Record<string, ChatAttachment[]>;
  artifactReferencesByConversation: Record<string, ChatArtifactReference[]>;
  attachmentErrorByConversation: Record<string, string>;
  invocationByConversation: Record<string, ChatInvocationSelection | undefined>;
  activeAgentId: string | null;
  agents: AgentEntry[];
  page: "connect" | "chat";
  terminalOpen: boolean;
  terminalAgentId: string | null;
  activeNav: string;
  unreadByAgent: Record<string, number>;
  unreadByConversation: Record<string, number>;
  recentConversationKeys: string[];
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
  connect: (host: string, port: number, token: string) => Promise<boolean>;
  connectToAgent: (agentId: string) => Promise<void>;
  switchAgent: (agentId: string) => Promise<void>;
  addAgent: (host: string, port: number, token: string) => string;
  removeAgent: (agentId: string) => void;
  disconnectAgent: (agentId: string) => Promise<void>;
  resetIdentityState: () => void;
  sendMessage: (
    text: string,
    artifactReferences?: ChatArtifactReference[],
    options?: { preserveComposer?: boolean },
  ) => void;
  pickAttachments: () => Promise<void>;
  addAttachments: (attachments: ChatAttachment[]) => void;
  addArtifactReference: (reference: ChatArtifactReference) => void;
  removeArtifactReference: (artifactId: string, sessionId: string) => void;
  setAttachmentError: (error: string) => void;
  removeAttachment: (attachmentId: string) => void;
  abortMessage: () => Promise<void>;
  continueTurn: (turnId: string) => Promise<void>;
  retryMessage: (messageId: number) => Promise<void>;
  resumeCapabilityRequest: (messageId: number) => Promise<string>;
  respondToInteraction: (requestId: string, response: string) => Promise<void>;
  respondToAction: (actionId: string, decision: "allow" | "deny") => Promise<void>;
  setDraft: (text: string) => void;
  setInvocation: (invocation?: ChatInvocationSelection) => void;
  newSession: (name?: string) => Promise<void>;
  switchSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<string>;
  openSearchMessage: (sessionId: string, messageId: number) => Promise<void>;
  loadOlderMessages: () => Promise<void>;
  searchSessions: (query: string) => Promise<void>;
  loadMoreSessions: () => Promise<void>;
  refreshAssignments: (agentId?: string) => Promise<void>;
  refreshCurrentProject: (agentId?: string) => Promise<void>;
  refreshActivities: (agentId?: string) => Promise<void>;
  refreshArtifacts: (agentId?: string) => Promise<void>;
  refreshPersonMemories: (agentId?: string) => Promise<void>;
  loadMorePersonMemories: (agentId?: string) => Promise<void>;
  refreshAgentState: (agentId?: string) => Promise<void>;
  requestAssignmentCancel: (assignmentId: string, reason?: string) => Promise<string>;
  requestAssignmentResume: (
    assignmentId: string,
    response?: string,
    decision?: "approve" | "deny",
  ) => Promise<string>;
  setPage: (page: "connect" | "chat") => void;
  setTerminalOpen: (open: boolean) => void;
  openAgentLogs: (agentId: string) => void;
  setActiveNav: (nav: string) => void;
  clearUnread: (agentId: string) => void;
  refreshLocalAgents: () => Promise<void>;
  createLocalAgent: (
    name: string,
    description: string,
    options?: { activate?: boolean },
  ) => Promise<AgentCreationResult>;
  controlLocalAgent: (agentId: string, action: AgentLifecycleAction) => Promise<void>;
}

// ── Store ──

const persisted = loadPersisted();

export const useCoreStore = create<CoreState & CoreActions>()((set, get) => ({
  connectionByAgent: {},
  messagesByAgent: {},
  messagesByConversation: {},
  assignmentsByAgent: {},
  assignmentLoadingByAgent: {},
  assignmentErrorByAgent: {},
  currentProjectByAgent: {},
  projectLoadingByAgent: {},
  projectErrorByAgent: {},
  activitiesByAgent: {},
  activityLoadingByAgent: {},
  activityErrorByAgent: {},
  artifactsByAgent: {},
  artifactLoadingByAgent: {},
  artifactErrorByAgent: {},
  personMemoriesByAgent: {},
  personMemoryListByAgent: {},
  agentStateByAgent: {},
  speakingByAgent: {},
  sendingByAgent: {},
  sendingByConversation: {},
  draftByAgent: {},
  draftByConversation: {},
  attachmentsByConversation: {},
  artifactReferencesByConversation: {},
  attachmentErrorByConversation: {},
  invocationByConversation: {},
  activeAgentId: persisted.activeAgentId ?? null,
  agents: persisted.agents ?? [],
  page: (persisted.agents && persisted.agents.length > 0) ? "chat" : "connect",
  terminalOpen: false,
  terminalAgentId: null,
  activeNav: "assistant",
  unreadByAgent: {},
  unreadByConversation: {},
  recentConversationKeys: [],
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
          if (!localAgent.online) {
            const connection = s.connectionByAgent[agentId];
            if (connection) connection.status = "disconnected";
            delete s.agentStateByAgent[agentId];
            delete s.speakingByAgent[agentId];
            for (const key of Object.keys(s.sendingByConversation)) {
              if (key.startsWith(`${agentId}\u0000`)) s.sendingByConversation[key] = false;
            }
            s.sendingByAgent[agentId] = false;
          }
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
            const connection = s.connectionByAgent[agent.id];
            if (connection) connection.status = "disconnected";
            delete s.agentStateByAgent[agent.id];
            delete s.speakingByAgent[agent.id];
            for (const key of Object.keys(s.sendingByConversation)) {
              if (key.startsWith(`${agent.id}\u0000`)) s.sendingByConversation[key] = false;
            }
            s.sendingByAgent[agent.id] = false;
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

  createLocalAgent: async (name, description, options) => {
    const result = await window.localAgents.create({ name, description });
    if (!result.ok || !result.agentId) return result;

    await get().refreshLocalAgents();
    if (options?.activate !== false) {
      set(produce((s: CoreState) => {
        const created = s.agents.find((agent) => agent.localAgentId === result.agentId);
        if (created) {
          s.activeAgentId = created.id;
          s.page = "chat";
        }
      }));
    }
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

  connect: async (host, port, token) => {
    const agentId = `${host}:${port}`;

    set(produce((s: CoreState) => {
      s.connectionByAgent[agentId] = { status: "connecting", agentName: "", error: "" };
    }));

    try {
      const requestedSessionId = get().activeSessionByAgent[agentId] || undefined;
      const res = await window.gateway.connect({ host, port, token, agentId, sessionId: requestedSessionId });
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
        if (sessionId) s.messagesByConversation[conversationStateKey(agentId, sessionId)] = messages;
        s.sessionsByAgent[agentId] = sessionResult.sessions;
        s.sessionListByAgent[agentId] = sessionResult.listState;
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = pagination;
        }
        if (sessionId) {
          setSessionSending(
            s,
            agentId,
            sessionId,
            resume?.state === "running" || resume?.state === "waiting_user",
          );
        }
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
        agentId, sessionId: requestedSessionId,
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
        if (sessionId) s.messagesByConversation[conversationStateKey(agentId, sessionId)] = messages;
        s.sessionsByAgent[agentId] = sessionResult.sessions;
        s.sessionListByAgent[agentId] = sessionResult.listState;
        if (sessionId) {
          s.activeSessionByAgent[agentId] = sessionId;
          if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
          s.historyPaginationByAgent[agentId][sessionId] = pagination;
        }
        if (sessionId) {
          setSessionSending(
            s,
            agentId,
            sessionId,
            resume?.state === "running" || resume?.state === "waiting_user",
          );
        }
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
    if (get().agents.find(a => a.id === agentId)) return agentId;

    set(produce((s: CoreState) => {
      s.agents.push({ id: agentId, name: agentId, host, port, token, source: "manual" });
      if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
    }));

    get().connectToAgent(agentId);
    return agentId;
  },

  // ── Remove agent ──

  removeAgent: (agentId) => {
    window.gateway.disconnect({ agentId }).catch(() => {});

    set(produce((s: CoreState) => {
      delete s.connectionByAgent[agentId];
      delete s.messagesByAgent[agentId];
      for (const key of Object.keys(s.messagesByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.messagesByConversation[key];
      }
      delete s.assignmentsByAgent[agentId];
      delete s.assignmentLoadingByAgent[agentId];
      delete s.assignmentErrorByAgent[agentId];
      delete s.currentProjectByAgent[agentId];
      delete s.projectLoadingByAgent[agentId];
      delete s.projectErrorByAgent[agentId];
      delete s.activitiesByAgent[agentId];
      delete s.activityLoadingByAgent[agentId];
      delete s.activityErrorByAgent[agentId];
      delete s.agentStateByAgent[agentId];
      delete s.speakingByAgent[agentId];
      delete s.artifactsByAgent[agentId];
      delete s.artifactLoadingByAgent[agentId];
      delete s.artifactErrorByAgent[agentId];
      delete s.personMemoriesByAgent[agentId];
      delete s.personMemoryListByAgent[agentId];
      delete s.sendingByAgent[agentId];
      for (const key of Object.keys(s.sendingByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.sendingByConversation[key];
      }
      delete s.draftByAgent[agentId];
      for (const key of Object.keys(s.draftByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.draftByConversation[key];
      }
      for (const key of Object.keys(s.artifactReferencesByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.artifactReferencesByConversation[key];
      }
      for (const key of Object.keys(s.invocationByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.invocationByConversation[key];
      }
      for (const key of Object.keys(s.unreadByConversation)) {
        if (key.startsWith(`${agentId}\u0000`)) delete s.unreadByConversation[key];
      }
      s.recentConversationKeys = s.recentConversationKeys
        .filter((key) => !key.startsWith(`${agentId}\u0000`));
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
      delete s.speakingByAgent[agentId];
    }));
  },

  // ── Send message ──

  sendMessage: (text, artifactReferences = [], options = {}) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId] || "";
    const draftKey = attachmentDraftKey(agentId, sessionId);
    const composerReferences = options.preserveComposer
      ? artifactReferences
      : artifactReferences.length > 0
        ? artifactReferences
        : (get().artifactReferencesByConversation[draftKey] || []);
    const attachments = options.preserveComposer
      ? []
      : (get().attachmentsByConversation[draftKey] || []);
    const invocation = get().invocationByConversation[draftKey];
    if (!text.trim() && attachments.length === 0 && composerReferences.length === 0) return;
    const clientRequestId = crypto.randomUUID();

    set(produce((s: CoreState) => {
      if (!s.messagesByAgent[agentId]) s.messagesByAgent[agentId] = [];
      s.messagesByAgent[agentId].push({
        id: `user-${clientRequestId}`, role: "user", content: text, streaming: false,
        createdAt: Date.now(),
        deliveryStatus: "processing",
        invocation: invocation ? { ...invocation } : undefined,
        attachments: [
          ...attachments.map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          mimeType: attachment.mimeType,
          size: attachment.size,
          kind: attachment.kind,
          previewUrl: attachment.kind === "image" && attachment.dataBase64
            ? `data:${attachment.mimeType};base64,${attachment.dataBase64}`
            : undefined,
          })),
          ...composerReferences.map((reference) => ({
            id: reference.artifactId,
            name: reference.name || i18n.t("preview.document"),
            mimeType: reference.mimeType || "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size: reference.size || 0,
            kind: reference.kind === "image"
              ? "image" as const
              : reference.kind === "audio"
                ? "audio" as const
                : reference.kind === "video"
                  ? "video" as const
                  : reference.kind === "text"
                    ? "text" as const
                    : "document" as const,
            annotation: reference.selection ? {
              selectedText: reference.selection.selectedText,
              page: reference.selection.kind === "text" ? reference.selection.page : undefined,
              sheet: reference.selection.kind === "spreadsheet" ? reference.selection.sheet : undefined,
              range: reference.selection.kind === "spreadsheet" ? reference.selection.range : undefined,
            } : undefined,
          })),
        ],
      });
      s.messagesByAgent[agentId].push({
        id: pendingRequestResponseId(clientRequestId),
        role: "agent",
        content: "",
        streaming: true,
        createdAt: Date.now(),
        responsePhase: "replying",
      });
      touchSession(s, agentId, s.activeSessionByAgent[agentId] || "", 1, text);
      setSessionSending(s, agentId, sessionId, true);
      if (!options.preserveComposer) {
        s.draftByAgent[agentId] = "";
        s.draftByConversation[conversationStateKey(agentId, sessionId)] = "";
        delete s.attachmentsByConversation[draftKey];
        delete s.artifactReferencesByConversation[draftKey];
        delete s.attachmentErrorByConversation[draftKey];
        delete s.invocationByConversation[draftKey];
      }
    }));

    void window.gateway.sendMessage({
      content: text,
      agentId,
      sessionId,
      clientRequestId,
      attachments,
      artifactReferences: composerReferences,
      invocation,
    }).then((res) => {
      if (!res.error && res.result?.accepted !== false) {
        set(produce((s: CoreState) => {
          const userMessage = messagesForSession(s, agentId, sessionId)
            .find((message) => message.id === `user-${clientRequestId}`);
          if (userMessage && typeof res.result?.turn_id === "string") {
            userMessage.turnId = res.result.turn_id;
          }
          if (userMessage && typeof res.result?.message_id === "number") {
            userMessage.sourceMessageId = res.result.message_id;
          }
          if (userMessage && res.result?.status === "queued") {
            userMessage.deliveryStatus = res.result?.deferred === true
              ? "queued"
              : "processing";
          } else if (userMessage && res.result?.status === "steering") {
            userMessage.deliveryStatus = "processing";
            if (typeof res.result?.active_turn_id === "string") {
              userMessage.steeredIntoTurnId = res.result.active_turn_id;
            }
          }
          const localPendingId = pendingRequestResponseId(clientRequestId);
          const localPendingIndex = messagesForSession(s, agentId, sessionId)
            .findIndex((message) => message.id === localPendingId);
          if (res.result?.status === "steering") {
            if (localPendingIndex >= 0) {
              messagesForSession(s, agentId, sessionId).splice(localPendingIndex, 1);
            }
            return;
          }
          const turnId = typeof res.result?.turn_id === "string"
            ? res.result.turn_id
            : "";
          if (turnId) {
            const sessionMessages = messagesForSession(s, agentId, sessionId);
            const terminal = sessionMessages.find((message) => (
              message.role === "agent"
              && message.turnId === turnId
              && !message.streaming
              && !message.responsePhase
              && Boolean(message.content.trim())
            ));
            const existing = sessionMessages.find((message) => (
              message.role === "agent"
              && message.turnId === turnId
              && (message.responsePhase || message.streaming)
            ));
            const localPending = sessionMessages.find((message) => message.id === localPendingId);
            // Gateway events and the chat.send RPC response travel on separate
            // paths. A fast Agent can start, or even complete, before this
            // callback runs. Never rename or revive a message already claimed
            // by the event stream: its stable id is how message.complete finds
            // and finalizes the same renderer entry.
            if (terminal) {
              if (localPending && localPending !== terminal) {
                sessionMessages.splice(sessionMessages.indexOf(localPending), 1);
              }
            } else if (existing && localPending && existing !== localPending) {
              sessionMessages.splice(sessionMessages.indexOf(localPending), 1);
            } else if (localPending) {
              localPending.turnId = turnId;
              localPending.responsePhase = res.result?.deferred === true ? "waiting" : "replying";
            } else if (!existing) {
              sessionMessages.push({
                id: pendingResponseId(turnId),
                role: "agent",
                content: "",
                streaming: true,
                createdAt: Date.now(),
                turnId,
                responsePhase: res.result?.deferred === true ? "waiting" : "replying",
              });
            }
          }
        }));
        return;
      }

      const message = res.error?.message || "Message was not accepted";
      set(produce((s: CoreState) => {
        const sessionMessages = messagesForSession(s, agentId, sessionId);
        const pendingIndex = sessionMessages
          .findIndex((entry) => entry.id === pendingRequestResponseId(clientRequestId));
        if (pendingIndex >= 0) sessionMessages.splice(pendingIndex, 1);
        const userMessage = sessionMessages
          .find((entry) => entry.id === `user-${clientRequestId}`);
        if (userMessage) {
          userMessage.deliveryStatus = "failed";
          userMessage.deliveryError = message;
        }
        sessionMessages.push({
          id: `send-error-${Date.now()}`,
          role: "agent",
          content: `Error: ${message}`,
          streaming: false,
        });
        setSessionSending(s, agentId, sessionId, false);
      }));
    }).catch((error) => {
      set(produce((s: CoreState) => {
        const sessionMessages = messagesForSession(s, agentId, sessionId);
        const pendingIndex = sessionMessages
          .findIndex((entry) => entry.id === pendingRequestResponseId(clientRequestId));
        if (pendingIndex >= 0) sessionMessages.splice(pendingIndex, 1);
        const userMessage = sessionMessages
          .find((entry) => entry.id === `user-${clientRequestId}`);
        if (userMessage) {
          userMessage.deliveryStatus = "failed";
          userMessage.deliveryError = String(error);
        }
        sessionMessages.push({
          id: `send-error-${Date.now()}`,
          role: "agent",
          content: `Error: ${error}`,
          streaming: false,
        });
        setSessionSending(s, agentId, sessionId, false);
      }));
    });
  },

  // Person-scoped data must never survive a Desktop account switch. Agent
  // discovery and lifecycle state are host-scoped and intentionally remain.
  resetIdentityState: () => {
    for (const agentId of Object.keys(get().connectionByAgent)) {
      clearAgentStreams(agentId);
    }
    set(produce((s: CoreState) => {
      s.connectionByAgent = {};
      s.messagesByAgent = {};
      s.messagesByConversation = {};
      s.assignmentsByAgent = {};
      s.assignmentLoadingByAgent = {};
      s.assignmentErrorByAgent = {};
      s.currentProjectByAgent = {};
      s.projectLoadingByAgent = {};
      s.projectErrorByAgent = {};
      s.activitiesByAgent = {};
      s.activityLoadingByAgent = {};
      s.activityErrorByAgent = {};
      s.artifactsByAgent = {};
      s.artifactLoadingByAgent = {};
      s.artifactErrorByAgent = {};
      s.personMemoriesByAgent = {};
      s.personMemoryListByAgent = {};
      s.agentStateByAgent = {};
      s.speakingByAgent = {};
      s.sendingByAgent = {};
      s.sendingByConversation = {};
      s.draftByAgent = {};
      s.draftByConversation = {};
      s.attachmentsByConversation = {};
      s.artifactReferencesByConversation = {};
      s.attachmentErrorByConversation = {};
      s.invocationByConversation = {};
      s.unreadByAgent = {};
      s.unreadByConversation = {};
      s.recentConversationKeys = [];
      s.sessionsByAgent = {};
      s.sessionListByAgent = {};
      s.activeSessionByAgent = {};
      s.historyPaginationByAgent = {};
    }));
  },

  pickAttachments: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId];
    const draftKey = attachmentDraftKey(agentId, sessionId);
    let result;
    try {
      result = await window.gateway.pickAttachments();
    } catch (error) {
      set(produce((s: CoreState) => {
        s.attachmentErrorByConversation[draftKey] = String(error);
      }));
      return;
    }
    if (result.error) {
      get().setAttachmentError(result.error);
      return;
    }
    get().addAttachments(result.attachments);
  },

  addAttachments: (attachments) => {
    const agentId = get().activeAgentId;
    if (!agentId || attachments.length === 0) return;
    const draftKey = attachmentDraftKey(agentId, get().activeSessionByAgent[agentId]);
    set(produce((s: CoreState) => {
      s.attachmentErrorByConversation[draftKey] = "";
      const existing = s.attachmentsByConversation[draftKey] || [];
      const references = s.artifactReferencesByConversation[draftKey] || [];
      const additions = attachments.filter((item) => !existing.some(
        (current) => current.name === item.name && current.size === item.size,
      ));
      if (existing.length + references.length + additions.length > 4) {
        s.attachmentErrorByConversation[draftKey] = i18n.t("home.maxAttachments");
        return;
      }
      const combined = [...existing, ...additions];
      const invalidItem = additions.find((item) => item.size > (
        item.kind === "video" ? 20 * 1024 * 1024 : 5 * 1024 * 1024
      ));
      if (invalidItem) {
        const limit = invalidItem.kind === "video" ? 20 : 5;
        s.attachmentErrorByConversation[draftKey] = i18n.t("home.fileTooLarge", { name: invalidItem.name, size: limit });
        return;
      }
      const total = combined.reduce((sum, item) => sum + item.size, 0);
      const totalLimit = combined.some((item) => item.kind === "video")
        ? 32 * 1024 * 1024
        : 8 * 1024 * 1024;
      if (total > totalLimit) {
        s.attachmentErrorByConversation[draftKey] = i18n.t("home.attachmentTotalLimit", { size: totalLimit / 1024 / 1024 });
        return;
      }
      s.attachmentsByConversation[draftKey] = combined;
    }));
  },

  addArtifactReference: (reference) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const draftKey = attachmentDraftKey(agentId, get().activeSessionByAgent[agentId]);
    set(produce((s: CoreState) => {
      const existing = s.artifactReferencesByConversation[draftKey] || [];
      if (existing.some((item) => (
        item.artifactId === reference.artifactId && item.sessionId === reference.sessionId
      ))) return;
      const attachments = s.attachmentsByConversation[draftKey] || [];
      if (attachments.length + existing.length >= 4) {
        s.attachmentErrorByConversation[draftKey] = i18n.t("home.maxAttachments");
        return;
      }
      touchConversationState(s, agentId, get().activeSessionByAgent[agentId] || "new");
      s.artifactReferencesByConversation[draftKey] = [...existing, reference];
      delete s.attachmentErrorByConversation[draftKey];
    }));
  },

  removeArtifactReference: (artifactId, sessionId) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const draftKey = attachmentDraftKey(agentId, get().activeSessionByAgent[agentId]);
    set(produce((s: CoreState) => {
      s.artifactReferencesByConversation[draftKey] = (
        s.artifactReferencesByConversation[draftKey] || []
      ).filter((reference) => !(
        reference.artifactId === artifactId && reference.sessionId === sessionId
      ));
      delete s.attachmentErrorByConversation[draftKey];
    }));
  },

  setAttachmentError: (error) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const draftKey = attachmentDraftKey(agentId, get().activeSessionByAgent[agentId]);
    set(produce((s: CoreState) => {
      s.attachmentErrorByConversation[draftKey] = error;
    }));
  },

  removeAttachment: (attachmentId) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const draftKey = attachmentDraftKey(agentId, get().activeSessionByAgent[agentId]);
    set(produce((s: CoreState) => {
      s.attachmentsByConversation[draftKey] = (s.attachmentsByConversation[draftKey] || [])
        .filter((attachment) => attachment.id !== attachmentId);
      delete s.attachmentErrorByConversation[draftKey];
    }));
  },

  // ── Abort message ──

  abortMessage: async () => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId] || "";
    const activeResponse = [...(get().messagesByAgent[agentId] || [])]
      .reverse()
      .find((message) => message.role === "agent"
        && Boolean(message.turnId)
        && Boolean(message.streaming || message.responsePhase));
    const turnId = activeResponse?.turnId || "";
    if (!sessionId || !turnId) return;

    const res = await window.gateway.abortMessage({ agentId, sessionId, turnId });
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

    if (res.result?.aborted === true) {
      clearSessionStreams(agentId, sessionId);
      set(produce((s: CoreState) => { setSessionSending(s, agentId, sessionId, false); }));
    }
  },

  continueTurn: async (turnId) => {
    const agentId = get().activeAgentId;
    const sessionId = agentId ? get().activeSessionByAgent[agentId] || "" : "";
    if (!agentId || !sessionId || !turnId
      || get().sendingByConversation[conversationStateKey(agentId, sessionId)]) return;
    const clientRequestId = crypto.randomUUID();
    const optimisticId = `continue-${clientRequestId}`;
    set(produce((s: CoreState) => {
      s.messagesByAgent[agentId].push({
        id: optimisticId,
        role: "user",
        content: i18n.t("home.continue"),
        streaming: false,
        createdAt: Date.now(),
        deliveryStatus: "processing",
      });
      setSessionSending(s, agentId, sessionId, true);
      touchSession(s, agentId, sessionId, 1, i18n.t("home.continue"));
    }));
    try {
      const response = await window.gateway.continueMessage({
        agentId, sessionId, interruptedTurnId: turnId, clientRequestId,
      });
      if (response.error || response.result?.accepted === false) {
        throw new Error(response.error?.message || String(response.result?.reason || "Continue failed"));
      }
      set(produce((s: CoreState) => {
        const message = s.messagesByAgent[agentId]
          .find((item) => item.id === optimisticId);
        if (!message) return;
        if (typeof response.result?.turn_id === "string") message.turnId = response.result.turn_id;
        if (typeof response.result?.message_id === "number") message.sourceMessageId = response.result.message_id;
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        const message = s.messagesByAgent[agentId]
          .find((item) => item.id === optimisticId);
        if (message) {
          message.deliveryStatus = "failed";
          message.deliveryError = String(error);
        }
        setSessionSending(s, agentId, sessionId, false);
      }));
    }
  },

  retryMessage: async (messageId) => {
    const agentId = get().activeAgentId;
    const sessionId = agentId ? get().activeSessionByAgent[agentId] || "" : "";
    if (!agentId || !sessionId
      || get().sendingByConversation[conversationStateKey(agentId, sessionId)]) return;
    const source = (get().messagesByAgent[agentId] || [])
      .find((message) => message.sourceMessageId === messageId);
    if (!source || !["failed", "interrupted"].includes(source.deliveryStatus || "")) return;
    const clientRequestId = crypto.randomUUID();
    const optimisticId = `retry-${clientRequestId}`;
    set(produce((s: CoreState) => {
      s.messagesByAgent[agentId].push({
        id: optimisticId,
        role: "user",
        content: source.content,
        streaming: false,
        createdAt: Date.now(),
        attachments: source.attachments,
        deliveryStatus: "processing",
        retryOf: messageId,
      });
      setSessionSending(s, agentId, sessionId, true);
      touchSession(s, agentId, sessionId, 1, source.content);
    }));
    try {
      const response = await window.gateway.retryMessage({
        agentId, sessionId, messageId, clientRequestId,
      });
      if (response.error || response.result?.accepted === false) {
        const error = response.error?.message || String(response.result?.reason || "Message was not accepted");
        set(produce((s: CoreState) => {
          s.messagesByAgent[agentId] = (s.messagesByAgent[agentId] || [])
            .filter((message) => message.id !== optimisticId);
          const original = s.messagesByAgent[agentId]
            .find((message) => message.sourceMessageId === messageId);
          if (original) original.deliveryError = error;
          setSessionSending(s, agentId, sessionId, false);
        }));
        return;
      }
      set(produce((s: CoreState) => {
        const retried = s.messagesByAgent[agentId]
          .find((message) => message.id === optimisticId);
        if (!retried) return;
        if (typeof response.result?.turn_id === "string") retried.turnId = response.result.turn_id;
        if (typeof response.result?.message_id === "number") retried.sourceMessageId = response.result.message_id;
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.messagesByAgent[agentId] = (s.messagesByAgent[agentId] || [])
          .filter((message) => message.id !== optimisticId);
        const original = s.messagesByAgent[agentId]
          .find((message) => message.sourceMessageId === messageId);
        if (original) original.deliveryError = String(error);
        setSessionSending(s, agentId, sessionId, false);
      }));
    }
  },

  resumeCapabilityRequest: async (messageId) => {
    const agentId = get().activeAgentId;
    const sessionId = agentId ? get().activeSessionByAgent[agentId] || "" : "";
    if (!agentId || !sessionId) return i18n.t("storeUi.sessionUnavailable");
    if (get().sendingByConversation[conversationStateKey(agentId, sessionId)]) {
      return i18n.t("storeUi.sessionProcessing");
    }
    const source = (get().messagesByAgent[agentId] || [])
      .find((message) => message.sourceMessageId === messageId && message.role === "user");
    if (!source) return i18n.t("storeUi.blockedRequestMissing");

    const clientRequestId = crypto.randomUUID();
    const optimisticId = `capability-resume-${clientRequestId}`;
    set(produce((s: CoreState) => {
      s.messagesByAgent[agentId].push({
        id: optimisticId,
        role: "user",
        content: source.content,
        streaming: false,
        createdAt: Date.now(),
        attachments: source.attachments,
        deliveryStatus: "processing",
        retryOf: messageId,
      });
      setSessionSending(s, agentId, sessionId, true);
      touchSession(s, agentId, sessionId, 1, source.content);
    }));
    try {
      const response = await window.gateway.retryMessage({
        agentId, sessionId, messageId, clientRequestId,
      });
      if (response.error || response.result?.accepted === false) {
        const error = response.error?.message || String(response.result?.reason || i18n.t("storeUi.resumeFailed"));
        set(produce((s: CoreState) => {
          s.messagesByAgent[agentId] = (s.messagesByAgent[agentId] || [])
            .filter((message) => message.id !== optimisticId);
          setSessionSending(s, agentId, sessionId, false);
        }));
        return error;
      }
      set(produce((s: CoreState) => {
        const resumed = s.messagesByAgent[agentId]
          .find((message) => message.id === optimisticId);
        if (!resumed) return;
        if (typeof response.result?.turn_id === "string") resumed.turnId = response.result.turn_id;
        if (typeof response.result?.message_id === "number") resumed.sourceMessageId = response.result.message_id;
      }));
      return "";
    } catch (error) {
      set(produce((s: CoreState) => {
        s.messagesByAgent[agentId] = (s.messagesByAgent[agentId] || [])
          .filter((message) => message.id !== optimisticId);
        setSessionSending(s, agentId, sessionId, false);
      }));
      return String(error instanceof Error ? error.message : error);
    }
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

  respondToAction: async (actionId, decision) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const action = (get().messagesByAgent[agentId] || [])
      .find((entry) => entry.action?.id === actionId)?.action;
    if (!action?.turnId) return;
    set(produce((s: CoreState) => {
      const message = (s.messagesByAgent[agentId] || [])
        .find((entry) => entry.action?.id === actionId);
      if (message?.action) {
        message.action.status = "responding";
        message.action.error = "";
      }
    }));
    const response = await window.gateway.respondAction({
      agentId,
      actionId,
      turnId: action.turnId,
      decision,
    });
    if (response.error) {
      set(produce((s: CoreState) => {
        const message = (s.messagesByAgent[agentId] || [])
          .find((entry) => entry.action?.id === actionId);
        if (message?.action) {
          message.action.status = "error";
          message.action.error = response.error!.message;
        }
      }));
    }
  },

  setDraft: (text) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId];
    set(produce((s: CoreState) => {
      touchConversationState(s, agentId, sessionId || "new");
      s.draftByAgent[agentId] = text;
      s.draftByConversation[conversationStateKey(agentId, sessionId)] = text;
    }));
  },

  setInvocation: (invocation) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    const sessionId = get().activeSessionByAgent[agentId];
    set(produce((s: CoreState) => {
      const key = conversationStateKey(agentId, sessionId);
      touchConversationState(s, agentId, sessionId || "new");
      if (invocation) s.invocationByConversation[key] = invocation;
      else delete s.invocationByConversation[key];
    }));
  },

  // ── Session management ──

  newSession: async (name) => {
    const agentId = get().activeAgentId;
    if (!agentId) return;
    if (get().sendingByAgent[agentId]) return;
    if (get().connectionByAgent[agentId]?.status === "connecting") return;
    // An empty active session is already the place for a new conversation.
    // Do not ask the Gateway to create another empty session beside it.
    if (!name && (get().messagesByAgent[agentId]?.length || 0) === 0) return;
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
          touchConversationState(s, agentId, sessionId);
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
    if (get().connectionByAgent[agentId]?.status === "connecting") return;
    const previousSessionId = get().activeSessionByAgent[agentId] || "";
    if (previousSessionId === sessionId) return;
    const agent = get().agents.find((entry) => entry.id === agentId);
    if (!agent) return;
    const switchRequest = (_sessionSwitchRequestByAgent[agentId] || 0) + 1;
    _sessionSwitchRequestByAgent[agentId] = switchRequest;

    // Seal the visible conversation before awaiting IPC. Saving it after the
    // await can copy whichever conversation became active in the meantime
    // into the previous session's cache.
    if (previousSessionId) {
      set(produce((s: CoreState) => {
        if (s.activeSessionByAgent[agentId] !== previousSessionId) return;
        s.messagesByConversation[conversationStateKey(agentId, previousSessionId)] = [
          ...(s.messagesByAgent[agentId] || []),
        ];
      }));
    }

    try {
      const res = await window.gateway.switchSession({ agentId, sessionId });
      if (_sessionSwitchRequestByAgent[agentId] !== switchRequest) return;
      if (res.error) {
        set(produce((s: CoreState) => {
          const connection = s.connectionByAgent[agentId];
          if (connection) connection.error = res.error!.message;
        }));
        return;
      }

      const result = (res.result || {}) as Record<string, unknown>;
      if (typeof result.session_id === "string" && result.session_id !== sessionId) {
        throw new Error(`Session switch returned ${result.session_id}, expected ${sessionId}`);
      }
      const resume = result.resume && typeof result.resume === "object"
        ? result.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      const pagination = historyPagination(resume);
      set(produce((s: CoreState) => {
        const targetKey = conversationStateKey(agentId, sessionId);
        touchConversationState(s, agentId, sessionId);
        // The Gateway snapshot is authoritative. Reusing any non-empty local
        // cache here made one accidental cross-session alias permanent.
        s.messagesByAgent[agentId] = messages;
        s.messagesByConversation[targetKey] = messages;
        s.activeSessionByAgent[agentId] = sessionId;
        s.unreadByConversation[conversationStateKey(agentId, sessionId)] = 0;
        if (!s.historyPaginationByAgent[agentId]) s.historyPaginationByAgent[agentId] = {};
        s.historyPaginationByAgent[agentId][sessionId] = pagination;
        const connection = s.connectionByAgent[agentId];
        if (connection) {
          connection.agentName = (result.agent_name as string) || agent.name;
          connection.error = "";
        }
        setSessionSending(
          s,
          agentId,
          sessionId,
          resume?.state === "running" || resume?.state === "waiting_user",
        );
      }));
      restoreStreamFromResume(agentId, sessionId, resume);
    } catch (error) {
      if (_sessionSwitchRequestByAgent[agentId] !== switchRequest) return;
      set(produce((s: CoreState) => {
        const connection = s.connectionByAgent[agentId];
        if (connection) connection.error = String(error);
      }));
    }
  },

  // ── UI ──

  deleteSession: async (sessionId) => {
    const agentId = get().activeAgentId;
    if (!agentId || !sessionId) return i18n.t("storeUi.sessionUnavailable");
    const conversationKey = conversationStateKey(agentId, sessionId);
    if (get().sendingByConversation[conversationKey]) {
      return i18n.t("sidebar.sessionDeleteWorking");
    }

    if (get().activeSessionByAgent[agentId] === sessionId) {
      const fallback = (get().sessionsByAgent[agentId] || [])
        .find((session) => session.id !== sessionId);
      if (fallback) {
        await get().switchSession(fallback.id);
      } else {
        // Deleting the only conversation still needs a replacement even when
        // the current conversation is empty; the normal new-session action
        // intentionally suppresses duplicate empty conversations.
        await get().newSession(i18n.t("sidebar.newSession"));
      }
      if (get().activeSessionByAgent[agentId] === sessionId) {
        return i18n.t("sidebar.sessionDeleteSwitchFailed");
      }
    }

    const response = await window.gateway.deleteSession({ agentId, sessionId });
    if (response.error) return response.error.message || i18n.t("sidebar.sessionDeleteFailed");

    set(produce((s: CoreState) => {
      s.sessionsByAgent[agentId] = (s.sessionsByAgent[agentId] || [])
        .filter((session) => session.id !== sessionId);
      delete s.messagesByConversation[conversationKey];
      delete s.sendingByConversation[conversationKey];
      delete s.draftByConversation[conversationKey];
      delete s.attachmentsByConversation[conversationKey];
      delete s.artifactReferencesByConversation[conversationKey];
      delete s.attachmentErrorByConversation[conversationKey];
      delete s.invocationByConversation[conversationKey];
      delete s.unreadByConversation[conversationKey];
      s.recentConversationKeys = s.recentConversationKeys
        .filter((key) => key !== conversationKey);
      if (s.historyPaginationByAgent[agentId]) {
        delete s.historyPaginationByAgent[agentId][sessionId];
      }
    }));
    return "";
  },

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
      const sessions = includeActiveSession(
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

  openSearchMessage: async (sessionId, messageId) => {
    const agentId = get().activeAgentId;
    if (!agentId || !sessionId || messageId < 1) return;

    await get().switchSession(sessionId);
    if (get().activeAgentId !== agentId || get().activeSessionByAgent[agentId] !== sessionId) return;

    const targetId = `history-${sessionId}-${messageId}`;
    const conversationKey = conversationStateKey(agentId, sessionId);
    let found = (get().messagesByAgent[agentId] || []).some((message) => message.id === targetId);

    // Search can hit a message older than the resumed 50-message window. Load
    // complete history pages until the target becomes part of the visible,
    // continuous conversation timeline.
    while (!found) {
      const page = get().historyPaginationByAgent[agentId]?.[sessionId];
      if (!page?.hasMore || !page.beforeId) break;

      const response = await window.gateway.getHistory({
        agentId,
        sessionId,
        limit: 200,
        beforeId: page.beforeId,
      });
      if (response.error) break;

      const olderMessages = historyMessages(response.result, sessionId);
      const nextPage = historyPagination(response.result);
      set(produce((state: CoreState) => {
        if (state.activeAgentId !== agentId || state.activeSessionByAgent[agentId] !== sessionId) return;
        const currentMessages = state.messagesByAgent[agentId] || [];
        const currentIds = new Set(currentMessages.map((message) => message.id));
        const uniqueOlder = olderMessages.filter((message) => !currentIds.has(message.id));
        const merged = [...uniqueOlder, ...currentMessages];
        state.messagesByAgent[agentId] = merged;
        state.messagesByConversation[conversationKey] = merged;
        if (!state.historyPaginationByAgent[agentId]) state.historyPaginationByAgent[agentId] = {};
        state.historyPaginationByAgent[agentId][sessionId] = nextPage;
      }));
      found = (get().messagesByAgent[agentId] || []).some((message) => message.id === targetId);
      if (olderMessages.length === 0) break;
    }

    if (found) {
      window.dispatchEvent(new CustomEvent("xiaomei:focus-search-message", {
        detail: { messageKey: targetId },
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

  refreshAssignments: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    set(produce((s: CoreState) => {
      s.assignmentLoadingByAgent[agentId] = true;
      s.assignmentErrorByAgent[agentId] = "";
    }));
    try {
      const response = await window.gateway.listAssignments({ agentId, status: "all", limit: 100 });
      if (response.error) throw new Error(response.error.message);
      const rows = Array.isArray(response.result?.assignments) ? response.result.assignments : [];
      const assignments = rows
        .map(assignmentSnapshot)
        .filter((item): item is AssignmentSnapshot => item !== null)
        .sort((left, right) => right.updatedAt - left.updatedAt);
      set(produce((s: CoreState) => {
        s.assignmentsByAgent[agentId] = assignments;
        s.assignmentLoadingByAgent[agentId] = false;
        s.assignmentErrorByAgent[agentId] = "";
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.assignmentLoadingByAgent[agentId] = false;
        s.assignmentErrorByAgent[agentId] = String(error);
      }));
    }
  },

  refreshCurrentProject: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    const sessionId = get().activeSessionByAgent[agentId];
    if (!sessionId) {
      set(produce((s: CoreState) => {
        s.currentProjectByAgent[agentId] = null;
        s.projectLoadingByAgent[agentId] = false;
        s.projectErrorByAgent[agentId] = "";
      }));
      return;
    }
    set(produce((s: CoreState) => {
      s.projectLoadingByAgent[agentId] = true;
      s.projectErrorByAgent[agentId] = "";
    }));
    try {
      const response = await window.gateway.getCurrentProject({ agentId, sessionId });
      if (response.error) throw new Error(response.error.message);
      const detail = response.result?.project ? projectDetailSnapshot(response.result) : null;
      set(produce((s: CoreState) => {
        if (s.activeSessionByAgent[agentId] !== sessionId) return;
        const previous = s.currentProjectByAgent[agentId];
        if (
          detail
          && previous?.project.id === detail.project.id
          && previous.project.revision > detail.project.revision
        ) return;
        if (
          detail
          && previous?.project.id === detail.project.id
          && previous.process
          && (!detail.process || previous.process.revision > detail.process.revision)
        ) {
          detail.process = previous.process;
        }
        s.currentProjectByAgent[agentId] = detail;
        s.projectLoadingByAgent[agentId] = false;
        s.projectErrorByAgent[agentId] = "";
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.projectLoadingByAgent[agentId] = false;
        s.projectErrorByAgent[agentId] = String(error);
      }));
    }
  },

  refreshActivities: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    set(produce((s: CoreState) => {
      s.activityLoadingByAgent[agentId] = true;
      s.activityErrorByAgent[agentId] = "";
    }));
    try {
      const response = await window.gateway.listActivities({
        agentId,
        status: "all",
        category: "all",
        limit: 100,
      });
      if (response.error) throw new Error(response.error.message);
      const rows = Array.isArray(response.result?.activities) ? response.result.activities : [];
      const activities = rows
        .map(activitySnapshot)
        .filter((item): item is ActivitySnapshot => item !== null)
        .sort((left, right) => right.updatedAt - left.updatedAt);
      set(produce((s: CoreState) => {
        s.activitiesByAgent[agentId] = activities;
        s.activityLoadingByAgent[agentId] = false;
        s.activityErrorByAgent[agentId] = "";
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.activityLoadingByAgent[agentId] = false;
        s.activityErrorByAgent[agentId] = String(error);
      }));
    }
  },

  refreshArtifacts: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    set(produce((s: CoreState) => {
      s.artifactLoadingByAgent[agentId] = true;
      s.artifactErrorByAgent[agentId] = "";
    }));
    try {
      const response = await window.gateway.listArtifacts({ agentId, limit: 100, offset: 0 });
      if (response.error) throw new Error(response.error.message);
      const rows = Array.isArray(response.result?.artifacts) ? response.result.artifacts : [];
      const artifacts = rows
        .map(artifactSnapshot)
        .filter((item): item is ArtifactSnapshot => item !== null);
      set(produce((s: CoreState) => {
        s.artifactsByAgent[agentId] = artifacts;
        s.artifactLoadingByAgent[agentId] = false;
        s.artifactErrorByAgent[agentId] = "";
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.artifactLoadingByAgent[agentId] = false;
        s.artifactErrorByAgent[agentId] = String(error);
      }));
    }
  },

  refreshPersonMemories: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    set(produce((s: CoreState) => {
      const previous = s.personMemoryListByAgent[agentId];
      s.personMemoryListByAgent[agentId] = {
        loading: true,
        loadingMore: false,
        hasMore: previous?.hasMore ?? false,
        nextOffset: previous?.nextOffset ?? null,
        error: "",
      };
    }));
    try {
      const response = await window.gateway.listMemories({ agentId, limit: 30, offset: 0 });
      if (response.error) throw new Error(response.error.message);
      const shortRows = Array.isArray(response.result?.short_term_memories)
        ? response.result.short_term_memories
        : [];
      const longRows = Array.isArray(response.result?.memories) ? response.result.memories : [];
      const rows = [...shortRows, ...longRows];
      const memories = rows
        .map(personMemorySnapshot)
        .filter((item): item is PersonMemorySnapshot => item !== null);
      set(produce((s: CoreState) => {
        s.personMemoriesByAgent[agentId] = memories;
        s.personMemoryListByAgent[agentId] = {
          loading: false,
          loadingMore: false,
          hasMore: response.result?.has_more === true,
          nextOffset: typeof response.result?.next_offset === "number"
            ? response.result.next_offset
            : null,
          error: "",
        };
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        const previous = s.personMemoryListByAgent[agentId];
        s.personMemoryListByAgent[agentId] = {
          loading: false,
          loadingMore: false,
          hasMore: previous?.hasMore ?? false,
          nextOffset: previous?.nextOffset ?? null,
          error: String(error),
        };
      }));
    }
  },

  loadMorePersonMemories: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    const page = agentId ? get().personMemoryListByAgent[agentId] : undefined;
    if (
      !agentId
      || get().connectionByAgent[agentId]?.status !== "connected"
      || !page?.hasMore
      || page.loading
      || page.loadingMore
      || page.nextOffset === null
    ) return;
    set(produce((s: CoreState) => {
      s.personMemoryListByAgent[agentId].loadingMore = true;
      s.personMemoryListByAgent[agentId].error = "";
    }));
    try {
      const response = await window.gateway.listMemories({
        agentId,
        limit: 30,
        offset: page.nextOffset,
      });
      if (response.error) throw new Error(response.error.message);
      const rows = Array.isArray(response.result?.memories) ? response.result.memories : [];
      const incoming = rows
        .map(personMemorySnapshot)
        .filter((item): item is PersonMemorySnapshot => item !== null);
      set(produce((s: CoreState) => {
        const existing = s.personMemoriesByAgent[agentId] || [];
        const known = new Set(existing.map((item) => item.id));
        s.personMemoriesByAgent[agentId] = [
          ...existing,
          ...incoming.filter((item) => !known.has(item.id)),
        ];
        s.personMemoryListByAgent[agentId] = {
          loading: false,
          loadingMore: false,
          hasMore: response.result?.has_more === true,
          nextOffset: typeof response.result?.next_offset === "number"
            ? response.result.next_offset
            : null,
          error: "",
        };
      }));
    } catch (error) {
      set(produce((s: CoreState) => {
        s.personMemoryListByAgent[agentId].loadingMore = false;
        s.personMemoryListByAgent[agentId].error = String(error);
      }));
    }
  },

  refreshAgentState: async (requestedAgentId) => {
    const agentId = requestedAgentId || get().activeAgentId;
    if (!agentId || get().connectionByAgent[agentId]?.status !== "connected") return;
    try {
      const response = await window.gateway.getAgentState({ agentId });
      if (response.error) throw new Error(response.error.message);
      const state = agentStateSnapshot(response.result?.state);
      if (!state) return;
      set(produce((s: CoreState) => {
        s.agentStateByAgent[agentId] = state;
      }));
    } catch {
      // State is supplementary; an older Agent must not break conversation.
    }
  },

  requestAssignmentCancel: async (assignmentId, reason = "") => {
    const agentId = get().activeAgentId;
    const assignment = agentId
      ? (get().assignmentsByAgent[agentId] || []).find((item) => item.id === assignmentId)
      : undefined;
    if (!agentId || !assignment) return i18n.t("storeUi.assignmentMissing");
    const response = await window.gateway.requestAssignmentCancel({
      agentId,
      assignmentId,
      reason,
      expectedRevision: assignment.revision,
    });
    if (response.error) return response.error.message;
    const updated = assignmentSnapshot(response.result?.assignment);
    if (updated) set(produce((s: CoreState) => { upsertAssignment(s, agentId, updated); }));
    return "";
  },

  requestAssignmentResume: async (assignmentId, responseText = "", decision) => {
    const agentId = get().activeAgentId;
    const assignment = agentId
      ? (get().assignmentsByAgent[agentId] || []).find((item) => item.id === assignmentId)
      : undefined;
    if (!agentId || !assignment) return i18n.t("storeUi.assignmentMissing");
    const response = await window.gateway.requestAssignmentResume({
      agentId,
      assignmentId,
      response: responseText,
      decision,
      expectedRevision: assignment.revision,
    });
    if (response.error) return response.error.message;
    const updated = assignmentSnapshot(response.result?.assignment);
    if (updated) set(produce((s: CoreState) => { upsertAssignment(s, agentId, updated); }));
    return "";
  },

  setPage: (page) => set(produce((s: CoreState) => { s.page = page; })),
  setTerminalOpen: (open) => set(produce((s: CoreState) => {
    s.terminalOpen = open;
    s.terminalAgentId = null;
  })),
  openAgentLogs: (agentId) => set(produce((s: CoreState) => {
    s.terminalAgentId = agentId;
    s.terminalOpen = true;
  })),
  setActiveNav: (nav) => set(produce((s: CoreState) => { s.activeNav = nav; })),
  clearUnread: (agentId) => set(produce((s: CoreState) => { s.unreadByAgent[agentId] = 0; })),
}));

// Persist connection and session selections to localStorage. Identity secrets
// live exclusively in the Electron main-process vault.
useCoreStore.subscribe((state) => savePersisted(state));

// ── Gateway event handler ──

type GatewayEventRegistry = typeof globalThis & {
  __xiaomeiGatewayEventsCleanup?: () => void;
};

export function initGatewayEvents(): () => void {
  // Vite HMR recreates this module without recreating the renderer window.
  // Keep ownership on globalThis so a refreshed module can dispose the
  // previous listener before registering its replacement.
  const registry = globalThis as GatewayEventRegistry;
  registry.__xiaomeiGatewayEventsCleanup?.();

  const disposeNotificationSelect = window.notifications.onSelect((target) => {
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

  const disposeGatewayEvent = window.gateway.onEvent((raw: {
    event: string;
    data: unknown;
    agentId: string;
    sequence?: number;
    timestamp?: number;
  }) => {
    const { event, data: rawData, agentId } = raw;
    const d = (rawData || {}) as Record<string, unknown>;
    const text = (d.text || "") as string;
    const store = useCoreStore.getState;
    const setState = useCoreStore.setState;

    if (!agentId) return;

    if (event === "embodiment.command.requested") {
      const commandId = typeof d.command_id === "string" ? d.command_id : "";
      const command = typeof d.command === "string" ? d.command : "";
      const embodimentId = typeof d.embodiment_id === "string" ? d.embodiment_id : "";
      const sessionId = typeof d.session_id === "string" ? d.session_id : "";
      const commandArguments = d.arguments && typeof d.arguments === "object" && !Array.isArray(d.arguments)
        ? d.arguments as Record<string, unknown>
        : {};
      if (!commandId || !command || !embodimentId || !sessionId) return;
      void executeEmbodimentCommand({
        commandId,
        embodimentId,
        command,
        arguments: commandArguments,
        agentId,
        sessionId,
      }).then((response) => window.gateway.respondEmbodimentCommand({
        agentId,
        commandId,
        status: response.status,
        result: response.result,
        error: response.error,
      })).catch((error) => {
        console.error("[embodiment] command response failed", error);
      });
      return;
    }

    if (event === "process.updated") {
      const process = projectProcessSnapshot(d.process);
      const current = store().currentProjectByAgent[agentId];
      if (process && current?.project.id === process.projectId) {
        setState(produce((s: CoreState) => {
          const detail = s.currentProjectByAgent[agentId];
          if (!detail || detail.project.id !== process.projectId) return;
          if (detail.process && detail.process.revision > process.revision) return;
          detail.process = process;
        }));
      } else {
        void store().refreshCurrentProject(agentId);
      }
      return;
    }

    if (event === "project.created" || event === "project.updated") {
      void store().refreshCurrentProject(agentId);
      return;
    }

    if (event.startsWith("activity.")) {
      const activity = activitySnapshot(d.activity);
      if (!activity) return;
      setState(produce((s: CoreState) => {
        upsertActivity(s, agentId, activity);
      }));
      return;
    }

    if (event === "agent.state.changed") {
      const state = agentStateSnapshot(d.state);
      if (!state) return;
      setState(produce((s: CoreState) => {
        if (state.relationship === undefined) {
          state.relationship = s.agentStateByAgent[agentId]?.relationship;
        }
        s.agentStateByAgent[agentId] = state;
      }));
      return;
    }

    if (event === "agent.speech.started") {
      setState(produce((s: CoreState) => {
        s.speakingByAgent[agentId] = {
          body: String(d.body || "local"),
          startedAt: typeof raw.timestamp === "number" ? raw.timestamp : Date.now(),
        };
      }));
      return;
    }

    if (event === "agent.speech.completed") {
      setState(produce((s: CoreState) => {
        delete s.speakingByAgent[agentId];
      }));
      return;
    }

    if (event === "assignment.changed" || event === "assignment.progress") {
      const assignment = assignmentSnapshot(d);
      if (!assignment) return;
      const deliverables = Array.isArray(d.deliverables)
        ? d.deliverables.flatMap((value) => {
            const artifact = displayArtifact(value);
            return artifact ? [artifact] : [];
          })
        : [];
      let changed = false;
      setState(produce((s: CoreState) => {
        changed = upsertAssignment(s, agentId, assignment);
        if (assignment.status === "completed" && assignment.originSessionId) {
          const sessionMessages = messagesForSession(s, agentId, assignment.originSessionId);
          for (const artifact of deliverables) {
            if (sessionMessages.some((message) => message.artifact?.id === artifact.id)) continue;
            sessionMessages.push({
              id: `assignment-artifact-${assignment.id}-${artifact.id}`,
              role: "agent",
              content: "",
              streaming: false,
              artifact,
            });
          }
        }
        if (changed && agentId !== s.activeAgentId) {
          s.unreadByAgent[agentId] = (s.unreadByAgent[agentId] || 0) + 1;
        }
      }));
      if (changed && ["waiting_person", "completed", "failed"].includes(assignment.status)) {
        const state = store();
        const agent = state.agents.find((entry) => entry.id === agentId);
        const agentName = state.connectionByAgent[agentId]?.agentName || agent?.name || "Agent";
        const body = assignment.status === "waiting_person"
          ? assignment.waitingReason || i18n.t("storeUi.waitingReply", { title: assignment.title })
          : assignment.progressSummary || assignment.terminalReason || assignment.title;
        void window.notifications.show({
          title: `${agentName} · ${assignment.title}`,
          body,
          agentId,
          sessionId: assignment.originSessionId,
        }).catch(() => {});
      }
      return;
    }

    const eventSessionId = typeof d.session_id === "string" && d.session_id
      ? d.session_id
      : store().activeSessionByAgent[agentId] || "";
    const eventTurnId = typeof d.turn_id === "string" ? d.turn_id : "";
    const eventMessages = (state: CoreState) => messagesForSession(state, agentId, eventSessionId);
    const readEventMessages = (state: CoreState) => readMessagesForSession(state, agentId, eventSessionId);
    const activeStreamKey = streamingKey(agentId, eventSessionId, eventTurnId);
    if (!_streamingByTurn[activeStreamKey]) {
      _streamingByTurn[activeStreamKey] = { ref: "", id: null };
    }
    const stream = _streamingByTurn[activeStreamKey];
    const cancelPendingStreamRender = () => {
      const timer = _streamRenderTimers[activeStreamKey];
      if (timer === undefined) return;
      window.clearTimeout(timer);
      delete _streamRenderTimers[activeStreamKey];
    };
    const flushStreamToStore = () => {
      cancelPendingStreamRender();
      if (!stream.ref.trim()) return;
      if (!stream.id) {
        stream.id = `streaming-${eventTurnId || Date.now()}-${Date.now()}`;
        setState(produce((s: CoreState) => {
          eventMessages(s).push({
            id: stream.id!, role: "agent", content: stream.ref, streaming: true,
            turnId: eventTurnId || undefined,
            responsePhase: responsePhaseForStream(stream.ref),
          });
        }));
        return;
      }
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        const message = sessionMessages.find((item) => item.id === stream.id);
        if (message) {
          message.content = stream.ref;
          message.responsePhase = responsePhaseForStream(stream.ref);
        }
      }));
    };

    if (event === "embodiment.audio.input.completed") {
      if (d.voiceprint_verified === true) {
        window.dispatchEvent(new CustomEvent("xiaomei:desktop-biometric-verified", {
          detail: { kind: "voiceprint", agentId },
        }));
      }
      // A spoken Clarify answer resumes the existing Turn and is rendered by
      // interaction.updated. It is not a second user message or a new Turn.
      if (d.disposition === "interaction_response") return;
      if (d.status !== "completed" || !text.trim()) return;
      const messageId = typeof d.message_id === "number" ? d.message_id : undefined;
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        const duplicate = sessionMessages.some((message) => (
          message.role === "user"
          && ((messageId !== undefined && message.sourceMessageId === messageId)
            || (eventTurnId && message.turnId === eventTurnId))
        ));
        if (duplicate) return;
        sessionMessages.push({
          id: messageId !== undefined
            ? `voice-user-${messageId}`
            : `voice-user-${eventTurnId || Date.now()}`,
          role: "user",
          content: text,
          streaming: false,
          createdAt: typeof raw.timestamp === "number" ? raw.timestamp : Date.now(),
          attachments: displayAttachments(d.attachments),
          turnId: eventTurnId || undefined,
          sourceMessageId: messageId,
          deliveryStatus: "processing",
        });
        touchSession(s, agentId, eventSessionId, 1, text);
        setSessionSending(s, agentId, eventSessionId, true);
      }));
      return;
    }

    if (event === "reconnecting") {
      setState(produce((s: CoreState) => {
        const previous = s.connectionByAgent[agentId];
        s.connectionByAgent[agentId] = {
          status: "connecting",
          agentName: previous?.agentName || "",
          error: "",
        };
      }));
      const agent = store().agents.find((entry) => entry.id === agentId);
      if (agent?.source === "local") void store().refreshLocalAgents();
      return;
    }

    if (event === "reconnected" || event === "stream.resynced") {
      const sessionId = typeof d.session_id === "string" ? d.session_id : "";
      const resume = d.resume && typeof d.resume === "object"
        ? d.resume as Record<string, unknown>
        : undefined;
      const messages = resumeMessages(resume, sessionId);
      if (event === "reconnected") clearAgentStreams(agentId);
      setState(produce((s: CoreState) => {
        if (event === "reconnected" || s.activeSessionByAgent[agentId] === sessionId) {
          const previous = s.connectionByAgent[agentId];
          s.connectionByAgent[agentId] = {
            status: "connected",
            agentName: (d.agent_name as string) || previous?.agentName || "",
            error: "",
          };
          if (s.agents.find((entry) => entry.id === agentId)?.source === "local") {
            s.localAvailabilityByAgent[agentId] = true;
          }
        }
        if (sessionId) {
          if (event === "reconnected") s.activeSessionByAgent[agentId] = sessionId;
          if (s.activeSessionByAgent[agentId] === sessionId) s.messagesByAgent[agentId] = messages;
          s.messagesByConversation[conversationStateKey(agentId, sessionId)] = messages;
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
        if (sessionId) {
          setSessionSending(
            s,
            agentId,
            sessionId,
            resume?.state === "running" || resume?.state === "waiting_user",
          );
        }
      }));
      restoreStreamFromResume(agentId, sessionId, resume);
      if (event === "reconnected") {
        // session.resume only restores the active conversation. Refresh the
        // authoritative list as well, otherwise an Agent process restart can
        // leave the sidebar containing only that resumed session.
        const fallbackSessions = store().sessionsByAgent[agentId] || [];
        void fetchAgentSessions(agentId, sessionId, messages, fallbackSessions)
          .then((sessionResult) => {
            setState(produce((s: CoreState) => {
              if (s.connectionByAgent[agentId]?.status !== "connected") return;
              s.sessionsByAgent[agentId] = sessionResult.sessions;
              s.sessionListByAgent[agentId] = sessionResult.listState;
            }));
          })
          .catch((error) => {
            setState(produce((s: CoreState) => {
              const current = s.sessionListByAgent[agentId];
              if (current) current.error = String(error);
            }));
          });
      }
      void useCoreStore.getState().refreshActivities(agentId);
      void useCoreStore.getState().refreshArtifacts(agentId);
      void useCoreStore.getState().refreshPersonMemories(agentId);
      void useCoreStore.getState().refreshAgentState(agentId);
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
      cancelPendingStreamRender();
      stream.ref = "";
      stream.id = pendingResponseId(eventTurnId);
      setState(produce((s: CoreState) => {
        setSessionSending(s, agentId, eventSessionId, true);
        const sessionMessages = eventMessages(s);
        const userMessage = [...sessionMessages]
          .reverse()
          .find((message) => message.role === "user" && (
            message.turnId === eventTurnId
            || (["queued", "processing"].includes(message.deliveryStatus || "")
              && !message.turnId)
          ));
        if (userMessage) {
          if (eventTurnId) userMessage.turnId = eventTurnId;
          userMessage.deliveryStatus = "processing";
        }
        const pending = sessionMessages.find((message) => (
          message.id === stream.id
          || (message.role === "agent"
            && message.turnId === eventTurnId
            && Boolean(message.responsePhase))
        )) || [...sessionMessages].reverse().find((message) => (
          message.role === "agent"
          && !message.turnId
          && Boolean(message.responsePhase)
        ));
        if (pending) {
          stream.id = pending.id;
          if (eventTurnId) pending.turnId = eventTurnId;
          pending.streaming = true;
          pending.responsePhase = "replying";
        } else {
          sessionMessages.push({
            id: stream.id!,
            role: "agent",
            content: "",
            streaming: true,
            createdAt: Date.now(),
            turnId: eventTurnId || undefined,
            responsePhase: "replying",
          });
        }
      }));
      return;
    }

    if (event === "capability.setup.requested") {
      const setup = capabilitySetupRequest(d, eventSessionId);
      if (!setup) return;
      flushStreamToStore();
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        if (sessionMessages.some((message) => message.capabilitySetup?.id === setup.id)) return;
        if (activeStreamId) {
          const activeIndex = sessionMessages.findIndex((message) => message.id === activeStreamId);
          const activeMessage = activeIndex >= 0 ? sessionMessages[activeIndex] : undefined;
          if (activeMessage && !stream.ref.trim() && activeMessage.responsePhase) {
            sessionMessages.splice(activeIndex, 1);
          } else if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
            activeMessage.responsePhase = undefined;
          }
        }
        sessionMessages.push({
          id: setup.id,
          role: "agent",
          content: "",
          streaming: false,
          createdAt: Date.now(),
          turnId: eventTurnId || undefined,
          capabilitySetup: setup,
        });
        if (s.activeSessionByAgent[agentId] !== eventSessionId) {
          const key = conversationStateKey(agentId, eventSessionId);
          s.unreadByConversation[key] = (s.unreadByConversation[key] || 0) + 1;
        }
        if (s.activeAgentId !== agentId) {
          s.unreadByAgent[agentId] = (s.unreadByAgent[agentId] || 0) + 1;
        }
        inserted = true;
      }));
      if (inserted && activeStreamId && stream.id === activeStreamId) {
        stream.id = null;
        stream.ref = "";
      }
      return;
    }

    if (event === "capability.setup.updated") {
      const requestId = typeof d.id === "string" ? d.id : "";
      const resumeStatus = typeof d.resume_status === "string" ? d.resume_status : "";
      if (!requestId || !["pending", "resumed", "unavailable"].includes(resumeStatus)) return;
      setState(produce((s: CoreState) => {
        const message = eventMessages(s)
          .find((entry) => entry.capabilitySetup?.id === requestId);
        if (message?.capabilitySetup) {
          message.capabilitySetup.resumeStatus = resumeStatus as CapabilitySetupRequest["resumeStatus"];
        }
      }));
      return;
    }

    if (event === "action.proposed") {
      const actionId = typeof d.id === "string" ? d.id : "";
      const summary = typeof d.summary === "string" ? d.summary : "";
      if (!actionId || !summary) return;
      flushStreamToStore();
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        if (sessionMessages.some((message) => message.action?.id === actionId)) return;
        if (activeStreamId) {
          const activeIndex = sessionMessages.findIndex((message) => message.id === activeStreamId);
          const activeMessage = activeIndex >= 0 ? sessionMessages[activeIndex] : undefined;
          if (activeMessage && !stream.ref.trim() && activeMessage.responsePhase) {
            sessionMessages.splice(activeIndex, 1);
          } else if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
            activeMessage.responsePhase = undefined;
          }
        }
        sessionMessages.push({
          id: actionId,
          role: "agent",
          content: "",
          streaming: false,
          turnId: eventTurnId || undefined,
          action: actionRequest(d, eventSessionId, eventTurnId, "pending"),
        });
        if (s.activeSessionByAgent[agentId] !== eventSessionId) {
          const key = conversationStateKey(agentId, eventSessionId);
          s.unreadByConversation[key] = (s.unreadByConversation[key] || 0) + 1;
        }
        if (s.activeAgentId !== agentId) {
          s.unreadByAgent[agentId] = (s.unreadByAgent[agentId] || 0) + 1;
        }
        inserted = true;
      }));
      if (inserted && activeStreamId && stream.id === activeStreamId) {
        stream.id = null;
        stream.ref = "";
      }
      return;
    }

    if (event === "action.completed") {
      const actionId = typeof d.id === "string" ? d.id : "";
      if (!actionId) return;
      const rawStatus = typeof d.status === "string" ? d.status : "failed";
      const status = ["completed", "failed", "rejected", "cancelled", "expired"].includes(rawStatus)
        ? rawStatus as ActionRequest["status"]
        : "failed";
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        let message = sessionMessages
          .find((entry) => entry.action?.id === actionId);
        if (!message) {
          message = {
            id: actionId,
            role: "agent",
            content: "",
            streaming: false,
            turnId: eventTurnId || undefined,
            action: actionRequest(d, eventSessionId, eventTurnId, status),
          };
          sessionMessages.push(message);
        } else if (message.action) {
          message.action = actionRequest(d, eventSessionId, eventTurnId, status);
        }
      }));
      return;
    }

    if (event === "interaction.requested") {
      const payload = d;
      const requestId = typeof payload.id === "string" ? payload.id : "";
      const question = typeof payload.question === "string" ? payload.question : "";
      if (!requestId || !question) return;
      const choices = interactionChoices(payload.choices);
      flushStreamToStore();
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        if (sessionMessages.some((message) => message.interaction?.id === requestId)) return;

        // A tool call can happen in the middle of one ReAct stream. Close
        // any text emitted before the question so content produced after
        // the answer starts a new message below the interaction card.
        if (activeStreamId) {
          const activeIndex = sessionMessages.findIndex((message) => message.id === activeStreamId);
          const activeMessage = activeIndex >= 0 ? sessionMessages[activeIndex] : undefined;
          if (activeMessage && !stream.ref.trim() && activeMessage.responsePhase) {
            sessionMessages.splice(activeIndex, 1);
          } else if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
            activeMessage.responsePhase = undefined;
          }
        }
        sessionMessages.push({
          id: requestId,
          role: "agent",
          content: "",
          streaming: false,
          turnId: eventTurnId || undefined,
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
        if (s.activeSessionByAgent[agentId] !== eventSessionId) {
          const key = conversationStateKey(agentId, eventSessionId);
          s.unreadByConversation[key] = (s.unreadByConversation[key] || 0) + 1;
        }
        if (s.activeAgentId !== agentId) {
          s.unreadByAgent[agentId] = (s.unreadByAgent[agentId] || 0) + 1;
        }
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
      const response = interactionDisplayText(payload.response);
      if (!requestId) return;
      setState(produce((s: CoreState) => {
        const message = eventMessages(s)
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
      flushStreamToStore();
      const activeStreamId = stream.id;
      let inserted = false;
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        if (sessionMessages.some((message) => message.tool?.id === toolCallId)) return;
        if (activeStreamId) {
          const activeMessage = sessionMessages
            .find((message) => message.id === activeStreamId);
          if (activeMessage) {
            activeMessage.content = stream.ref;
            activeMessage.streaming = false;
          }
        }
        sessionMessages.push({
          id: `tool-${toolCallId}`,
          role: "agent",
          content: "",
          streaming: false,
          turnId: eventTurnId || undefined,
          tool: {
            id: toolCallId,
            name,
            arguments: args,
            status: "running",
            summary: "",
            truncated: false,
            error: "",
            startedAt: typeof d.started_at === "number" ? d.started_at : Date.now(),
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
        const sessionMessages = eventMessages(s);
        let message = sessionMessages
          .find((entry) => entry.tool?.id === toolCallId);
        if (!message) {
          message = {
            id: `tool-${toolCallId}`,
            role: "agent",
            content: "",
            streaming: false,
            turnId: eventTurnId || undefined,
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
          sessionMessages.push(message);
        }
        if (!message.tool) return;
        const completedAt = typeof d.completed_at === "number" ? d.completed_at : Date.now();
        message.tool.status = error ? "error" : "complete";
        message.tool.summary = summary;
        message.tool.truncated = d.truncated === true;
        message.tool.error = error;
        message.tool.completedAt = completedAt;
        if (typeof message.tool.startedAt === "number") {
          message.tool.durationMs = Math.max(0, completedAt - message.tool.startedAt);
        }
      }));
      return;
    }

    if (event === "artifact.created" || event === "artifact.updated") {
      const artifact = displayArtifact(d);
      if (!artifact) return;
      const snapshot = artifactSnapshot({
        ...d,
        session_id: typeof d.session_id === "string" ? d.session_id : eventSessionId,
        created_at: typeof d.created_at === "number"
          ? d.created_at
          : typeof raw.timestamp === "number" ? raw.timestamp / 1000 : Date.now() / 1000,
        updated_at: typeof d.updated_at === "number"
          ? d.updated_at
          : typeof raw.timestamp === "number" ? raw.timestamp / 1000 : Date.now() / 1000,
      });
      setState(produce((s: CoreState) => {
        if (snapshot) upsertArtifact(s, agentId, snapshot);
      }));
      return;
    }

    if (event === "artifact.presented") {
      const artifact = displayArtifact(d);
      if (!artifact) return;
      const snapshot = artifactSnapshot({
        ...d,
        session_id: typeof d.session_id === "string" ? d.session_id : eventSessionId,
        created_at: typeof d.created_at === "number"
          ? d.created_at
          : typeof raw.timestamp === "number" ? raw.timestamp / 1000 : Date.now() / 1000,
        updated_at: typeof d.updated_at === "number"
          ? d.updated_at
          : typeof raw.timestamp === "number" ? raw.timestamp / 1000 : Date.now() / 1000,
      });
      setState(produce((s: CoreState) => {
        if (snapshot) upsertArtifact(s, agentId, snapshot);
        const sessionMessages = eventMessages(s);
        const existingIndex = sessionMessages
          .findIndex((message) => message.artifact?.id === artifact.id);
        if (existingIndex >= 0) {
          const [existing] = sessionMessages.splice(existingIndex, 1);
          existing.artifact = artifact;
          existing.turnId = eventTurnId || artifact.turnId || existing.turnId;
          sessionMessages.push(existing);
          return;
        }
        sessionMessages.push({
          id: `artifact-${artifact.id}`,
          role: "agent",
          content: "",
          streaming: false,
          turnId: eventTurnId || artifact.turnId || undefined,
          artifact,
        });
      }));
      return;
    }

    // Internal cognition metadata has its own event and must never finalize
    // the visible assistant message stream.
    if (event === "internal.display" || event === "pong") return;

    if (event === "message.delta") {
      stream.ref += text;
      // Providers may emit hundreds of tiny chunks per second. Rendering and
      // parsing Markdown for each chunk can monopolize the Renderer thread, so
      // coalesce them into a bounded ~30 FPS UI stream.
      if (_streamRenderTimers[activeStreamKey] === undefined) {
        _streamRenderTimers[activeStreamKey] = window.setTimeout(
          flushStreamToStore,
          STREAM_RENDER_INTERVAL_MS,
        );
      }
    } else if (event === "message.complete") {
      flushStreamToStore();
      const status = typeof d.status === "string" ? d.status : "complete";
      const recalledMemories = memoryReferences(d.memory_references);
      const error = d.error && typeof d.error === "object"
        ? d.error as Record<string, unknown>
        : null;
      const terminalText = text || (status === "error"
        ? String(error?.message || i18n.t("storeUi.modelUnavailable"))
        : "");
      let retryMessageId: number | undefined;
      setState(produce((s: CoreState) => {
        const userMessage = [...eventMessages(s)]
          .reverse()
          .find((message) => message.role === "user" && message.turnId === eventTurnId);
        const terminalDeliveryStatus: DisplayMessage["deliveryStatus"] = status === "error"
          ? "failed"
          : status === "interrupted" ? "interrupted" : "completed";
        const terminalErrorCode = status === "error"
          ? String(error?.code || "")
          : "";
        const terminalErrorMessage = status === "error"
          ? String(error?.message || "Unknown error")
          : "";
        if (userMessage) {
          retryMessageId = userMessage.sourceMessageId;
          userMessage.deliveryStatus = terminalDeliveryStatus;
          userMessage.deliveryErrorCode = terminalErrorCode;
          userMessage.deliveryError = terminalErrorMessage;
        }
        for (const message of eventMessages(s)) {
          if (message.role !== "user" || message.steeredIntoTurnId !== eventTurnId) continue;
          message.deliveryStatus = terminalDeliveryStatus;
          message.deliveryErrorCode = terminalErrorCode;
          message.deliveryError = terminalErrorMessage;
        }
      }));
      let completedText = "";
      if (stream.id) {
        const finalText = stream.ref || terminalText;
        const streamingMessageExists = readEventMessages(store())
          .some((message) => (
            message.id === stream.id
            || (message.role === "agent"
              && message.turnId === eventTurnId
              && Boolean(message.streaming || message.responsePhase))
          ));
        if (streamingMessageExists) completedText = finalText;
        setState(produce((s: CoreState) => {
          const sessionMessages = eventMessages(s);
          let idx = sessionMessages.findIndex(m => m.id === stream.id);
          if (idx === -1 && eventTurnId) {
            idx = sessionMessages.findIndex((message) => (
              message.role === "agent"
              && message.turnId === eventTurnId
              && Boolean(message.streaming || message.responsePhase)
            ));
          }
          if (idx !== -1) {
            if (!finalText.trim()) {
              sessionMessages.splice(idx, 1);
            } else {
              sessionMessages[idx].content = finalText;
              sessionMessages[idx].streaming = false;
              sessionMessages[idx].responsePhase = undefined;
              sessionMessages[idx].memoryReferences = recalledMemories;
              sessionMessages[idx].serviceError =
                status === "error" && String(error?.code || "").startsWith("MODEL_")
                  ? {
                      code: String(error?.code || "MODEL_UNAVAILABLE"),
                      message: String(error?.message || finalText),
                      retryMessageId,
                    }
                  : undefined;
              touchSession(s, agentId, eventSessionId, 1);
            }
          }
        }));
        stream.id = null;
        stream.ref = "";
      } else if (terminalText.trim()) {
        // Skip a duplicate final message if the local stream already finalized it.
        const msgs = readEventMessages(store());
        const lastMsg = msgs && msgs.length > 0 ? msgs[msgs.length - 1] : null;
        const isDuplicate = lastMsg && lastMsg.role === "agent" && lastMsg.content === terminalText;
        if (isDuplicate) {
          setState(produce((s: CoreState) => {
            const sessionMessages = eventMessages(s);
            const current = sessionMessages[sessionMessages.length - 1];
            if (current) current.memoryReferences = recalledMemories;
          }));
        } else {
          completedText = terminalText;
          setState(produce((s: CoreState) => {
            eventMessages(s).push({
              id: "msg-" + Date.now(),
              role: "agent",
              content: terminalText,
              streaming: false,
              turnId: eventTurnId || undefined,
              memoryReferences: recalledMemories,
              serviceError: status === "error" && String(error?.code || "").startsWith("MODEL_")
                ? {
                    code: String(error?.code || "MODEL_UNAVAILABLE"),
                    message: String(error?.message || terminalText),
                    retryMessageId,
                  }
                : undefined,
            });
            touchSession(s, agentId, eventSessionId, 1);
          }));
        }
      }
      setState(produce((s: CoreState) => {
        const sessionMessages = eventMessages(s);
        for (let index = sessionMessages.length - 1; index >= 0; index -= 1) {
          const message = sessionMessages[index];
          if (
            message.role === "agent"
            && message.turnId === eventTurnId
            && !message.content.trim()
            && message.responsePhase
          ) {
            sessionMessages.splice(index, 1);
          }
        }
      }));
      delete _streamingByTurn[activeStreamKey];
      cancelPendingStreamRender();
      setState(produce((s: CoreState) => {
        setSessionSending(s, agentId, eventSessionId, false);
        const isBackgroundSession = s.activeSessionByAgent[agentId] !== eventSessionId;
        if (completedText && isBackgroundSession) {
          const key = conversationStateKey(agentId, eventSessionId);
          s.unreadByConversation[key] = (s.unreadByConversation[key] || 0) + 1;
        }
        if (completedText && agentId !== s.activeAgentId) {
          s.unreadByAgent[agentId] = (s.unreadByAgent[agentId] || 0) + 1;
        }
      }));
      if (completedText) {
        const state = store();
        window.setTimeout(() => {
          if (store().speakingByAgent[agentId]) return;
          void playMessageSound();
        }, 160);
        const agent = state.agents.find((entry) => entry.id === agentId);
        const agentName = state.connectionByAgent[agentId]?.agentName || agent?.name || "Agent";
        const summary = publicResponseText(terminalText || completedText).replace(/\s+/g, " ");
        if (summary) {
          void window.notifications.show({
            title: agentName,
            body: summary,
            agentId,
            sessionId: eventSessionId,
          }).catch(() => {});
        }
      }
    } else if (event === "error") {
      cancelPendingStreamRender();
      const err = (d.text || "Unknown error") as string;
      setState(produce((s: CoreState) => {
        eventMessages(s).push({
          id: "err-" + Date.now(), role: "agent", content: `Error: ${err}`, streaming: false,
        });
        setSessionSending(s, agentId, eventSessionId, false);
      }));
      stream.id = null;
      stream.ref = "";
    }
  });

  const cleanup = () => {
    disposeNotificationSelect();
    disposeGatewayEvent();
    if (registry.__xiaomeiGatewayEventsCleanup === cleanup) {
      delete registry.__xiaomeiGatewayEventsCleanup;
    }
  };
  registry.__xiaomeiGatewayEventsCleanup = cleanup;
  return cleanup;
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    const registry = globalThis as GatewayEventRegistry;
    registry.__xiaomeiGatewayEventsCleanup?.();
  });
}
