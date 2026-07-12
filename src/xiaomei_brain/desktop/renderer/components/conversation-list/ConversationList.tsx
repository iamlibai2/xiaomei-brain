import { useState } from "react";
import { useCoreStore } from "../../store";
import { SidebarTopbar } from "./SidebarTopbar";
import { NewTaskButton } from "./NewTaskButton";
import { NavTabs, NavIcons } from "./NavTabs";
import { CollapsibleSection } from "./CollapsibleSection";
import { SidebarFooter } from "./SidebarFooter";

interface ConversationListProps {
  userName?: string;
}

const navItems = [
  { id: "assistant", label: "助理", icon: NavIcons.assistant },
  { id: "project", label: "项目", icon: NavIcons.project },
  { id: "expert", label: "专家·技能·连接器", icon: NavIcons.expert },
  { id: "automation", label: "自动化", icon: NavIcons.automation },
  { id: "more", label: "更多", icon: NavIcons.more },
];

function formatTime(ts: number): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}天前`;
  return new Date(ts).toLocaleDateString();
}

export function ConversationList({ userName = "李白" }: ConversationListProps) {
  const [collapsed, setCollapsed] = useState(false);
  const activeNav = useCoreStore((s) => s.activeNav);
  const setActiveNav = useCoreStore((s) => s.setActiveNav);
  const sessions = useCoreStore((s) => s.sessions);
  const activeSessionId = useCoreStore((s) => s.activeSessionId);
  const agentName = useCoreStore((s) => s.connection.agentName);
  const loadSessionMessages = useCoreStore((s) => s.loadSessionMessages);
  const newTask = useCoreStore((s) => s.newTask);

  const handleNewTask = () => {
    newTask(agentName || "小美");
  };

  return (
    <div className={`conversation-list ${collapsed ? "collapsed" : ""}`}>
      <SidebarTopbar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed(!collapsed)}
        onSearch={() => {}}
        onRefresh={() => {}}
      />

      {collapsed ? (
        <div className="sidebar-collapsed-body">
          <button className="sidebar-collapsed-icon-btn" onClick={handleNewTask} title="新建任务">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`sidebar-collapsed-icon-btn ${activeNav === item.id ? "active" : ""}`}
              onClick={() => setActiveNav(item.id)}
              title={item.label}
            >
              {item.icon}
            </button>
          ))}
        </div>
      ) : (
        <>
          <NewTaskButton onClick={handleNewTask} />
          <NavTabs items={navItems} onSelect={setActiveNav} />
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <CollapsibleSection title="任务" count={sessions.length}>
              {sessions.map((ses) => (
                <div
                  key={ses.id}
                  className={`task-item ${ses.id === activeSessionId ? "task-item-active" : ""}`}
                  onClick={() => loadSessionMessages(ses.id)}
                >
                  <span className="task-item-name">
                    {ses.agent_name}
                    {ses.id === activeSessionId && <span className="task-item-active-dot" />}
                  </span>
                  <span className="task-item-time">{formatTime(ses.last_active)}</span>
                </div>
              ))}
              {sessions.length === 0 && (
                <div className="task-item" style={{ color: "var(--wb-color-text-disabled)", cursor: "default" }}>
                  <span className="task-item-name">暂无任务</span>
                </div>
              )}
            </CollapsibleSection>
            <CollapsibleSection title="空间" count={0}>
              <div className="task-item" style={{ color: "var(--wb-color-text-disabled)", cursor: "default" }}>
                <span className="task-item-name">暂无空间</span>
              </div>
            </CollapsibleSection>
          </div>
          <SidebarFooter userName={userName} />
        </>
      )}

      {collapsed && (
        <div className="sidebar-collapsed-footer">
          <div className="sidebar-footer-avatar" title={userName}>
            {userName.charAt(0)}
          </div>
        </div>
      )}
    </div>
  );
}
