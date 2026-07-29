import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCoreStore,
  AssignmentSnapshot,
  DisplayMessage,
  MemoryReference,
} from "../../store";
import { Button, Icon } from "../ui";
import { ChatInput } from "./ChatInput";
import { ChatTopbar } from "./ChatTopbar";
import { openSettingsCenter } from "../settings/events";
import { AssignmentCard } from "./AssignmentCard";
import { ActivitySidebar } from "../right-sidebar/ActivitySidebar";
import { TerminalPanel } from "../terminal/TerminalPanel";
import { MarkdownMessage } from "./MarkdownMessage";

const EMPTY_MSGS: DisplayMessage[] = [];
const EMPTY_ASSIGNMENTS: AssignmentSnapshot[] = [];
type RightSidebarSection = "activity" | "state" | "assignment" | "artifact" | "memory" | "context";

export function HomePage() {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const messages = useCoreStore((s) => s.messagesByAgent[s.activeAgentId || ""] || EMPTY_MSGS);
  const sending = useCoreStore((s) => s.sendingByAgent[s.activeAgentId || ""] || false);
  const agentName = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return t("home.defaultAgentName");
    return s.connectionByAgent[agentId]?.agentName
      || s.agents.find((agent) => agent.id === agentId)?.name
      || t("home.defaultAgentName");
  });
  const activeAgent = useCoreStore((s) => s.agents.find((agent) => agent.id === s.activeAgentId));
  const activeAgentOnline = useCoreStore((s) => s.localAvailabilityByAgent[s.activeAgentId || ""]);
  const activeAgentInfo = useCoreStore((s) => s.localInfoByAgent[s.activeAgentId || ""]);
  const activeAgentLifecycle = useCoreStore((s) => s.lifecycleByAgent[s.activeAgentId || ""]);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const terminalAgentId = useCoreStore((s) => s.terminalAgentId);
  const controlLocalAgent = useCoreStore((s) => s.controlLocalAgent);
  const sendMessage = useCoreStore((s) => s.sendMessage);
  const abortMessage = useCoreStore((s) => s.abortMessage);
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);
  const historyPage = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return agentId && sessionId ? s.historyPaginationByAgent[agentId]?.[sessionId] : undefined;
  });
  const loadOlderMessages = useCoreStore((s) => s.loadOlderMessages);
  const assignments = useCoreStore((s) => s.assignmentsByAgent[s.activeAgentId || ""] || EMPTY_ASSIGNMENTS);
  const connectionStatus = useCoreStore((s) => s.connectionByAgent[s.activeAgentId || ""]?.status);
  const refreshAssignments = useCoreStore((s) => s.refreshAssignments);
  const refreshActivities = useCoreStore((s) => s.refreshActivities);
  const refreshArtifacts = useCoreStore((s) => s.refreshArtifacts);
  const refreshPersonMemories = useCoreStore((s) => s.refreshPersonMemories);
  const refreshAgentState = useCoreStore((s) => s.refreshAgentState);
  const agentState = useCoreStore((s) => s.agentStateByAgent[s.activeAgentId || ""]);
  const currentActivity = useCoreStore((s) => (
    s.activitiesByAgent[s.activeAgentId || ""] || []
  ).find((item) => ["queued", "running", "paused"].includes(item.status)));

  const [activityPanelOpen, setActivityPanelOpen] = useState(false);
  const [rightSidebarSection, setRightSidebarSection] = useState<RightSidebarSection>("activity");
  const [focusedArtifactKey, setFocusedArtifactKey] = useState("");
  const [focusedMemories, setFocusedMemories] = useState<MemoryReference[]>([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<string | null>(null);
  const [historyTraversalStarted, setHistoryTraversalStarted] = useState<Set<string>>(() => new Set());
  const [followingLatest, setFollowingLatest] = useState(true);
  const [unreadWhileAway, setUnreadWhileAway] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const previousFirstMessageId = useRef<string | null>(null);
  const followLatestRef = useRef(true);
  const scrollFrameRef = useRef<number>();

  useEffect(() => {
    let active = true;
    void window.desktop.getSettings().then((settings) => {
      if (active) setActivityPanelOpen(settings.openRightSidebarByDefault);
    });
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<import("../../types").DesktopSettings>).detail;
      setActivityPanelOpen(settings.openRightSidebarByDefault);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => {
      active = false;
      window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
    };
  }, []);

  useEffect(() => {
    if (activeAgentId && connectionStatus === "connected") {
      void refreshAssignments(activeAgentId);
      void refreshActivities(activeAgentId);
      void refreshArtifacts(activeAgentId);
      void refreshPersonMemories(activeAgentId);
      void refreshAgentState(activeAgentId);
    }
  }, [
    activeAgentId,
    connectionStatus,
    refreshActivities,
    refreshAgentState,
    refreshArtifacts,
    refreshPersonMemories,
    refreshAssignments,
  ]);

  useEffect(() => {
    setActivityPanelOpen(false);
    setSelectedAssignmentId(null);
    setFocusedMemories([]);
  }, [activeAgentId]);

  const scrollToLatest = useCallback(() => {
    const list = messageListRef.current;
    followLatestRef.current = true;
    setFollowingLatest(true);
    setUnreadWhileAway(false);
    if (list) list.scrollTop = list.scrollHeight;
  }, []);

  const scheduleScrollToLatest = useCallback(() => {
    window.cancelAnimationFrame(scrollFrameRef.current || 0);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      if (followLatestRef.current) scrollToLatest();
    });
  }, [scrollToLatest]);

  useEffect(() => () => window.cancelAnimationFrame(scrollFrameRef.current || 0), []);

  useEffect(() => {
    followLatestRef.current = true;
    setFollowingLatest(true);
    setUnreadWhileAway(false);
    previousFirstMessageId.current = null;
    scheduleScrollToLatest();
  }, [activeAgentId, activeSessionId, scheduleScrollToLatest]);

  useEffect(() => {
    const firstMessageId = messages[0]?.id || null;
    const previousFirst = previousFirstMessageId.current;
    const historyWasPrepended = Boolean(
      previousFirst
      && firstMessageId !== previousFirst
      && messages.some((message) => message.id === previousFirst),
    );
    if (!historyWasPrepended) {
      if (followLatestRef.current) {
        scheduleScrollToLatest();
      } else {
        setUnreadWhileAway(true);
      }
    }
    previousFirstMessageId.current = firstMessageId;
  }, [messages, scheduleScrollToLatest]);

  const handleMessageListScroll = useCallback(() => {
    const list = messageListRef.current;
    if (!list) return;
    const distanceToBottom = list.scrollHeight - list.clientHeight - list.scrollTop;
    const nearBottom = distanceToBottom <= 72;
    followLatestRef.current = nearBottom;
    setFollowingLatest(nearBottom);
    if (nearBottom) setUnreadWhileAway(false);
  }, []);

  const loadOlderPreservingPosition = useCallback(async () => {
    const historyKey = activeAgentId && activeSessionId
      ? `${activeAgentId}:${activeSessionId}`
      : "";
    if (historyKey && historyPage?.hasMore) {
      setHistoryTraversalStarted((current) => {
        if (current.has(historyKey)) return current;
        const next = new Set(current);
        next.add(historyKey);
        return next;
      });
    }
    const list = messageListRef.current;
    const previousHeight = list?.scrollHeight || 0;
    await loadOlderMessages();
    requestAnimationFrame(() => {
      if (list) list.scrollTop += list.scrollHeight - previousHeight;
    });
  }, [activeAgentId, activeSessionId, historyPage?.hasMore, loadOlderMessages]);

  useEffect(() => {
    const sentinel = topRef.current;
    const list = messageListRef.current;
    if (!sentinel || !list || !historyPage?.hasMore || historyPage.loading || historyPage.error) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadOlderPreservingPosition();
    }, { root: list, threshold: 0.1 });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [activeAgentId, activeSessionId, historyPage?.hasMore, historyPage?.loading, historyPage?.error, loadOlderPreservingPosition]);

  const hasMessages = messages.length > 0;
  const activeHistoryKey = activeAgentId && activeSessionId
    ? `${activeAgentId}:${activeSessionId}`
    : "";
  const showOldestReached = Boolean(
    activeHistoryKey
    && historyTraversalStarted.has(activeHistoryKey)
    && historyPage
    && !historyPage.hasMore
    && !historyPage.loading
    && !historyPage.error,
  );
  const isDreaming = agentState?.living === "dreaming";
  const showAgentStart = !hasMessages && activeAgent?.source === "local" && activeAgentOnline === false;
  const agentStarting = activeAgentLifecycle?.status === "starting" || activeAgentLifecycle?.status === "restarting";
  const agentNeedsRestart = Boolean(activeAgentInfo?.pid);
  const visibleAssignments = assignments
    .filter((assignment) => (
      assignment.originSessionId === activeSessionId
      && !["declined", "cancelled"].includes(assignment.status)
    ))
    .slice(0, 2);
  const openAssignment = (assignmentId: string) => {
    setSelectedAssignmentId(assignmentId);
    setActivityPanelOpen(true);
  };

  const taskName = (() => {
    if (activeSessionId && activeAgentId) {
      const sessions = sessionsByAgent[activeAgentId] || [];
      const s = sessions.find((x) => x.id === activeSessionId);
      if (s) return s.name;
    }
    return agentName || t("home.defaultAgentName");
  })();

  return (
    <div className="main-content">
      <div className="main-content-primary">
      {activeAgentId && !showAgentStart && (
        <ChatTopbar
          taskName={taskName}
          onSearch={() => {}}
          onToggleRightPanel={() => setActivityPanelOpen((open) => !open)}
          rightPanelOpen={activityPanelOpen}
          onOpenAgentSettings={() => openSettingsCenter("overview")}
          agentState={agentState}
          activitySummary={currentActivity?.progressSummary || currentActivity?.title || ""}
        />
      )}
      <div className={`wb-home-page ${hasMessages ? "is-conversation" : "is-empty"}`}>
        {showAgentStart && activeAgent && activeAgentId && (
          <div className="agent-start-state">
            <div className="agent-start-avatar">{activeAgent.name.charAt(0)}</div>
            <h1>
              {agentNeedsRestart
                ? t("home.agentDisconnectedTitle", { name: activeAgent.name })
                : t("home.agentCreatedTitle", { name: activeAgent.name })}
            </h1>
            <p className="agent-start-role">
              <span>{t("home.agentResponsibility")}</span>
              {activeAgent.description || t("home.agentResponsibilityFallback")}
            </p>
            {agentNeedsRestart && (
              <p className="agent-start-status-hint">{t("home.agentDisconnectedHint")}</p>
            )}
            <Button
              variant="primary"
              size="lg"
              icon={agentStarting ? "refresh" : "play"}
              disabled={agentStarting}
              onClick={() => { void controlLocalAgent(activeAgentId, agentNeedsRestart ? "restart" : "start"); }}
            >
              {agentStarting
                ? t("home.agentStarting")
                : agentNeedsRestart
                  ? t("home.restartAgent", { name: activeAgent.name })
                  : t("home.startAgent", { name: activeAgent.name })}
            </Button>
            {activeAgentLifecycle?.status === "error" && (
              <div className="agent-start-error">{activeAgentLifecycle.error}</div>
            )}
          </div>
        )}
        {!hasMessages && !showAgentStart && (
          <>
            <div className="agent-empty-profile">
              <div className="agent-empty-avatar">{agentName.charAt(0)}</div>
              <h1>{agentName}</h1>
              <p>{activeAgent?.description || t("home.agentResponsibilityFallback")}</p>
              <span className={`agent-empty-presence ${agentState?.living || "idle"}`}>
                <i />
                {agentState?.focusSummary || (agentState ? livingStateName(agentState.living) : t("home.agentReady"))}
              </span>
            </div>
            {visibleAssignments.length > 0 && (
              <div className="assignment-home-cards">
                {visibleAssignments.map((assignment) => (
                  <AssignmentCard key={assignment.id} assignment={assignment} onOpen={openAssignment} />
                ))}
              </div>
            )}
            {isDreaming && <DreamingNotice agentName={agentName} />}
          </>
        )}
        {hasMessages && (
          <>
            {isDreaming && <DreamingNotice agentName={agentName} />}
            {visibleAssignments.length > 0 && (
              <div className="assignment-conversation-strip">
                {visibleAssignments.map((assignment) => (
                  <AssignmentCard key={assignment.id} assignment={assignment} onOpen={openAssignment} />
                ))}
              </div>
            )}
            <div className="message-list" ref={messageListRef} onScroll={handleMessageListScroll}>
              <div className="message-list-inner">
                <div ref={topRef} className="history-page-status">
                  {historyPage?.loading && t("home.loadingOlder")}
                  {historyPage?.error && (
                    <button type="button" onClick={() => { void loadOlderPreservingPosition(); }}>
                      {t("home.retryOlder")}
                    </button>
                  )}
                  {showOldestReached ? t("home.oldestReached") : null}
                </div>
                {messages.map((m) => (
                  <MessageRow
                    key={m.id}
                    message={m}
                    agentName={agentName || t("home.defaultAgentName")}
                    onShowArtifact={(artifactId, sessionId) => {
                      setFocusedArtifactKey(`${sessionId}:${artifactId}`);
                      setRightSidebarSection("artifact");
                      setActivityPanelOpen(true);
                    }}
                    onShowMemories={(references) => {
                      setFocusedMemories(references);
                      setRightSidebarSection("context");
                      setActivityPanelOpen(true);
                    }}
                  />
                ))}
                <div ref={bottomRef} />
              </div>
            </div>
            {!followingLatest && (
              <button
                type="button"
                className={`scroll-to-latest ${unreadWhileAway ? "has-unread" : ""}`}
                onClick={scrollToLatest}
                title="回到底部"
              >
                <Icon name="chevron-down" size={16} />
                {unreadWhileAway && <span>有新消息</span>}
              </button>
            )}
          </>
        )}
        {!showAgentStart && (
          <div className="wb-home-composer">
            <ChatInput onSend={sendMessage} sending={sending} onAbort={abortMessage} />
          </div>
        )}
      </div>
      {terminalOpen && <TerminalPanel key={terminalAgentId || "shell"} />}
      </div>
      <ActivitySidebar
        open={activityPanelOpen}
        onClose={() => setActivityPanelOpen(false)}
        selectedAssignmentId={selectedAssignmentId}
        onSelectAssignment={setSelectedAssignmentId}
        section={rightSidebarSection}
        onSectionChange={setRightSidebarSection}
        focusedArtifactKey={focusedArtifactKey}
        focusedMemories={focusedMemories}
      />
    </div>
  );
}

function DreamingNotice({ agentName }: { agentName: string }) {
  return (
    <div className="dreaming-message-notice" role="status">
      <Icon name="moon" size={16} />
      <div>
        <strong>{agentName}正在梦境中</strong>
        <span>收到的消息会安全排队，并在醒来后按顺序处理。</span>
      </div>
    </div>
  );
}

function livingStateName(state: import("../../store").AgentStateSnapshot["living"]): string {
  return {
    dormant: "休眠",
    waking: "正在苏醒",
    awake: "清醒",
    idle: "已准备好",
    working: "工作中",
    sleeping: "睡眠中",
    dreaming: "梦境中",
  }[state];
}

// ── 解析 ANSI 转义码，分离思考内容和正文 ──

function parseThinkingContent(raw: string, streaming: boolean): { thinking: string; content: string } {
  const ansiDim = /\x1b\[2m([\s\S]*?)\x1b\[0m/g;
  const thinkingParts: string[] = [];
  let content = raw.replace(ansiDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });
  const bareDim = /\[2m([\s\S]*?)\[0m/g;
  content = content.replace(bareDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });

  if (streaming) {
    const openTag = /\x1b\[2m([\s\S]*?)$/;
    const m = content.match(openTag);
    if (m) {
      thinkingParts.push(m[1].trim());
      content = content.replace(openTag, "");
    }
    const bareOpen = /\[2m([\s\S]*?)$/;
    const bm = content.match(bareOpen);
    if (bm) {
      thinkingParts.push(bm[1].trim());
      content = content.replace(bareOpen, "");
    }
  }

  return {
    thinking: thinkingParts.join("\n\n").trim(),
    content: content.trim(),
  };
}

function MessageRow({
  message,
  agentName,
  onShowArtifact,
  onShowMemories,
}: {
  message: DisplayMessage;
  agentName: string;
  onShowArtifact: (artifactId: string, sessionId: string) => void;
  onShowMemories: (references: MemoryReference[]) => void;
}) {
  const { t } = useTranslation();
  const isUser = message.role === "user";
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [messageCopied, setMessageCopied] = useState(false);
  const messageCopyTimerRef = useRef<number>();
  const activeAgentId = useCoreStore((s) => s.activeAgentId || "");
  const activeSessionId = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    return s.activeSessionByAgent[agentId] || "";
  });
  const retryMessage = useCoreStore((s) => s.retryMessage);
  const agentSending = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    return s.sendingByAgent[agentId] || false;
  });

  useEffect(() => () => window.clearTimeout(messageCopyTimerRef.current), []);

  const copyWholeMessage = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setMessageCopied(true);
    window.clearTimeout(messageCopyTimerRef.current);
    messageCopyTimerRef.current = window.setTimeout(() => setMessageCopied(false), 1600);
  };

  if (message.action) {
    return <ActionApprovalCard message={message} agentName={agentName} />;
  }

  if (message.interaction) {
    return <InteractionCard message={message} agentName={agentName} />;
  }

  if (message.artifact) {
    return (
      <ArtifactCard
        message={message}
        agentName={agentName}
        agentId={activeAgentId}
        sessionId={activeSessionId}
        onShowArtifact={onShowArtifact}
      />
    );
  }

  if (message.tool) {
    return <ToolActivityRow message={message} />;
  }

  if (isUser) {
    return (
      <div className="user-message-row">
        <div className="user-message-stack">
          <div className="user-message-bubble">
            {message.attachments && message.attachments.length > 0 && (
              <div className="message-attachments">
                {message.attachments.map((attachment) => (
                  <MessageAttachment
                    attachment={attachment}
                    agentId={activeAgentId}
                    sessionId={activeSessionId}
                    key={attachment.id}
                  />
                ))}
              </div>
            )}
            {message.content && <div>{message.content}</div>}
            {(message.deliveryStatus === "failed" || message.deliveryStatus === "interrupted") &&
              message.sourceMessageId && (
                <button
                  type="button"
                  className="message-retry"
                  disabled={agentSending}
                  onClick={() => void retryMessage(message.sourceMessageId!)}
                >
                  重试
                </button>
              )}
            {message.deliveryStatus && message.deliveryStatus !== "completed" && (
              <div className={`message-delivery-status ${message.deliveryStatus}`}>
                {message.deliveryStatus === "queued" && "已排队"}
                {message.deliveryStatus === "processing" && "处理中"}
                {message.deliveryStatus === "failed" && `处理失败${message.deliveryError ? `：${message.deliveryError}` : ""}`}
                {message.deliveryStatus === "interrupted" && "已中断"}
              </div>
            )}
          </div>
          <div className="user-message-meta">
            {message.createdAt && (
              <time dateTime={new Date(message.createdAt).toISOString()}>
                {formatMessageTime(message.createdAt)}
              </time>
            )}
            <button
              type="button"
              title="复制整条消息"
              onClick={() => void copyWholeMessage(message.content)}
            >
              <Icon name="copy" size={13} />
              <span>{messageCopied ? "已复制" : "复制"}</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  const { thinking, content } = parseThinkingContent(message.content, message.streaming);
  const hasThinking = thinking.length > 0;
  const displayedContent = hasThinking ? content : message.content;
  const thinkingComplete = !message.streaming || /\x1b\[0m/.test(message.content) || /\[0m/.test(message.content);

  return (
    <div className="assistant-message-row">
      <button
        type="button"
        className="message-copy-action"
        title="复制整条回答"
        onClick={() => void copyWholeMessage(displayedContent)}
      >
        <Icon name="copy" size={14} />
        <span>{messageCopied ? "已复制" : "复制"}</span>
      </button>
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">
          {agentName.charAt(0)}
        </div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      {hasThinking && (
        <div className={`thinking-block ${!thinkingExpanded ? "thinking-collapsed" : ""} ${thinkingComplete ? "thinking-complete" : ""}`}>
          <div
            className={`thinking-header ${!thinkingComplete ? "thinking-loading" : ""}`}
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
          >
            <span className="thinking-title">{t("home.deepThink")}</span>
            {thinkingComplete && (
              <span className={`thinking-chevron ${thinkingExpanded ? "expanded" : ""}`}>▼</span>
            )}
          </div>
          {thinkingExpanded && (
            <div className="thinking-content">
              {thinking}
            </div>
          )}
        </div>
      )}
      <div className="assistant-text-content">
        <MarkdownMessage
          content={displayedContent}
          streaming={message.streaming}
        />
        {message.memoryReferences && message.memoryReferences.length > 0 && (
          <button
            type="button"
            className="message-memory-reference"
            onClick={() => onShowMemories(message.memoryReferences || [])}
          >
            <Icon name="sparkles" size={13} />
            查看本次召回的 {message.memoryReferences.length} 条记忆
          </button>
        )}
      </div>
    </div>
  );
}

function formatMessageTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function MessageAttachment({
  attachment,
  agentId,
  sessionId,
}: {
  attachment: NonNullable<DisplayMessage["attachments"]>[number];
  agentId: string;
  sessionId: string;
}) {
  const [previewUrl, setPreviewUrl] = useState(attachment.previewUrl || "");
  const [error, setError] = useState("");

  useEffect(() => {
    setPreviewUrl(attachment.previewUrl || "");
    setError("");
    if (attachment.kind !== "image" || attachment.previewUrl || !agentId || !sessionId) return;
    let cancelled = false;
    void window.gateway.getAttachment({
      agentId,
      sessionId,
      attachmentId: attachment.id,
    }).then((response) => {
      if (cancelled) return;
      if (response.error) {
        setError(response.error.message);
        return;
      }
      const value = response.result?.attachment;
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        setError("附件内容无效");
        return;
      }
      const item = value as Record<string, unknown>;
      const dataBase64 = typeof item.dataBase64 === "string" ? item.dataBase64 : "";
      const mimeType = typeof item.mimeType === "string" ? item.mimeType : attachment.mimeType;
      if (!dataBase64) {
        setError("附件内容为空");
        return;
      }
      setPreviewUrl(`data:${mimeType};base64,${dataBase64}`);
    }).catch((reason) => {
      if (!cancelled) setError(String(reason));
    });
    return () => { cancelled = true; };
  }, [agentId, attachment.id, attachment.kind, attachment.mimeType, attachment.previewUrl, sessionId]);

  const open = async () => {
    if (!agentId || !sessionId) return;
    const result = await window.gateway.openAttachment({
      agentId,
      sessionId,
      attachmentId: attachment.id,
    });
    setError(result.ok ? "" : result.error || "无法打开附件");
  };

  return (
    <button
      type="button"
      className={`message-attachment ${attachment.kind}`}
      onClick={() => { void open(); }}
      title={error || `打开 ${attachment.name}`}
    >
      {previewUrl ? (
        <img src={previewUrl} alt={attachment.name} />
      ) : (
        <span className={`message-attachment-icon ${error ? "error" : ""}`}>
          {error ? "!" : attachment.kind === "image" ? "IMG" : "FILE"}
        </span>
      )}
      <span className="message-attachment-name">{attachment.name}</span>
    </button>
  );
}

function ArtifactCard({
  message,
  agentName,
  agentId,
  sessionId,
  onShowArtifact,
}: {
  message: DisplayMessage;
  agentName: string;
  agentId: string;
  sessionId: string;
  onShowArtifact: (artifactId: string, sessionId: string) => void;
}) {
  const artifact = message.artifact!;
  const [previewUrl, setPreviewUrl] = useState("");
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    setPreviewUrl("");
    setError("");
    if (artifact.kind !== "image" || artifact.size > 5 * 1024 * 1024 || !agentId || !sessionId) return;
    let cancelled = false;
    void window.gateway.getArtifact({ agentId, sessionId, artifactId: artifact.id })
      .then((response) => {
        if (cancelled) return;
        if (response.error) {
          setError(response.error.message);
          return;
        }
        const raw = response.result?.artifact;
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
        const value = raw as Record<string, unknown>;
        const data = typeof value.dataBase64 === "string" ? value.dataBase64 : "";
        const mime = typeof value.mimeType === "string" ? value.mimeType : artifact.mimeType;
        if (data) setPreviewUrl(`data:${mime};base64,${data}`);
      })
      .catch((reason) => { if (!cancelled) setError(String(reason)); });
    return () => { cancelled = true; };
  }, [agentId, artifact.id, artifact.kind, artifact.mimeType, artifact.size, sessionId]);

  const open = async () => {
    if (!agentId || !sessionId || opening) return;
    setOpening(true);
    try {
      const result = await window.gateway.openArtifact({
        agentId, sessionId, artifactId: artifact.id,
      });
      setError(result.ok ? "" : result.error || "无法打开产物");
    } finally {
      setOpening(false);
    }
  };

  const size = artifact.size < 1024
    ? `${artifact.size} B`
    : artifact.size < 1024 * 1024
      ? `${(artifact.size / 1024).toFixed(1)} KB`
      : `${(artifact.size / 1024 / 1024).toFixed(1)} MB`;

  return (
    <div className="assistant-message-row artifact-message-row">
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      <div className="artifact-card-group">
        <button
          type="button"
          className={`artifact-card artifact-${artifact.kind}`}
          onClick={() => void open()}
          disabled={opening}
          title={error || `打开 ${artifact.name}`}
        >
          {previewUrl ? (
            <img className="artifact-preview" src={previewUrl} alt={artifact.name} />
          ) : (
            <span className={`artifact-icon ${error ? "error" : ""}`}>
              <Icon name={artifact.kind === "image" ? "sparkles" : "file-text"} size={20} />
            </span>
          )}
          <span className="artifact-info">
            <span className="artifact-label">Agent 产物</span>
            <span className="artifact-name">{artifact.name}</span>
            <span className="artifact-meta">{size}{opening ? " · 正在打开" : ""}</span>
            {error && <span className="artifact-error">{error}</span>}
          </span>
          <Icon name="external-link" size={16} className="artifact-open-icon" />
        </button>
        <button
          type="button"
          className="artifact-show-sidebar"
          onClick={() => onShowArtifact(artifact.id, sessionId)}
        >
          在产物栏查看
        </button>
      </div>
    </div>
  );
}

function ActionApprovalCard({ message, agentName }: { message: DisplayMessage; agentName: string }) {
  const { t } = useTranslation();
  const action = message.action!;
  const respondToAction = useCoreStore((s) => s.respondToAction);
  const canRespond = action.status === "pending" || action.status === "error";
  const command = typeof action.arguments.command === "string" ? action.arguments.command : "";

  const respond = (decision: "allow" | "deny") => {
    if (!canRespond) return;
    void respondToAction(action.id, decision);
  };

  return (
    <div className="assistant-message-row interaction-message-row">
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      <div className={`interaction-card action-card action-${action.status}`}>
        <div className="interaction-card-label action-card-label">
          {t("home.actionLabel")}
          <span className={`action-risk action-risk-${action.riskLevel}`}>
            {t(`home.actionRisk_${action.riskLevel}`, { defaultValue: action.riskLevel })}
          </span>
        </div>
        <div className="interaction-card-question">{action.summary}</div>
        {action.reason && <div className="action-card-reason">{action.reason}</div>}
        {command && <pre className="action-card-command">{command}</pre>}
        {canRespond && (
          <div className="interaction-card-choices action-card-actions">
            <button type="button" className="action-deny" onClick={() => respond("deny")}>
              {t("home.actionDeny")}
            </button>
            <button type="button" className="action-allow" onClick={() => respond("allow")}>
              {t("home.actionAllowOnce")}
            </button>
          </div>
        )}
        {action.status === "responding" && (
          <div className="interaction-card-status">{t("home.actionResponding")}</div>
        )}
        {action.status === "completed" && (
          <div className="interaction-card-status interaction-card-result">{t("home.actionCompleted")}</div>
        )}
        {action.status === "rejected" && (
          <div className="interaction-card-status">{t("home.actionRejected")}</div>
        )}
        {action.status === "cancelled" && (
          <div className="interaction-card-status">{t("home.actionCancelled")}</div>
        )}
        {action.status === "expired" && (
          <div className="interaction-card-status">{t("home.actionExpired")}</div>
        )}
        {(action.status === "failed" || action.status === "error") && (
          <div className="interaction-card-error">{action.error || t("home.actionFailed")}</div>
        )}
      </div>
    </div>
  );
}

function ToolActivityRow({ message }: { message: DisplayMessage }) {
  const { t } = useTranslation();
  const tool = message.tool!;
  const running = tool.status === "running";
  const failed = tool.status === "error";
  const title = running
    ? t("home.toolRunning", { name: tool.name })
    : failed
      ? t("home.toolError", { name: tool.name })
      : t("home.toolComplete", { name: tool.name });
  const hasArguments = Object.keys(tool.arguments).length > 0;
  const hasDetails = hasArguments || Boolean(tool.summary) || Boolean(tool.error);

  return (
    <div className={`tool-activity tool-${tool.status}`}>
      <span className="tool-activity-indicator" aria-hidden="true" />
      <div className="tool-activity-body">
        {hasDetails && !running ? (
          <details className="tool-activity-details">
            <summary className="tool-activity-title">{title}</summary>
            {hasArguments && (
              <div className="tool-activity-section">
                <span>{t("home.toolArguments")}</span>
                <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
              </div>
            )}
            {(tool.error || tool.summary) && (
              <div className="tool-activity-section">
                <span>{failed ? t("home.toolErrorDetail") : t("home.toolResult")}</span>
                <pre>{tool.error || tool.summary}{tool.truncated ? "…" : ""}</pre>
              </div>
            )}
          </details>
        ) : (
          <div className="tool-activity-title">{title}</div>
        )}
      </div>
    </div>
  );
}

function InteractionCard({ message, agentName }: { message: DisplayMessage; agentName: string }) {
  const { t } = useTranslation();
  const interaction = message.interaction!;
  const respondToInteraction = useCoreStore((s) => s.respondToInteraction);
  const [answer, setAnswer] = useState("");
  const canRespond = interaction.status === "pending" || interaction.status === "error";
  const waiting = interaction.status === "responding";

  const submit = (response: string) => {
    if (!canRespond || !response.trim()) return;
    void respondToInteraction(interaction.id, response.trim());
  };

  return (
    <div className="assistant-message-row interaction-message-row">
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      <div className={`interaction-card interaction-${interaction.status}`}>
        <div className="interaction-card-label">{t("home.interactionLabel")}</div>
        <div className="interaction-card-question">{interaction.question}</div>
        {canRespond && interaction.choices.length > 0 && (
          <div className="interaction-card-choices">
            {interaction.choices.map((choice) => (
              <button type="button" key={choice} onClick={() => submit(choice)}>
                {choice}
              </button>
            ))}
          </div>
        )}
        {canRespond && interaction.choices.length === 0 && (
          <form
            className="interaction-card-answer"
            onSubmit={(event) => {
              event.preventDefault();
              submit(answer);
            }}
          >
            <input
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder={t("home.interactionAnswerPlaceholder")}
              autoFocus
            />
            <button type="submit" disabled={!answer.trim()}>{t("home.interactionSubmit")}</button>
          </form>
        )}
        {waiting && <div className="interaction-card-status">{t("home.interactionSending")}</div>}
        {interaction.status === "answered" && (
          <div className="interaction-card-status interaction-card-result">
            {t("home.interactionAnswered", { answer: interaction.response })}
          </div>
        )}
        {interaction.status === "expired" && (
          <div className="interaction-card-status">{t("home.interactionExpired")}</div>
        )}
        {interaction.status === "cancelled" && (
          <div className="interaction-card-status">{t("home.interactionCancelled")}</div>
        )}
        {interaction.status === "error" && interaction.error && (
          <div className="interaction-card-error">{interaction.error}</div>
        )}
      </div>
    </div>
  );
}
