import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore, AgentEntry } from "../../store";
import { Icon, Button } from "../ui";
import { SidebarTopbar } from "./SidebarTopbar";
import { SidebarFooter } from "./SidebarFooter";
import { AddAgentDialog } from "./AddAgentDialog";
import { openSettingsCenter } from "../settings/events";
import { openUnifiedSearch } from "../search/events";

export function ConversationList({
  collapsed,
  onCollapsedChange,
}: {
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  const { t } = useTranslation();
  const [addDialogOpen, setAddDialogOpen] = useState(false);

  const agents = useCoreStore((s) => s.agents);
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const connectionByAgent = useCoreStore((s) => s.connectionByAgent);
  const switchAgent = useCoreStore((s) => s.switchAgent);
  const newSession = useCoreStore((s) => s.newSession);
  const switchSession = useCoreStore((s) => s.switchSession);
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);
  const sessionListByAgent = useCoreStore((s) => s.sessionListByAgent);
  const activeMessageCount = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    return agentId ? (s.messagesByAgent[agentId]?.length || 0) : 0;
  });
  const searchSessions = useCoreStore((s) => s.searchSessions);
  const loadMoreSessions = useCoreStore((s) => s.loadMoreSessions);
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const setTerminalOpen = useCoreStore((s) => s.setTerminalOpen);
  const unreadByAgent = useCoreStore((s) => s.unreadByAgent);
  const unreadByConversation = useCoreStore((s) => s.unreadByConversation);
  const sendingByAgent = useCoreStore((s) => s.sendingByAgent);
  const sendingByConversation = useCoreStore((s) => s.sendingByConversation);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);
  const localInfoByAgent = useCoreStore((s) => s.localInfoByAgent);
  const lifecycleByAgent = useCoreStore((s) => s.lifecycleByAgent);
  const controlLocalAgent = useCoreStore((s) => s.controlLocalAgent);

  const [identityName, setIdentityName] = useState("");
  const displayName = identityName || t("sidebar.defaultUserName");

  useEffect(() => {
    const refreshIdentityName = () => {
      void window.identity.status().then((status) => {
        setIdentityName(status.displayName || "");
      });
    };
    refreshIdentityName();
    window.addEventListener("xiaomei:identity-status-changed", refreshIdentityName);
    return () => window.removeEventListener("xiaomei:identity-status-changed", refreshIdentityName);
  }, []);

  function handleNewSession() {
    void newSession();
  }

  const activeSessions = activeAgentId ? (sessionsByAgent[activeAgentId] || []) : [];
  const sessionListState = activeAgentId ? sessionListByAgent[activeAgentId] : undefined;
  const sessionBusy = activeAgentId
    ? Boolean(connectionByAgent[activeAgentId]?.status === "connecting")
    : false;
  const canCreateSession = activeMessageCount > 0
    && !sessionBusy
    && !Boolean(activeAgentId && sendingByAgent[activeAgentId]);

  useEffect(() => {
    if (activeAgentId && sessionListState?.query) void searchSessions("");
  }, [activeAgentId, searchSessions, sessionListState?.query]);

  return (
    <div className={`conversation-list ${collapsed ? "collapsed" : ""}`}>
      <SidebarTopbar
        collapsed={collapsed}
        onToggleCollapse={() => onCollapsedChange(!collapsed)}
        onSearch={openUnifiedSearch}
        onRefresh={() => { void refreshLocalAgents(); }}
        onTerminalToggle={() => setTerminalOpen(!terminalOpen)}
      />

      {collapsed ? (
        <div className="sidebar-collapsed-body">
          <div className="sidebar-collapsed-agent-list">
            {agents.map((a) => {
              const conn = connectionByAgent[a.id];
              const isActive = a.id === activeAgentId;
              return (
                <button
                  key={a.id}
                  className={`sidebar-collapsed-agent-btn ${isActive ? "active" : ""} ${sendingByAgent[a.id] ? "working" : ""}`}
                  onClick={() => {
                    if (a.source === "local" && localAvailabilityByAgent[a.id] === false) {
                      void controlLocalAgent(a.id, "start");
                    } else {
                      void switchAgent(a.id);
                    }
                  }}
                  title={`${a.name} (${a.host}:${a.port}) — ${conn?.status || "disconnected"}`}
                >
                  {a.name.charAt(0)}
                  {(unreadByAgent[a.id] || 0) > 0 && (
                    <span className="sidebar-collapsed-unread">
                      {(unreadByAgent[a.id] || 0) > 9 ? "9+" : unreadByAgent[a.id]}
                    </span>
                  )}
                </button>
              );
            })}
            <button
              className="sidebar-collapsed-agent-btn"
              onClick={() => { setAddDialogOpen(true); }}
              title={t("sidebar.addAgent")}
            >
              <Icon name="plus" size={16} />
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Agent list header */}
          <div className="agent-list-header">
            <span className="agent-list-header-text">
              {t("sidebar.agents")} ({agents.length})
            </span>
            <button
              className="agent-list-header-add"
              onClick={() => setAddDialogOpen(true)}
              title={t("sidebar.addAgent")}
            >
              <Icon name="plus" size={16} />
            </button>
          </div>

          {/* Agent list */}
          <div className="agent-list">
            {agents.length === 0 ? (
              <div className="agent-list-empty">
                <span>{t("sidebar.noAgents")}</span>
              </div>
            ) : (
              agents.map((a) => (
                <AgentItem
                  key={a.id}
                  agent={a}
                  isActive={a.id === activeAgentId}
                  connection={connectionByAgent[a.id]}
                  isWorking={sendingByAgent[a.id] || false}
                  unreadCount={unreadByAgent[a.id] || 0}
                  localOnline={a.source === "local" ? localAvailabilityByAgent[a.id] : undefined}
                  localInfo={localInfoByAgent[a.id]}
                  lifecycle={lifecycleByAgent[a.id]}
                  onSelect={() => switchAgent(a.id)}
                  onLifecycle={(action) => { void controlLocalAgent(a.id, action); }}
                />
              ))
            )}
          </div>

          {/* Sessions list for active agent */}
          {activeAgentId && (
            <div className="session-section">
              <div className="session-section-header">
                <span className="session-section-title">
                  {t("sidebar.sessions")} ({activeSessions.length})
                </span>
                <button
                  className="session-new-btn"
                  onClick={handleNewSession}
                  disabled={!canCreateSession}
                  title={t("sidebar.newSession")}
                >
                  <Icon name="plus" size={14} />
                </button>
              </div>
              <div className="session-list">
                {sessionListState?.loading ? (
                  <div className="session-list-status">{t("sidebar.loadingSessions")}</div>
                ) : activeSessions.length === 0 ? (
                  <div className="session-list-status">{t("sidebar.noSessionsFound")}</div>
                ) : activeSessions.map((session) => (
                  <SessionItem
                    key={session.id}
                    session={session}
                    isActive={session.id === activeSessionId}
                    isCurrent={session.id === activeSessionId}
                    disabled={sessionBusy}
                    isWorking={Boolean(sendingByConversation[`${activeAgentId}\u0000${session.id}`])}
                    unreadCount={unreadByConversation[`${activeAgentId}\u0000${session.id}`] || 0}
                    onClick={() => { void switchSession(session.id); }}
                  />
                ))}
                {sessionListState?.error && (
                  <button className="session-load-more error" onClick={() => { void searchSessions(""); }}>
                    {t("sidebar.retrySessions")}
                  </button>
                )}
                {sessionListState?.hasMore && !sessionListState.loading && !sessionListState.error && (
                  <button
                    className="session-load-more"
                    disabled={sessionListState.loadingMore}
                    onClick={() => { void loadMoreSessions(); }}
                  >
                    {sessionListState.loadingMore ? t("sidebar.loadingSessions") : t("sidebar.loadMoreSessions")}
                  </button>
                )}
              </div>
            </div>
          )}

          <SidebarFooter userName={displayName} onSettings={() => openSettingsCenter("accounts")} />
        </>
      )}

      {/* Collapsed footer */}
      {collapsed && (
        <div className="sidebar-collapsed-footer">
          <div className="sidebar-footer-avatar" title={displayName}>
            {displayName.charAt(0)}
          </div>
        </div>
      )}
      {addDialogOpen && <AddAgentDialog onClose={() => setAddDialogOpen(false)} />}
    </div>
  );
}

// ── Agent item ──

function AgentItem({
  agent,
  isActive,
  connection,
  isWorking,
  unreadCount,
  localOnline,
  localInfo,
  lifecycle,
  onSelect,
  onLifecycle,
}: {
  agent: AgentEntry;
  isActive: boolean;
  connection: import("../../store").ConnectionState | undefined;
  isWorking: boolean;
  unreadCount: number;
  localOnline?: boolean;
  localInfo?: import("../../types").LocalAgentInfo;
  lifecycle?: import("../../store").AgentLifecycleState;
  onSelect: () => void;
  onLifecycle: (action: import("../../types").AgentLifecycleAction) => void;
}) {
  const { t } = useTranslation();
  const status = connection?.status || "disconnected";
  const statusClass = isWorking && status === "connected"
    ? "working"
    : status === "connected"
      ? "connected"
      : status === "connecting"
        ? "connecting"
        : "disconnected";
  const lifecycleBusy = lifecycle && !["idle", "error"].includes(lifecycle.status);
  const lifecycleLabel = lifecycle?.status === "starting"
    ? t("sidebar.agentStarting")
    : lifecycle?.status === "stopping"
      ? t("sidebar.agentStopping")
      : lifecycle?.status === "restarting"
        ? t("sidebar.agentRestarting")
        : "";

  return (
    <div
      className={`agent-item ${isActive ? "active" : ""} ${unreadCount > 0 ? "unread" : ""}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
      aria-current={isActive ? "true" : undefined}
    >
      <div className="agent-avatar">{agent.name.charAt(0)}</div>
      <div className="agent-info">
        <span className="agent-name">{agent.name}</span>
        <span className="agent-host">
          {lifecycleBusy
            ? lifecycleLabel
            : isWorking
              ? t("sidebar.agentWorking")
            : localOnline === false
              ? t("sidebar.agentOffline")
              : localOnline === true && status !== "connected"
                ? t("sidebar.agentAvailable")
                : `${agent.host}:${agent.port}${localInfo?.pid ? ` · PID ${localInfo.pid}` : ""}`}
        </span>
      </div>
      {agent.source === "local" && (
        <div className="agent-lifecycle-actions">
          {lifecycleBusy ? (
            <Icon name="refresh" size={13} className="agent-lifecycle-spinner" />
          ) : localOnline ? (
            <>
              <button
                className="agent-lifecycle-btn"
                onClick={(event) => { event.stopPropagation(); onLifecycle("restart"); }}
                title={t("sidebar.restartAgent")}
              >
                <Icon name="refresh" size={13} />
              </button>
              <button
                className="agent-lifecycle-btn danger"
                onClick={(event) => { event.stopPropagation(); onLifecycle("stop"); }}
                title={t("sidebar.stopAgent")}
              >
                <Icon name="power" size={13} />
              </button>
            </>
          ) : (
            <button
              className="agent-lifecycle-btn start"
              onClick={(event) => { event.stopPropagation(); onLifecycle(localInfo?.pid ? "restart" : "start"); }}
              title={localInfo?.pid ? t("sidebar.restartAgent") : t("sidebar.startAgent")}
            >
              <Icon name={localInfo?.pid ? "refresh" : "play"} size={13} />
            </button>
          )}
        </div>
      )}
      <span
        className={`agent-status-dot ${localOnline === true && status === "disconnected" ? "available" : statusClass}`}
        title={lifecycle?.status === "error"
          ? lifecycle.error
          : isWorking
          ? t("sidebar.agentWorking")
          : localOnline === false
            ? t("sidebar.agentOffline")
            : localOnline === true && status !== "connected"
              ? t("sidebar.agentAvailable")
              : status}
      />
      {unreadCount > 0 && (
        <span className="agent-unread-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
      )}
    </div>
  );
}

// ── Session item ──

function SessionItem({
  session,
  isActive,
  isCurrent,
  disabled = false,
  isWorking = false,
  unreadCount = 0,
  onClick,
}: {
  session: import("../../types").SessionEntry;
  isActive: boolean;
  isCurrent: boolean;
  disabled?: boolean;
  isWorking?: boolean;
  unreadCount?: number;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const channel = session.channel
    || (session.id.startsWith("feishu-") ? "feishu" : undefined)
    || (session.id.startsWith("dingtalk-") ? "dingtalk" : undefined);
  return (
    <div
      className={`session-item ${isActive ? "active" : ""} ${isCurrent ? "current" : ""} ${disabled ? "disabled" : ""} ${unreadCount > 0 ? "unread" : ""}`}
      onClick={disabled ? undefined : onClick}
      title={disabled ? t("sidebar.sessionSwitchBlocked") : session.name}
      onKeyDown={(event) => {
        if (disabled || isCurrent) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      }}
      role="button"
      tabIndex={disabled || isCurrent ? -1 : 0}
      aria-current={isCurrent ? "page" : undefined}
    >
      <span className="session-item-name">
        {session.name}
      </span>
      <span className="session-item-status">
        {channel === "feishu" && (
          <span className="session-channel-mark feishu" title={t("channelUi.feishu")}>飞</span>
        )}
        {channel === "dingtalk" && (
          <span className="session-channel-mark dingtalk" title={t("channelUi.dingtalk")}>钉</span>
        )}
        <span className="session-item-meta">{formatSessionMeta(session)}</span>
        {isWorking && <span className="session-working-dot" title={t("sidebar.agentWorking")} />}
        {unreadCount > 0 && (
          <span className="session-unread-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
        )}
      </span>
    </div>
  );
}

function formatSessionMeta(session: import("../../types").SessionEntry): string {
  const timestamp = session.updatedAt || session.createdAt;
  const date = new Date(timestamp);
  const formattedDate = date.toLocaleDateString([], {
    month: "2-digit",
    day: "2-digit",
  });
  return session.messageCount === undefined
    ? formattedDate
    : `${formattedDate} · ${session.messageCount}`;
}
