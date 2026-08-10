import { useTranslation } from "react-i18next";
import { Icon, Button } from "../ui";
import { useDesktopInfo } from "../../desktop-info";

interface SidebarTopbarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSearch: () => void;
  onRefresh: () => void;
}

export function SidebarTopbar({ collapsed, onToggleCollapse, onSearch, onRefresh }: SidebarTopbarProps) {
  const { t } = useTranslation();
  const desktopInfo = useDesktopInfo();
  return (
    <div className={`sidebar-topbar ${collapsed ? "sidebar-topbar-collapsed" : ""}`}>
      {collapsed ? (
        <Button
          variant="ghost"
          size="icon-sm"
          icon="sidebar-panel-left"
          iconSize={18}
          onClick={onToggleCollapse}
          title={`${t("sidebar.expand")} (Ctrl+B)`}
        />
      ) : (
        <>
          <div className="sidebar-logo-row">
            <span className="sidebar-logo-text">xiaomei-brain</span>
            <span className="sidebar-version-badge">v{desktopInfo?.version || "…"}</span>
          </div>
          <div className="sidebar-topbar-actions">
            <Button variant="ghost" size="icon-md" icon="refresh" onClick={onRefresh} title={t("sidebar.refresh")} />
            <Button variant="ghost" size="icon-md" icon="search" onClick={onSearch} title={t("sidebar.search")} />
            <Button variant="ghost" size="icon-md" icon="sidebar-panel-right" onClick={onToggleCollapse} title={`${t("sidebar.collapse")} (Ctrl+B)`} />
          </div>
        </>
      )}
    </div>
  );
}
