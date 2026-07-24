import { useTranslation } from "react-i18next";
import { Button } from "../ui";

interface ChatTopbarProps {
  taskName: string;
  onSearch?: () => void;
  onToggleRightPanel?: () => void;
  rightPanelOpen?: boolean;
  onOpenAgentSettings?: () => void;
}

export function ChatTopbar({ taskName, onSearch, onToggleRightPanel, rightPanelOpen, onOpenAgentSettings }: ChatTopbarProps) {
  const { t } = useTranslation();

  return (
    <div className="chat-topbar">
      <div className="chat-topbar-left">
        <span className="chat-topbar-title">{taskName}</span>
      </div>
      <div className="chat-topbar-right">
        <Button
          variant="ghost"
          size="icon-md"
          icon="settings"
          onClick={onOpenAgentSettings}
          title={t("home.agentSettings", "Agent 设置")}
        />
        <Button
          variant="ghost"
          size="icon-md"
          icon="search"
          onClick={onSearch}
          title={t("home.searchInConversation")}
        />
        <Button
          variant="ghost"
          size="icon-md"
          icon={rightPanelOpen ? "sidebar-panel-right" : "sidebar-panel-right"}
          onClick={onToggleRightPanel}
          title={t("home.toggleRightPanel")}
        />
      </div>
    </div>
  );
}
