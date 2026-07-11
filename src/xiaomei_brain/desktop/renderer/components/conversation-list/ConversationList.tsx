import { useState } from "react";
import { useCoreStore } from "../../store";
import { SidebarTopbar } from "./SidebarTopbar";
import { NewTaskButton } from "./NewTaskButton";
import { NavTabs, NavIcons } from "./NavTabs";
import { CollapsibleSection } from "./CollapsibleSection";
import { SidebarFooter } from "./SidebarFooter";

interface TaskItem {
  name: string;
  time: string;
  active?: boolean;
}

interface SpaceItem {
  title: string;
  subtitle: string;
}

interface ConversationListProps {
  userName?: string;
  onNewTask?: () => void;
}

const navItems = [
  { id: "assistant", label: "助理", icon: NavIcons.assistant },
  { id: "project", label: "项目", icon: NavIcons.project },
  { id: "expert", label: "专家·技能·连接器", icon: NavIcons.expert },
  { id: "automation", label: "自动化", icon: NavIcons.automation },
  { id: "more", label: "更多", icon: NavIcons.more },
];

const mockTasks: TaskItem[] = [
  { name: "JSON-RPC 协议讨论", time: "3天前", active: true },
  { name: "代码 Review", time: "昨天" },
  { name: "Python 环境配置", time: "5天前" },
];

const mockSpaces: SpaceItem[] = [
  { title: "xiaomei-brain 开发", subtitle: "3 个任务" },
];

export function ConversationList({ userName = "李白", onNewTask }: ConversationListProps) {
  const [collapsed, setCollapsed] = useState(false);
  const activeNav = useCoreStore((s) => s.activeNav);
  const setActiveNav = useCoreStore((s) => s.setActiveNav);

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
          <button className="sidebar-collapsed-icon-btn" onClick={() => onNewTask?.()} title="新建任务">
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
          <NewTaskButton onClick={() => onNewTask?.()} />
          <NavTabs items={navItems} onSelect={setActiveNav} />
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <CollapsibleSection title="任务" count={mockTasks.length}>
              {mockTasks.map((task, i) => (
                <div key={i} className="task-item">
                  <span className="task-item-name">
                    {task.name}
                    {task.active && <span className="task-item-active-dot" />}
                  </span>
                  <span className="task-item-time">{task.time}</span>
                </div>
              ))}
            </CollapsibleSection>
            <CollapsibleSection title="空间" count={mockSpaces.length}>
              {mockSpaces.map((space, i) => (
                <div key={i} className="space-item">
                  <span className="space-item-title">{space.title}</span>
                  <span className="space-item-subtitle">{space.subtitle}</span>
                </div>
              ))}
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
