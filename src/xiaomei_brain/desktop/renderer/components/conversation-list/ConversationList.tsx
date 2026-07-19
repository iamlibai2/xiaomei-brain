import { useState } from "react";
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
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const messagesByAgent = useCoreStore((s) => s.messagesByAgent);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const setTerminalOpen = useCoreStore((s) => s.setTerminalOpen);
  const unreadByAgent = useCoreStore((s) => s.unreadByAgent);
  const sendingByAgent = useCoreStore((s) => s.sendingByAgent);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);

  const displayName = userId || t("sidebar.defaultUserName");

  // Add-agent form state
  const [addHost, setAddHost] = useState("localhost");
  const [addPort, setAddPort] = useState("19767");
  const [addToken, setAddToken] = useState("");

  function handleAddAgent() {
    const port = parseInt(addPort) || 19767;
    addAgent(addHost, port, addToken);
    setShowAddForm(false);
    setAddHost("localhost");
    setAddPort("19767");
    setAddToken("");
  }

  function handleNewSession() {
    newSession();
  }

  const activeSessions = activeAgentId ? (sessionsByAgent[activeAgentId] || []) : [];
  const isConnected = activeAgentId ? connectionByAgent[activeAgentId]?.status === "connected" : false;
  const hasCurrentChat = activeAgentId && (messagesByAgent[activeAgentId]?.length > 0 || isConnected);

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
                  onClick={() => switchAgent(a.id)}
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
                onSelect={() => switchAgent(a.id)}
              />
            ))
          )}

          {/* Sessions list for active agent */}
          {activeAgentId && (
            <div className="session-section" style={{ flex: 1, minHeight: 0, overflow: "hidden auto", display: "flex", flexDirection: "column" }}>
              <div className="session-section-header">
                <span className="session-section-title">
                  {t("sidebar.sessions")} ({activeSessions.length + (hasCurrentChat ? 1 : 0)})
                </span>
                <button
                  className="session-new-btn"
                  onClick={handleNewSession}
                  disabled={sendingByAgent[activeAgentId] || false}
                  title={t("sidebar.newSession")}
                >
                  <Icon name="plus" size={14} />
                </button>
              </div>
              <div className="session-list">
                {/* Current chat (always shown when active agent has messages or is connected) */}
                <SessionItem
                  name={t("sidebar.currentSession")}
                  isActive={!activeSessionId}
                  isCurrent={true}
                  onClick={() => {}}
                />
                {activeSessions.map((s) => (
                  <SessionItem
                    key={s.id}
                    name={s.name}
                    isActive={s.id === activeSessionId}
                    isCurrent={false}
                    disabled={sendingByAgent[activeAgentId] || false}
                    onClick={() => switchSession(s.id)}
                  />
                ))}
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
  onSelect,
}: {
  agent: AgentEntry;
  isActive: boolean;
  connection: import("../../store").ConnectionState | undefined;
  isWorking: boolean;
  unreadCount: number;
  localOnline?: boolean;
  onSelect: () => void;
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

  return (
    <div
      className={`agent-item ${isActive ? "active" : ""}`}
      onClick={onSelect}
    >
      <div className="agent-avatar">{agent.name.charAt(0)}</div>
      <div className="agent-info">
        <span className="agent-name">{agent.name}</span>
        <span className="agent-host">
          {isWorking
            ? t("sidebar.agentWorking")
            : localOnline === false
              ? t("sidebar.agentOffline")
              : localOnline === true && status !== "connected"
                ? t("sidebar.agentAvailable")
                : `${agent.host}:${agent.port}`}
        </span>
      </div>
      <span
        className={`agent-status-dot ${localOnline === true && status === "disconnected" ? "available" : statusClass}`}
        title={isWorking
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
  name,
  isActive,
  isCurrent,
  disabled = false,
  onClick,
}: {
  name: string;
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
        {name}
      </span>
    </div>
  );
}
