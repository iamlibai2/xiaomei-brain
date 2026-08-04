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
  kind: "image" | "text" | "document" | "video";
  dataBase64?: string;
}

export interface ArtifactTextSelection {
  kind: "text";
  page?: number;
  selectedText: string;
  contextBefore?: string;
  contextAfter?: string;
}

export interface ArtifactSpreadsheetSelection {
  kind: "spreadsheet";
  sheet: string;
  range: string;
  selectedText: string;
}

export interface ArtifactHtmlSelection {
  kind: "html";
  selector: string;
  tag: string;
  selectedText: string;
  outerHtml: string;
  contextBefore?: string;
  contextAfter?: string;
}

export type ArtifactSelection = ArtifactTextSelection | ArtifactSpreadsheetSelection | ArtifactHtmlSelection;

export interface ChatArtifactReference {
  artifactId: string;
  sessionId: string;
  selection?: ArtifactSelection;
  // Renderer-only presentation fields; Electron sends only Agent-owned IDs
  // and the structured selection to Gateway.
  name?: string;
  mimeType?: string;
  size?: number;
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

export interface ModelDefinition {
  id: string;
  name: string;
  context_window: number;
  max_tokens: number;
  reasoning: boolean;
  thinking_toggle: boolean;
  thinking_efforts: ThinkingEffort[];
  thinking_default_enabled: boolean;
  thinking_default_effort: ThinkingEffort;
  requires_reasoning_content_for_tools: boolean;
  supports_tools: boolean;
  input_modes: string[];
  supports_vision: boolean;
}

export type ThinkingEffort = "default" | "low" | "medium" | "high" | "max";

export interface ModelThinkingSelection {
  enabled: boolean;
  effort: ThinkingEffort;
}

export interface ModelProviderConfig {
  id: string;
  base_url: string;
  api_mode: string;
  secret_configured: boolean;
  secret_hint: string;
  models: ModelDefinition[];
}

export interface ModelConfigSnapshot {
  agent_id: string;
  selection: {
    primary: string;
    vision: string;
    thinking: Partial<ModelThinkingSelection>;
  };
  active: {
    primary: string;
    vision: string;
    thinking: Partial<ModelThinkingSelection>;
  };
  providers: ModelProviderConfig[];
  hashes: { global: string; agent: string };
}

export type MediaCapability = "image" | "tts" | "music" | "video";

export interface MediaServiceField {
  key: string;
  label: string;
  type: "secret" | "text" | "number" | "boolean" | "select";
  required: boolean;
  advanced: boolean;
  default?: string | number | boolean;
  options?: string[];
  minimum?: number;
  maximum?: number;
  step?: number;
}

export interface MediaServiceConfig {
  id: string;
  name: string;
  plugin: string;
  capability: MediaCapability;
  vendor: string;
  configured: boolean;
  enabled: boolean;
  secret_configured: boolean;
  secret_hint: string;
  restart_required: boolean;
  connection_kind: "remote" | "local" | "hybrid";
  fields: MediaServiceField[];
  values: Record<string, string | number | boolean | null>;
}

export interface MediaRuntimeToolStatus {
  id: "ffmpeg" | "ffprobe";
  name: string;
  available: boolean;
  version: string;
  path: string;
  error: string;
}

export interface MediaRuntimeStatus {
  ready: boolean;
  tools: MediaRuntimeToolStatus[];
}

export type ToolServiceCapability = "web_search";

export interface ToolServiceConfig {
  id: string;
  name: string;
  plugin: string;
  capability: ToolServiceCapability;
  vendor: string;
  configured: boolean;
  enabled: boolean;
  secret_configured: boolean;
  secret_hint: string;
  restart_required: boolean;
  fields: MediaServiceField[];
  values: Record<string, string | number | boolean | null>;
}

export type CapabilityStatus =
  | "not_acquired"
  | "disabled"
  | "preparing"
  | "needs_setup"
  | "ready"
  | "degraded"
  | "unavailable"
  | "error";

export interface CapabilityOutcome {
  id: string;
  name: string;
  description: string;
  available: boolean;
  limitations: string[];
}

export interface AgentCapability {
  id: string;
  name: string;
  summary: string;
  category: string;
  status: CapabilityStatus;
  enabled: boolean;
  outcomes: CapabilityOutcome[];
  examples: string[];
  issues: Array<{
    code: string;
    message: string;
    action?: {
      type: "open_settings";
      section: string;
      target: string;
      label: string;
    };
  }>;
  actions: Array<{
    type: "open_settings";
    section: string;
    target: string;
    label: string;
  }>;
  version: string;
  source: string;
}

export interface CapabilityPackageInspection {
  valid: boolean;
  file_name: string;
  archive_size: number;
  sha256: string;
  entry_count?: number;
  uncompressed_size?: number;
  errors: string[];
  warnings: string[];
  manifest?: {
    schema_version: number;
    package: {
      id: string;
      name: string;
      version: string;
      description: string;
      publisher: string;
      license: string;
    };
    capabilities: Array<{ id: string; name: string; summary: string }>;
    permissions: Array<{ category: string; value: string }>;
    requirements: {
      xiaomei_brain: string;
      python: string;
      python_packages: string[];
      node_packages: string[];
      executables: string[];
    };
    contents: Record<string, string[]>;
  };
}

export interface InstalledCapabilityPackage {
  id: string;
  name: string;
  version: string;
  sha256: string;
  publisher: string;
  description: string;
  installed_at: number;
  active: boolean;
  runtime_valid: boolean;
  issue: string;
  loaded: boolean;
  capabilities: Array<{ id: string; name: string; summary: string }>;
  permissions: Array<{ category: string; value: string }>;
  requirements: Record<string, unknown>;
}

// ── Bridge API ──

export interface GatewayBridge {
  connect(args: { host: string; port: number; token: string; agentId: string; sessionId?: string }): Promise<JsonRpcResponse>;
  switchSession(args: { agentId: string; sessionId: string }): Promise<JsonRpcResponse>;
  disconnect(args: { agentId: string }): Promise<void>;
  sendMessage(args: {
    content: string;
    agentId: string;
    sessionId: string;
    clientRequestId: string;
    attachments: ChatAttachment[];
    artifactReferences?: ChatArtifactReference[];
  }): Promise<JsonRpcResponse>;
  sendVoice(args: {
    agentId: string;
    dataBase64: string;
    mimeType: string;
    size: number;
    clientRequestId: string;
  }): Promise<JsonRpcResponse>;
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
  unifiedSearch(args: { agentId: string; query: string; limit?: number }): Promise<JsonRpcResponse>;
  listAssignments(args: { agentId: string; status?: string; limit?: number }): Promise<JsonRpcResponse>;
  getAssignment(args: { agentId: string; assignmentId: string; eventLimit?: number }): Promise<JsonRpcResponse>;
  listProjects(args: { agentId: string; status?: string; limit?: number }): Promise<JsonRpcResponse>;
  getProject(args: { agentId: string; projectId: string; eventLimit?: number }): Promise<JsonRpcResponse>;
  getCurrentProject(args: { agentId: string; sessionId: string }): Promise<JsonRpcResponse>;
  listActivities(args: {
    agentId: string;
    status?: string;
    category?: string;
    limit?: number;
    offset?: number;
  }): Promise<JsonRpcResponse>;
  getActivity(args: { agentId: string; activityId: string }): Promise<JsonRpcResponse>;
  getAgentState(args: { agentId: string }): Promise<JsonRpcResponse>;
  listCapabilities(args: { agentId: string }): Promise<JsonRpcResponse>;
  getCapability(args: { agentId: string; capabilityId: string }): Promise<JsonRpcResponse>;
  setCapabilityEnabled(args: {
    agentId: string;
    capabilityId: string;
    enabled: boolean;
  }): Promise<JsonRpcResponse>;
  inspectCapabilityPackage(args: { agentId: string }): Promise<JsonRpcResponse>;
  listCapabilityPackages(args: { agentId: string }): Promise<JsonRpcResponse>;
  installCapabilityPackage(args: { agentId: string; sha256: string }): Promise<JsonRpcResponse>;
  setCapabilityPackageActive(args: {
    agentId: string;
    packageId: string;
    version: string;
    sha256: string;
    active: boolean;
  }): Promise<JsonRpcResponse>;
  uninstallCapabilityPackage(args: {
    agentId: string;
    packageId: string;
  }): Promise<JsonRpcResponse>;
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
  getModelConfig(args: { agentId: string }): Promise<JsonRpcResponse>;
  getModelCatalog(args: { agentId: string; providerId?: string }): Promise<JsonRpcResponse>;
  testModelProvider(args: {
    agentId: string;
    providerId: string;
    baseUrl: string;
    apiKey: string;
    apiMode: string;
    modelId: string;
  }): Promise<JsonRpcResponse>;
  configureModelProvider(args: {
    agentId: string;
    providerId: string;
    baseUrl: string;
    apiKey: string;
    apiMode: string;
    models: ModelDefinition[];
    baseHash?: string;
  }): Promise<JsonRpcResponse>;
  removeModelProvider(args: {
    agentId: string;
    providerId: string;
    baseHash?: string;
  }): Promise<JsonRpcResponse>;
  setModelSelection(args: {
    agentId: string;
    primary: string;
    vision?: string;
    thinking?: ModelThinkingSelection;
    baseHash?: string;
  }): Promise<JsonRpcResponse>;
  listMediaServices(args: {
    agentId: string;
    capability?: MediaCapability;
  }): Promise<JsonRpcResponse>;
  getMediaRuntimeStatus(args: {
    agentId: string;
  }): Promise<JsonRpcResponse>;
  getMediaService(args: {
    agentId: string;
    serviceId: string;
  }): Promise<JsonRpcResponse>;
  testMediaService(args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
  }): Promise<JsonRpcResponse>;
  configureMediaService(args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
    enabled?: boolean;
  }): Promise<JsonRpcResponse>;
  removeMediaService(args: {
    agentId: string;
    serviceId: string;
  }): Promise<JsonRpcResponse>;
  listToolServices(args: {
    agentId: string;
    capability?: ToolServiceCapability;
  }): Promise<JsonRpcResponse>;
  getToolService(args: {
    agentId: string;
    serviceId: string;
  }): Promise<JsonRpcResponse>;
  testToolService(args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
  }): Promise<JsonRpcResponse>;
  configureToolService(args: {
    agentId: string;
    serviceId: string;
    config: Record<string, unknown>;
    enabled?: boolean;
  }): Promise<JsonRpcResponse>;
  removeToolService(args: {
    agentId: string;
    serviceId: string;
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

export interface IdentityAccountSummary {
  displayName: string;
  issuer: string;
  subject: string;
  active: boolean;
  unlocked: boolean;
}

export interface IdentityStatus {
  exists: boolean;
  unlocked: boolean;
  displayName?: string;
  issuer?: string;
  subject?: string;
  activeSubject?: string;
  accounts: IdentityAccountSummary[];
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
  unlock(args: { password: string; subject?: string }): Promise<IdentityOperationResult>;
  select(args: { subject: string }): Promise<IdentityOperationResult>;
  remove(args: { subject: string; password: string }): Promise<IdentityOperationResult>;
  lock(): Promise<IdentityStatus>;
  changePassword(args: {
    currentPassword: string;
    newPassword: string;
    subject?: string;
  }): Promise<IdentityOperationResult>;
  exportBackup(args?: { subject?: string }): Promise<IdentityOperationResult>;
  importBackup(args: { password: string }): Promise<IdentityOperationResult>;
}

export interface LocalAgentsBridge {
  discover(): Promise<LocalAgentInfo[]>;
  create(args: { name: string; description: string }): Promise<AgentCreationResult>;
  control(args: { agentId: string; connectionId: string; action: AgentLifecycleAction }): Promise<AgentLifecycleResult>;
}

export type LocalAIServiceState =
  | "online"
  | "starting"
  | "downloading"
  | "not_installed"
  | "download_error"
  | "stopped"
  | "unavailable"
  | "available"
  | "error";

export interface LocalAIServiceStatus {
  id: "embedding" | "stt" | "tts_voxcpm" | "voiceprint" | "face";
  name: string;
  description: string;
  model: string;
  selected_model_id: string;
  models: LocalAIModelOption[];
  selection_locked: boolean;
  selection_lock_reason: string;
  selected_device: "auto" | "cpu" | "cuda";
  supported_devices: Array<"auto" | "cpu" | "cuda">;
  expected_size: string;
  endpoint: string;
  required: boolean;
  controllable: boolean;
  downloadable: boolean;
  installed: boolean;
  missing_dependencies: string[];
  model_present: boolean;
  model_path: string;
  expected_size_bytes: number;
  downloaded_bytes: number;
  download_progress: number;
  state: LocalAIServiceState;
  pid?: number | null;
  started_at: string;
  device: string;
  health: Record<string, unknown>;
  memory_bytes: number;
  system_memory_total_bytes: number;
  gpu_memory_bytes: number;
  gpu_memory_total_bytes: number;
  error: string;
  log_path: string;
  download_log_path: string;
}

export interface LocalAIModelOption {
  id: string;
  name: string;
  source: string;
  expected_size: string;
  expected_size_bytes: number;
  downloaded_bytes: number;
  model_present: boolean;
  recommended_device: string;
  supported_devices: string[];
}

export interface LocalAISystemStatus {
  cpu_percent: number;
  memory_percent: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  gpus: Array<{
    name: string;
    utilization_percent: number;
    memory_used_bytes: number;
    memory_total_bytes: number;
  }>;
}

export interface LocalAIDownloadProgress {
  serviceId: string;
  modelId: string;
  progress: number;
  completed: boolean;
  failed: boolean;
  error: string;
}

export interface LocalAIBridge {
  list(): Promise<{
    ok: boolean;
    services: LocalAIServiceStatus[];
    system?: LocalAISystemStatus;
    error?: string;
  }>;
  control(args: {
    serviceId: string;
    action: "start" | "stop" | "restart" | "download" | "cancel-download";
    device?: "auto" | "cpu" | "cuda";
  }): Promise<{ ok: boolean; service?: LocalAIServiceStatus; error?: string }>;
  selectModel(args: { serviceId: string; modelId: string }): Promise<{
    ok: boolean;
    service?: LocalAIServiceStatus;
    error?: string;
  }>;
  selectDevice(args: {
    serviceId: string;
    device: "auto" | "cpu" | "cuda";
  }): Promise<{ ok: boolean; service?: LocalAIServiceStatus; error?: string }>;
  downloadProgress(args: { serviceId: string; modelId: string }): Promise<{
    ok: boolean;
    progress?: LocalAIDownloadProgress;
    error?: string;
  }>;
  readLog(args: { serviceId: string }): Promise<{ ok: boolean; content: string; error?: string }>;
  openDirectory(): Promise<DirectoryOpenResult>;
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

export interface DesktopSettings {
  openAtLogin: boolean;
  openAtLoginAvailable: boolean;
  closeBehavior: "exit" | "minimize";
  notificationsEnabled: boolean;
  language: "zh-CN" | "en-US";
  openRightSidebarByDefault: boolean;
  automaticUpdates: {
    state: "disabled";
    message: string;
  };
}

export interface DesktopSettingsResult {
  ok: boolean;
  settings?: DesktopSettings;
  error?: string;
}

export interface DesktopBridge {
  getInfo(): Promise<DesktopInfo>;
  getSettings(): Promise<DesktopSettings>;
  updateSettings(
    patch: Partial<Pick<
      DesktopSettings,
      | "openAtLogin"
      | "closeBehavior"
      | "notificationsEnabled"
      | "language"
      | "openRightSidebarByDefault"
    >>,
  ): Promise<DesktopSettingsResult>;
  readLog(): Promise<{ content: string }>;
  openLogDirectory(): Promise<DirectoryOpenResult>;
  openConfigDirectory(): Promise<DirectoryOpenResult>;
  openExternal(url: string): Promise<DirectoryOpenResult>;
}

export interface WinBridge {
  minimize(): void;
  maximize(): void;
  close(): void;
  quit(): void;
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
    localAI: LocalAIBridge;
    notifications: NotificationsBridge;
    desktop: DesktopBridge;
    win: WinBridge;
    terminal: TerminalBridge;
  }
}
