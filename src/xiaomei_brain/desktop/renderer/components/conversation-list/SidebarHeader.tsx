import { useDesktopInfo } from "../../desktop-info";

export function SidebarHeader() {
  const desktopInfo = useDesktopInfo();
  return (
    <div className="sidebar-header">
      <div className="sidebar-logo-row">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">小</div>
          <span className="sidebar-logo-text">xiaomei-brain</span>
        </div>
        <span className="sidebar-version-badge">v{desktopInfo?.version || "…"}</span>
      </div>
    </div>
  );
}
