import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore, AgentEntry } from "../../store";
import { Icon, Button } from "../ui";
import { SidebarTopbar } from "./SidebarTopbar";
import { NewTaskButton } from "./NewTaskButton";
import { CollapsibleSection } from "./CollapsibleSection";
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
  const newTask = useCoreStore((s) => s.newTask);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const setTerminalOpen = useCoreStore((s) => s.setTerminalOpen);
  const unreadByAgent = useCoreStore((s) => s.unreadByAgent);

  const displayName = userId || t("sidebar.defaultUserName");

  // Add-agent form state
  const [addHost, setAddHost] = useState("localhost");
  const [addPort, setAddPort] = useState("19767");
  const [addToken, setAddToken] = useState("");

  const activeConn = activeAgentId ? connectionByAgent[activeAgentId] : undefined;
  const isConnected = activeConn?.status === "connected";
  const agentName = activeConn?.agentName || "";

  function handleAddAgent() {
    const port = parseInt(addPort) || 19767;
    addAgent(addHost, port, addToken);
    setShowAddForm(false);
    setAddHost("localhost");
    setAddPort("19767");
    setAddToken("");
  }

  function handleNewTask() {
    newTask();
  }

  return (
    <div className={`conversation-list ${collapsed ? "collapsed" : ""}`}>
      <SidebarTopbar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
        onSearch={() => {}}
        onRefresh={() => {}}
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
                  className={`sidebar-collapsed-agent-btn ${isActive ? "active" : ""}`}
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
          <NewTaskButton onClick={handleNewTask} />

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
                unreadCount={unreadByAgent[a.id] || 0}
                onSelect={() => switchAgent(a.id)}
              />
            ))
          )}

          {/* Task & Workspace sections */}
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <CollapsibleSection title={t("sidebar.task")} count={isConnected ? 1 : 0}>
              {isConnected ? (
                <div className="task-item task-item-active">
                  <span className="task-item-name">
                    {agentName || t("sidebar.currentSession")}
                    <span className="task-item-active-dot" />
                  </span>
                  <span className="task-item-time">{t("sidebar.justNow")}</span>
                </div>
              ) : (
                <div className="task-item" style={{ color: "var(--ui-color-text-disabled)", cursor: "default" }}>
                  <span className="task-item-name">{t("sidebar.noTask")}</span>
                </div>
              )}
            </CollapsibleSection>
            <CollapsibleSection title={t("sidebar.space")} count={0}>
              <div className="task-item" style={{ color: "var(--ui-color-text-disabled)", cursor: "default" }}>
                <span className="task-item-name">{t("sidebar.noSpace")}</span>
              </div>
            </CollapsibleSection>
          </div>

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
  unreadCount,
  onSelect,
}: {
  agent: AgentEntry;
  isActive: boolean;
  connection: import("../../store").ConnectionState | undefined;
  unreadCount: number;
  onSelect: () => void;
}) {
  const status = connection?.status || "disconnected";
  const statusClass = status === "connected" ? "connected" : status === "connecting" ? "connecting" : "disconnected";

  return (
    <div
      className={`agent-item ${isActive ? "active" : ""}`}
      onClick={onSelect}
    >
      <div className="agent-avatar">{agent.name.charAt(0)}</div>
      <div className="agent-info">
        <span className="agent-name">{agent.name}</span>
        <span className="agent-host">{agent.host}:{agent.port}</span>
      </div>
      <span className={`agent-status-dot ${statusClass}`} />
      {unreadCount > 0 && (
        <span className="agent-unread-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
      )}
    </div>
  );
}
