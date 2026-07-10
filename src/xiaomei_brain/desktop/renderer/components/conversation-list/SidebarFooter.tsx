interface SidebarFooterProps {
  userName: string;
  onSettings?: () => void;
  onNotifications?: () => void;
}

export function SidebarFooter({ userName, onSettings, onNotifications }: SidebarFooterProps) {
  return (
    <div className="sidebar-footer">
      <div className="sidebar-footer-avatar">{userName[0] || "?"}</div>
      <span className="sidebar-footer-name">{userName}</span>
      <div className="sidebar-footer-actions">
        <button className="sidebar-icon-btn" onClick={onNotifications} title="通知">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
            <path d="M10 21a2 2 0 0 0 4 0" />
          </svg>
        </button>
        <button className="sidebar-icon-btn" onClick={onSettings} title="设置">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v6m0 10v6M4.22 4.22l4.24 4.24m7.08 7.08 4.24 4.24M1 12h6m10 0h6M4.22 19.78l4.24-4.24m7.08-7.08 4.24-4.24" />
          </svg>
        </button>
      </div>
    </div>
  );
}
