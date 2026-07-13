import { useTranslation } from "react-i18next";
import { Button } from "../ui";

interface SidebarFooterProps {
  userName: string;
  onSettings?: () => void;
  onNotifications?: () => void;
}

export function SidebarFooter({ userName, onSettings, onNotifications }: SidebarFooterProps) {
  const { t } = useTranslation();
  return (
    <div className="sidebar-footer">
      <div className="sidebar-footer-avatar">{userName[0] || "?"}</div>
      <span className="sidebar-footer-name">{userName}</span>
      <div className="sidebar-footer-actions">
        <Button variant="ghost" size="icon-md" icon="bell" onClick={onNotifications} title={t("sidebar.notifications")} />
        <Button variant="ghost" size="icon-md" icon="settings" onClick={onSettings} title={t("sidebar.settings")} />
      </div>
    </div>
  );
}
