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

export function ConversationList({ userName = "李白" }: ConversationListProps) {
  const [collapsed, setCollapsed] = useState(false);
  const activeNav = useCoreStore((s) => s.activeNav);
  const setActiveNav = useCoreStore((s) => s.setActiveNav);
  const agentName = useCoreStore((s) => s.connection.agentName);
  const sessionId = useCoreStore((s) => s.connection.sessionId);
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
            <CollapsibleSection title="任务" count={sessionId ? 1 : 0}>
              {sessionId ? (
                <div className="task-item task-item-active">
                  <span className="task-item-name">
                    {agentName || "当前会话"}
                    <span className="task-item-active-dot" />
                  </span>
                  <span className="task-item-time">刚刚</span>
                </div>
              ) : (
                <div className="task-item" style={{ color: "var(--ui-color-text-disabled)", cursor: "default" }}>
                  <span className="task-item-name">暂无任务</span>
                </div>
              )}
            </CollapsibleSection>
            <CollapsibleSection title="空间" count={0}>
              <div className="task-item" style={{ color: "var(--ui-color-text-disabled)", cursor: "default" }}>
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
