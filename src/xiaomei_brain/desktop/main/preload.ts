import { contextBridge, ipcRenderer } from "electron";

// ── CHANNEL_MAP — 声明式 IPC 通道定义 ──

interface InvokeChannel {
  invoke: string;
}

interface SendChannel {
  send: string;
}

interface EventChannel {
  event: string;
}

const CHANNEL_MAP = {
  gateway: {
    connect:         { invoke: "gateway:connect" },
    switchSession:   { invoke: "gateway:switchSession" },
    disconnect:      { invoke: "gateway:disconnect" },
    sendMessage:     { invoke: "gateway:sendMessage" },
    getInteractionCatalog: { invoke: "gateway:getInteractionCatalog" },
    compactSession:  { invoke: "gateway:compactSession" },
    sendVoice:       { invoke: "gateway:sendVoice" },
    setContinuousHearing: { invoke: "gateway:setContinuousHearing" },
    setCameraCapture: { invoke: "gateway:setCameraCapture" },
    pickAttachments: { invoke: "gateway:pickAttachments" },
    getAttachment:   { invoke: "gateway:getAttachment" },
    openAttachment:  { invoke: "gateway:openAttachment" },
    getArtifact:     { invoke: "gateway:getArtifact" },
    authorizeArtifactMedia: { invoke: "gateway:authorizeArtifactMedia" },
    listMediaLibrary: { invoke: "gateway:listMediaLibrary" },
    authorizeMediaTrack: { invoke: "gateway:authorizeMediaTrack" },
    listArtifacts:   { invoke: "gateway:listArtifacts" },
    listMemories:    { invoke: "gateway:listMemories" },
    openArtifact:    { invoke: "gateway:openArtifact" },
    downloadArtifact: { invoke: "gateway:downloadArtifact" },
    respondEmbodimentCommand: { invoke: "gateway:respondEmbodimentCommand" },
    abortMessage:    { invoke: "gateway:abortMessage" },
    continueMessage: { invoke: "gateway:continueMessage" },
    retryMessage:    { invoke: "gateway:retryMessage" },
    respondInteraction: { invoke: "gateway:respondInteraction" },
    respondAction:      { invoke: "gateway:respondAction" },
    getHistory:      { invoke: "gateway:getHistory" },
    listSessions:    { invoke: "gateway:listSessions" },
    deleteSession:   { invoke: "gateway:deleteSession" },
    unifiedSearch:   { invoke: "gateway:unifiedSearch" },
    listAssignments: { invoke: "gateway:listAssignments" },
    getAssignment: { invoke: "gateway:getAssignment" },
    listProjects: { invoke: "gateway:listProjects" },
    getProject: { invoke: "gateway:getProject" },
    getCurrentProject: { invoke: "gateway:getCurrentProject" },
    listWorkspaces: { invoke: "gateway:listWorkspaces" },
    getWorkspace: { invoke: "gateway:getWorkspace" },
    focusWorkspace: { invoke: "gateway:focusWorkspace" },
    listActivities: { invoke: "gateway:listActivities" },
    getActivity: { invoke: "gateway:getActivity" },
    getAgentState: { invoke: "gateway:getAgentState" },
    getBrain: { invoke: "gateway:getBrain" },
    watchBrain: { invoke: "gateway:watchBrain" },
    unwatchBrain: { invoke: "gateway:unwatchBrain" },
    getUsageSummary: { invoke: "gateway:getUsageSummary" },
    listUsage: { invoke: "gateway:listUsage" },
    listModelTraces: { invoke: "gateway:listModelTraces" },
    getModelTrace: { invoke: "gateway:getModelTrace" },
    clearModelTraces: { invoke: "gateway:clearModelTraces" },
    listVectorTraces: { invoke: "gateway:listVectorTraces" },
    clearVectorTraces: { invoke: "gateway:clearVectorTraces" },
    listCapabilities: { invoke: "gateway:listCapabilities" },
    getCapability: { invoke: "gateway:getCapability" },
    setCapabilityEnabled: { invoke: "gateway:setCapabilityEnabled" },
    getCapabilitySetupStatus: { invoke: "gateway:getCapabilitySetupStatus" },
    startCapabilitySetup: { invoke: "gateway:startCapabilitySetup" },
    cancelCapabilitySetup: { invoke: "gateway:cancelCapabilitySetup" },
    runCapabilityOAuth: { invoke: "gateway:runCapabilityOAuth" },
    inspectCapabilityPackage: { invoke: "gateway:inspectCapabilityPackage" },
    inspectCapabilityArtifact: { invoke: "gateway:inspectCapabilityArtifact" },
    listCapabilityPackages: { invoke: "gateway:listCapabilityPackages" },
    installCapabilityPackage: { invoke: "gateway:installCapabilityPackage" },
    setCapabilityPackageActive: { invoke: "gateway:setCapabilityPackageActive" },
    uninstallCapabilityPackage: { invoke: "gateway:uninstallCapabilityPackage" },
    openAssignmentArtifact: { invoke: "gateway:openAssignmentArtifact" },
    requestAssignmentCancel: { invoke: "gateway:requestAssignmentCancel" },
    requestAssignmentResume: { invoke: "gateway:requestAssignmentResume" },
    listIdentities:  { invoke: "gateway:listIdentities" },
    getPersonBiometrics: { invoke: "gateway:getPersonBiometrics" },
    enrollPersonBiometric: { invoke: "gateway:enrollPersonBiometric" },
    verifyPersonBiometric: { invoke: "gateway:verifyPersonBiometric" },
    listLegacySessions: { invoke: "gateway:listLegacySessions" },
    claimLegacySession: { invoke: "gateway:claimLegacySession" },
    getChannelConfig: { invoke: "gateway:getChannelConfig" },
    testChannel: { invoke: "gateway:testChannel" },
    configureChannel: { invoke: "gateway:configureChannel" },
    getChannelStatus: { invoke: "gateway:getChannelStatus" },
    removeChannel: { invoke: "gateway:removeChannel" },
    beginIdentityLink: { invoke: "gateway:beginIdentityLink" },
    getIdentityLinkStatus: { invoke: "gateway:getIdentityLinkStatus" },
    cancelIdentityLink: { invoke: "gateway:cancelIdentityLink" },
    listIdentityLinks: { invoke: "gateway:listIdentityLinks" },
    revokeIdentityLink: { invoke: "gateway:revokeIdentityLink" },
    getAgentConfig: { invoke: "gateway:getAgentConfig" },
    updateAgentConfig: { invoke: "gateway:updateAgentConfig" },
    resetAgentConfig: { invoke: "gateway:resetAgentConfig" },
    getModelConfig: { invoke: "gateway:getModelConfig" },
    getModelCatalog: { invoke: "gateway:getModelCatalog" },
    testModelProvider: { invoke: "gateway:testModelProvider" },
    configureModelProvider: { invoke: "gateway:configureModelProvider" },
    removeModelProvider: { invoke: "gateway:removeModelProvider" },
    setModelSelection: { invoke: "gateway:setModelSelection" },
    listMediaServices: { invoke: "gateway:listMediaServices" },
    getMediaRuntimeStatus: { invoke: "gateway:getMediaRuntimeStatus" },
    getMediaService: { invoke: "gateway:getMediaService" },
    testMediaService: { invoke: "gateway:testMediaService" },
    configureMediaService: { invoke: "gateway:configureMediaService" },
    removeMediaService: { invoke: "gateway:removeMediaService" },
    listToolServices: { invoke: "gateway:listToolServices" },
    getToolService: { invoke: "gateway:getToolService" },
    testToolService: { invoke: "gateway:testToolService" },
    configureToolService: { invoke: "gateway:configureToolService" },
    removeToolService: { invoke: "gateway:removeToolService" },
    getExecutionEnvironment: { invoke: "gateway:getExecutionEnvironment" },
    getExecutionEnvironmentStatus: { invoke: "gateway:getExecutionEnvironmentStatus" },
    testExecutionEnvironment: { invoke: "gateway:testExecutionEnvironment" },
    saveExecutionEnvironment: { invoke: "gateway:saveExecutionEnvironment" },
    getConfig:       { invoke: "store:getConfig" },
    onEvent:         { event: "gateway:event" },
  },
  localAgents: {
    discover:        { invoke: "localAgents:discover" },
    create:          { invoke: "localAgents:create" },
    control:         { invoke: "localAgents:control" },
  },
  localAI: {
    cachedList:       { invoke: "localAI:cachedList" },
    list:             { invoke: "localAI:list" },
    control:          { invoke: "localAI:control" },
    selectModel:      { invoke: "localAI:selectModel" },
    selectDevice:     { invoke: "localAI:selectDevice" },
    downloadProgress: { invoke: "localAI:downloadProgress" },
    startupState:     { invoke: "localAI:startupState" },
    readLog:          { invoke: "localAI:readLog" },
    openDirectory:    { invoke: "localAI:openDirectory" },
  },
  setup: {
    status:           { invoke: "setup:status" },
    installInference:{ invoke: "setup:installInference" },
    installFfmpeg:    { invoke: "setup:installFfmpeg" },
    installOptionalService: { invoke: "setup:installOptionalService" },
    onProgress:       { event: "setup:progress" },
  },
  bootstrap: {
    status:           { invoke: "bootstrap:status" },
    begin:            { invoke: "bootstrap:begin" },
    prepareRuntime:   { invoke: "bootstrap:prepareRuntime" },
    selectMode:       { invoke: "bootstrap:selectMode" },
    prepareQuick:     { invoke: "bootstrap:prepareQuick" },
    completeOptionalServices: { invoke: "bootstrap:completeOptionalServices" },
    rememberOptions:  { invoke: "bootstrap:rememberOptions" },
    provisionInitialAgent: { invoke: "bootstrap:provisionInitialAgent" },
    complete:         { invoke: "bootstrap:complete" },
    advancePreview:   { invoke: "bootstrap:advancePreview" },
  },
  identity: {
    status:           { invoke: "identity:status" },
    create:           { invoke: "identity:create" },
    unlock:           { invoke: "identity:unlock" },
    verifyPassword:   { invoke: "identity:verifyPassword" },
    select:           { invoke: "identity:select" },
    remove:           { invoke: "identity:remove" },
    lock:             { invoke: "identity:lock" },
    changePassword:   { invoke: "identity:changePassword" },
    exportBackup:     { invoke: "identity:exportBackup" },
    importBackup:     { invoke: "identity:importBackup" },
  },
  notifications: {
    show:             { invoke: "notification:show" },
    onSelect:         { event: "notification:selected" },
  },
  desktop: {
    getInfo:                { invoke: "desktop:getInfo" },
    getSettings:            { invoke: "desktop:getSettings" },
    updateSettings:         { invoke: "desktop:updateSettings" },
    readLog:                { invoke: "desktop:readLog" },
    openLogDirectory:       { invoke: "desktop:openLogDirectory" },
    openConfigDirectory:    { invoke: "desktop:openConfigDirectory" },
    openExternal:           { invoke: "desktop:openExternal" },
    reportRendererError:    { send: "desktop:reportRendererError" },
  },
  desktopUpdate: {
    getState:                { invoke: "desktop-update:getState" },
    check:                   { invoke: "desktop-update:check" },
    download:                { invoke: "desktop-update:download" },
    install:                 { invoke: "desktop-update:install" },
    onState:                 { event: "desktop-update:state" },
  },
  win: {
    minimize:          { send: "window:minimize" },
    maximize:          { send: "window:maximize" },
    close:             { send: "window:close" },
    quit:              { send: "window:quit" },
    isMaximized:       { invoke: "window:isMaximized" },
    setFullScreen:     { invoke: "window:setFullScreen" },
    onMaximizeChange:  { event: "window:maximizeChanged" },
  },
  terminal: {
    spawn:    { invoke: "terminal:spawn" },
    write:    { invoke: "terminal:write" },
    resize:   { invoke: "terminal:resize" },
    dispose:  { invoke: "terminal:dispose" },
    onData:   { event: "terminal:data" },
    onExit:   { event: "terminal:exit" },
  },
} as const;

// ── buildBridge ──

function isInvoke(def: unknown): def is InvokeChannel {
  return typeof def === "object" && def !== null && "invoke" in def;
}

function isSend(def: unknown): def is SendChannel {
  return typeof def === "object" && def !== null && "send" in def;
}

function isEvent(def: unknown): def is EventChannel {
  return typeof def === "object" && def !== null && "event" in def;
}

function buildBridge(map: typeof CHANNEL_MAP): void {
  for (const [namespace, methods] of Object.entries(map)) {
    const api: Record<string, unknown> = {};

    for (const [name, def] of Object.entries(methods)) {
      if (isInvoke(def)) {
        api[name] = (args: unknown) => ipcRenderer.invoke(def.invoke, args);
      } else if (isSend(def)) {
        api[name] = (...args: unknown[]) => ipcRenderer.send(def.send, ...args);
      } else if (isEvent(def)) {
        api[name] = (callback: (...cbArgs: unknown[]) => void) => {
          const handler = (_event: Electron.IpcRendererEvent, ...cbArgs: unknown[]) => {
            callback(...cbArgs);
          };
          ipcRenderer.on(def.event, handler);
          return () => {
            ipcRenderer.removeListener(def.event, handler);
          };
        };
      }
    }

    contextBridge.exposeInMainWorld(namespace, api);
  }
}

buildBridge(CHANNEL_MAP);
