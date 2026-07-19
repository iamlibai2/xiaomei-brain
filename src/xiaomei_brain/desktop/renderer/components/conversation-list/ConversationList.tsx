import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore, AgentEntry } from "../../store";
import { Icon, Button } from "../ui";
import { SidebarTopbar } from "./SidebarTopbar";
import { SidebarFooter } from "./SidebarFooter";

export function ConversationList() {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);

  const agents = useCoreStore((s) => s.agents);
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const connectionByAgent = useCoreStore((s) => s.connectionByAgent);
  const userId = useCoreStore((s) => s.userId);
  const switchAgent = useCoreStore((s) => s.switchAgent);
  const addAgent = useCoreStore((s) => s.addAgent);
  const newSession = useCoreStore((s) => s.newSession);
  const switchSession = useCoreStore((s) => s.switchSession);
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);
  const sessionListByAgent = useCoreStore((s) => s.sessionListByAgent);
  const searchSessions = useCoreStore((s) => s.searchSessions);
  const loadMoreSessions = useCoreStore((s) => s.loadMoreSessions);
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const setTerminalOpen = useCoreStore((s) => s.setTerminalOpen);
  const unreadByAgent = useCoreStore((s) => s.unreadByAgent);
  const sendingByAgent = useCoreStore((s) => s.sendingByAgent);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);
  const localInfoByAgent = useCoreStore((s) => s.localInfoByAgent);
  const lifecycleByAgent = useCoreStore((s) => s.lifecycleByAgent);
  const controlLocalAgent = useCoreStore((s) => s.controlLocalAgent);

  const displayName = userId || t("sidebar.defaultUserName");

  // Add-agent form state
  const [addHost, setAddHost] = useState("localhost");
  const [addPort, setAddPort] = useState("19767");
  const [addToken, setAddToken] = useState("");
  const [sessionQuery, setSessionQuery] = useState("");

  function handleAddAgent() {
    const port = parseInt(addPort) || 19767;
    addAgent(addHost, port, addToken);
    setShowAddForm(false);
    setAddHost("localhost");
    setAddPort("19767");
    setAddToken("");
  }

  function handleNewSession() {
    void newSession();
  }

  const activeSessions = activeAgentId ? (sessionsByAgent[activeAgentId] || []) : [];
  const sessionListState = activeAgentId ? sessionListByAgent[activeAgentId] : undefined;
  const sessionBusy = activeAgentId
    ? Boolean(sendingByAgent[activeAgentId] || connectionByAgent[activeAgentId]?.status === "connecting")
    : false;

  useEffect(() => {
    setSessionQuery(sessionListState?.query || "");
  }, [activeAgentId]);

  useEffect(() => {
    if (!activeAgentId || sessionQuery.trim() === (sessionListState?.query || "")) return;
    const timer = window.setTimeout(() => { void searchSessions(sessionQuery); }, 250);
    return () => window.clearTimeout(timer);
  }, [activeAgentId, sessionQuery, sessionListState?.query, searchSessions]);

  const groupedSessions = useMemo(
    () => groupSessions(activeSessions, activeSessionId),
    [activeSessions, activeSessionId],
  );

  return (
    <div className={`conversation-list ${collapsed ? "collapsed" : ""}`}>
      <SidebarTopbar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
        onSearch={() => {}}
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
                </button>
              );
            })}
            <button
              className="sidebar-collapsed-agent-btn"
              onClick={() => { setCollapsed(false); setShowAddForm(true); }}
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
              onClick={() => setShowAddForm(!showAddForm)}
              title={t("sidebar.addAgent")}
            >
              <Icon name="plus" size={16} />
            </button>
          </div>

          {/* Add agent form */}
          {showAddForm && (
            <div className="add-agent-form">
              <input
                value={addHost}
                onChange={(e) => setAddHost(e.target.value)}
                placeholder={t("sidebar.addAgentHost")}
              />
              <input
                value={addPort}
                onChange={(e) => setAddPort(e.target.value)}
                placeholder={t("sidebar.addAgentPort")}
              />
              <input
                value={addToken}
                onChange={(e) => setAddToken(e.target.value)}
                placeholder={t("sidebar.addAgentToken")}
                type="password"
              />
              <div className="add-agent-form-buttons">
                <Button variant="ghost" size="icon-sm" onClick={() => setShowAddForm(false)}>
                  {t("sidebar.addAgentCancel")}
                </Button>
                <Button variant="primary" size="icon-sm" onClick={handleAddAgent}>
                  {t("sidebar.addAgentSubmit")}
                </Button>
              </div>
            </div>
          )}

          {/* Agent list */}
          {agents.length === 0 ? (
            <div className="agent-item" style={{ color: "var(--ui-color-text-disabled)", cursor: "default" }}>
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

          {/* Sessions list for active agent */}
          {activeAgentId && (
            <div className="session-section" style={{ flex: 1, minHeight: 0, overflow: "hidden auto", display: "flex", flexDirection: "column" }}>
              <div className="session-section-header">
                <span className="session-section-title">
                  {t("sidebar.sessions")} ({activeSessions.length})
                </span>
                <button
                  className="session-new-btn"
                  onClick={handleNewSession}
                  disabled={sessionBusy}
                  title={t("sidebar.newSession")}
                >
                  <Icon name="plus" size={14} />
                </button>
              </div>
              <div className="session-search">
                <Icon name="search" size={13} />
                <input
                  value={sessionQuery}
                  onChange={(event) => setSessionQuery(event.target.value)}
                  placeholder={t("sidebar.searchSessions")}
                  aria-label={t("sidebar.searchSessions")}
                />
              </div>
              <div className="session-list">
                {sessionListState?.loading ? (
                  <div className="session-list-status">{t("sidebar.loadingSessions")}</div>
                ) : groupedSessions.length === 0 ? (
                  <div className="session-list-status">{t("sidebar.noSessionsFound")}</div>
                ) : groupedSessions.map((group) => (
                  <div className="session-group" key={group.key}>
                    <div className="session-group-label">{t(`sidebar.${group.key}`)}</div>
                    {group.sessions.map((session) => (
                      <SessionItem
                        key={session.id}
                        session={session}
                        isActive={session.id === activeSessionId}
                        isCurrent={session.id === activeSessionId}
                        disabled={sessionBusy}
                        onClick={() => { void switchSession(session.id); }}
                      />
                    ))}
                  </div>
                ))}
                {sessionListState?.error && (
                  <button className="session-load-more error" onClick={() => { void searchSessions(sessionQuery); }}>
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

          <SidebarFooter userName={displayName} />
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
      className={`agent-item ${isActive ? "active" : ""}`}
      onClick={onSelect}
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
              onClick={(event) => { event.stopPropagation(); onLifecycle("start"); }}
              title={t("sidebar.startAgent")}
            >
              <Icon name="play" size={13} />
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
  onClick,
}: {
  session: import("../../types").SessionEntry;
  isActive: boolean;
  isCurrent: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <div
      className={`session-item ${isActive ? "active" : ""} ${isCurrent ? "current" : ""} ${disabled ? "disabled" : ""}`}
      onClick={disabled ? undefined : onClick}
      style={{ cursor: isCurrent || disabled ? "default" : "pointer" }}
    >
      <span className="session-item-name">
        {isCurrent && <span className="session-item-dot" />}
        {session.name}
      </span>
      <span className="session-item-meta">{formatSessionMeta(session)}</span>
    </div>
  );
}

function groupSessions(sessions: import("../../types").SessionEntry[], activeSessionId: string | null) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 24 * 60 * 60 * 1000;
  const groups = [
    { key: "currentSession", sessions: sessions.filter((session) => session.id === activeSessionId) },
    { key: "today", sessions: [] as import("../../types").SessionEntry[] },
    { key: "yesterday", sessions: [] as import("../../types").SessionEntry[] },
    { key: "earlier", sessions: [] as import("../../types").SessionEntry[] },
  ];
  for (const session of sessions) {
    if (session.id === activeSessionId) continue;
    const timestamp = session.updatedAt || session.createdAt;
    if (timestamp >= today) groups[1].sessions.push(session);
    else if (timestamp >= yesterday) groups[2].sessions.push(session);
    else groups[3].sessions.push(session);
  }
  return groups.filter((group) => group.sessions.length > 0);
}

function formatSessionMeta(session: import("../../types").SessionEntry): string {
  const timestamp = session.updatedAt || session.createdAt;
  const date = new Date(timestamp);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const time = sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "numeric", day: "numeric" });
  return session.messageCount === undefined ? time : `${time} · ${session.messageCount}`;
}
