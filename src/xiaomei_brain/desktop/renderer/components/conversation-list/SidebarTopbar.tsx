interface SidebarTopbarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSearch: () => void;
  onRefresh: () => void;
}

export function SidebarTopbar({ collapsed, onToggleCollapse, onSearch, onRefresh }: SidebarTopbarProps) {
  return (
    <div className={`sidebar-topbar ${collapsed ? "sidebar-topbar-collapsed" : ""}`}>
      {collapsed ? (
        <button className="sidebar-expand-btn" onClick={onToggleCollapse} title="展开侧栏">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="1" y="2" width="16" height="14" rx="2" />
            <line x1="4" y1="2" x2="4" y2="16" />
            <line x1="10" y1="7" x2="7" y2="9" />
            <line x1="10" y1="11" x2="7" y2="9" />
          </svg>
        </button>
      ) : (
        <>
          <div className="sidebar-logo-row">
            <span className="sidebar-logo-text">xiaomei-brain</span>
            <span className="sidebar-version-badge">v1.0.0</span>
          </div>
          <div className="sidebar-topbar-actions">
            <button className="sidebar-icon-btn" onClick={onRefresh} title="刷新">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 2v6h6" />
                <path d="M21 12A9 9 0 0 0 6 5.3L3 8" />
                <path d="M21 22v-6h-6" />
                <path d="M3 12a9 9 0 0 0 15 6.7l3-2.7" />
              </svg>
            </button>
            <button className="sidebar-icon-btn" onClick={onSearch} title="搜索">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
            </button>
            <button className="sidebar-icon-btn" onClick={onToggleCollapse} title="折叠侧栏">
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="1" y="2" width="16" height="14" rx="2" />
                <line x1="4" y1="2" x2="4" y2="16" />
                <line x1="7" y1="7" x2="10" y2="9" />
                <line x1="7" y1="11" x2="10" y2="9" />
              </svg>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
