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
  description?: string;
  host: string;
  port: number;
  token: string;
  source?: "manual" | "local";
  localAgentId?: string;
}

export interface ChatAttachment {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  kind: "image" | "text" | "document";
  dataBase64?: string;
}

export interface AttachmentPickResult {
  attachments: ChatAttachment[];
  error?: string;
}

export interface LocalAgentInfo {
  agentId: string;
  name: string;
  description?: string;
  host: string;
  port: number;
  online: boolean;
  pid?: number;
  startedAt?: string;
}

export type AgentLifecycleAction = "start" | "stop" | "restart";

export interface AgentLifecycleResult {
  ok: boolean;
  action: AgentLifecycleAction;
  agentId: string;
  message: string;
  runtimeSource?: "environment" | "config" | "virtualenv" | "bundled" | "path";
}

export interface AgentCreationResult {
  ok: boolean;
  name: string;
  description: string;
  message: string;
  agentId?: string;
  port?: number;
  runtimeSource?: "environment" | "config" | "virtualenv" | "bundled" | "path";
}

// ── Session (conversation) entry ──

export interface SessionEntry {
  id: string;       // unique session id
  name: string;     // user-given name or auto date-based
  createdAt: number; // timestamp ms
  updatedAt?: number;
  messageCount?: number;
}

// ── Bridge API ──

export interface GatewayBridge {
  connect(args: { host: string; port: number; token: string; agentId: string; sessionId?: string }): Promise<JsonRpcResponse>;
  disconnect(args: { agentId: string }): Promise<void>;
  sendMessage(args: { content: string; agentId: string; clientRequestId: string; attachments: ChatAttachment[] }): Promise<JsonRpcResponse>;
  pickAttachments(): Promise<AttachmentPickResult>;
  getAttachment(args: { agentId: string; sessionId: string; attachmentId: string }): Promise<JsonRpcResponse>;
  openAttachment(args: { agentId: string; sessionId: string; attachmentId: string }): Promise<{ ok: boolean; error?: string }>;
  getArtifact(args: { agentId: string; sessionId: string; artifactId: string }): Promise<JsonRpcResponse>;
  listArtifacts(args: { agentId: string; limit?: number; offset?: number }): Promise<JsonRpcResponse>;
  listMemories(args: { agentId: string; limit?: number; offset?: number }): Promise<JsonRpcResponse>;
  openArtifact(args: { agentId: string; sessionId: string; artifactId: string }): Promise<{ ok: boolean; error?: string }>;
  abortMessage(args: { agentId: string }): Promise<JsonRpcResponse>;
  retryMessage(args: { agentId: string; sessionId: string; messageId: number; clientRequestId: string }): Promise<JsonRpcResponse>;
  respondInteraction(args: { agentId: string; requestId: string; turnId: string; response: string }): Promise<JsonRpcResponse>;
  respondAction(args: { agentId: string; actionId: string; turnId: string; decision: "allow" | "deny" }): Promise<JsonRpcResponse>;
  getHistory(args: { sessionId?: string; limit?: number; beforeId?: number; agentId: string }): Promise<JsonRpcResponse>;
  listSessions(args: { limit?: number; offset?: number; query?: string; agentId: string }): Promise<JsonRpcResponse>;
  listAssignments(args: { agentId: string; status?: string; limit?: number }): Promise<JsonRpcResponse>;
  getAssignment(args: { agentId: string; assignmentId: string; eventLimit?: number }): Promise<JsonRpcResponse>;
  listActivities(args: {
    agentId: string;
    status?: string;
    category?: string;
    limit?: number;
    offset?: number;
  }): Promise<JsonRpcResponse>;
  getActivity(args: { agentId: string; activityId: string }): Promise<JsonRpcResponse>;
  getAgentState(args: { agentId: string }): Promise<JsonRpcResponse>;
  openAssignmentArtifact(args: {
    agentId: string;
    assignmentId: string;
    artifactId: string;
  }): Promise<{ ok: boolean; error?: string }>;
  requestAssignmentCancel(args: {
    agentId: string;
    assignmentId: string;
    reason?: string;
    expectedRevision?: number;
  }): Promise<JsonRpcResponse>;
  requestAssignmentResume(args: {
    agentId: string;
    assignmentId: string;
    response?: string;
    decision?: "approve" | "deny";
    expectedRevision?: number;
  }): Promise<JsonRpcResponse>;
  listIdentities(args: { agentId: string }): Promise<JsonRpcResponse>;
  listLegacySessions(args: { agentId: string }): Promise<JsonRpcResponse>;
  claimLegacySession(args: { agentId: string; sessionId: string }): Promise<JsonRpcResponse>;
  getChannelConfig(args: { agentId: string; channel: "feishu" | "dingtalk" }): Promise<JsonRpcResponse>;
  testChannel(args: { agentId: string; channel: "feishu" | "dingtalk"; appId: string; appSecret: string }): Promise<JsonRpcResponse>;
  configureChannel(args: {
    agentId: string;
    channel: "feishu" | "dingtalk";
    appId: string;
    appSecret: string;
    displayName: string;
    accountId?: string;
  }): Promise<JsonRpcResponse>;
  getChannelStatus(args: { agentId: string; channel: "feishu" | "dingtalk" }): Promise<JsonRpcResponse>;
  removeChannel(args: { agentId: string; channel: "feishu" | "dingtalk" }): Promise<JsonRpcResponse>;
  beginIdentityLink(args: { agentId: string; provider: "feishu" | "dingtalk" }): Promise<JsonRpcResponse>;
  getIdentityLinkStatus(args: { agentId: string; requestId: string }): Promise<JsonRpcResponse>;
  cancelIdentityLink(args: { agentId: string; requestId: string }): Promise<JsonRpcResponse>;
  listIdentityLinks(args: { agentId: string; provider: "feishu" | "dingtalk" }): Promise<JsonRpcResponse>;
  revokeIdentityLink(args: {
    agentId: string;
    provider: "feishu" | "dingtalk";
    bindingId: string;
  }): Promise<JsonRpcResponse>;
  getConfig(key: string): Promise<string | null>;

  /**
   * Subscribe to gateway push events. Callback receives { event, data, agentId }.
   */
  onEvent(callback: (raw: {
    event: string;
    data: unknown;
    agentId: string;
    sequence?: number;
    timestamp?: number;
  }) => void): () => void;
}

export interface IdentityStatus {
  exists: boolean;
  unlocked: boolean;
  displayName?: string;
  issuer?: string;
  subject?: string;
  error?: string;
}

export interface IdentityOperationResult {
  ok: boolean;
  status?: IdentityStatus;
  error?: string;
  canceled?: boolean;
}

export interface IdentityBridge {
  status(): Promise<IdentityStatus>;
  create(args: { displayName: string; password: string }): Promise<IdentityOperationResult>;
  unlock(args: { password: string }): Promise<IdentityOperationResult>;
  lock(): Promise<IdentityStatus>;
  changePassword(args: { currentPassword: string; newPassword: string }): Promise<IdentityOperationResult>;
  exportBackup(): Promise<IdentityOperationResult>;
  importBackup(args: { password: string }): Promise<IdentityOperationResult>;
}

export interface LocalAgentsBridge {
  discover(): Promise<LocalAgentInfo[]>;
  create(args: { name: string; description: string }): Promise<AgentCreationResult>;
  control(args: { agentId: string; connectionId: string; action: AgentLifecycleAction }): Promise<AgentLifecycleResult>;
}

export interface NotificationsBridge {
  show(args: { title: string; body: string; agentId: string; sessionId: string }): Promise<{ shown: boolean }>;
  onSelect(callback: (target: { agentId: string; sessionId: string }) => void): () => void;
}

export interface DesktopInfo {
  version: string;
  environment: "development" | "production";
  platform: string;
  arch: string;
  electronVersion: string;
  nodeVersion: string;
  configDirectory: string;
  agentDirectory: string;
  logDirectory: string;
  logFile: string;
}

export interface DirectoryOpenResult {
  ok: boolean;
  error?: string;
}

export interface DesktopBridge {
  getInfo(): Promise<DesktopInfo>;
  readLog(): Promise<{ content: string }>;
  openLogDirectory(): Promise<DirectoryOpenResult>;
  openConfigDirectory(): Promise<DirectoryOpenResult>;
  openExternal(url: string): Promise<DirectoryOpenResult>;
}

export interface WinBridge {
  minimize(): void;
  maximize(): void;
  close(): void;
  isMaximized(): Promise<boolean>;
  onMaximizeChange(callback: (maximized: boolean) => void): void;
}

export interface TerminalBridge {
  spawn(args: {
    cols: number;
    rows: number;
    mode?: "shell" | "agent-logs";
    agentId?: string;
  }): Promise<{ id?: string; shell?: string; cwd?: string; error?: string }>;
  write(data: string): Promise<void>;
  resize(args: { cols: number; rows: number }): Promise<void>;
  dispose(): Promise<void>;
  onData(callback: (data: string) => void): () => void;
  onExit(callback: (code: number) => void): () => void;
}

declare global {
  interface Window {
    gateway: GatewayBridge;
    identity: IdentityBridge;
    localAgents: LocalAgentsBridge;
    notifications: NotificationsBridge;
    desktop: DesktopBridge;
    win: WinBridge;
    terminal: TerminalBridge;
  }
}
