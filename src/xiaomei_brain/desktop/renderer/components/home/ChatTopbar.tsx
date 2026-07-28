import { useTranslation } from "react-i18next";
import { Button } from "../ui";
import type { AgentStateSnapshot } from "../../store";

interface ChatTopbarProps {
  taskName: string;
  onSearch?: () => void;
  onToggleRightPanel?: () => void;
  rightPanelOpen?: boolean;
  onOpenAgentSettings?: () => void;
  agentState?: AgentStateSnapshot;
  activitySummary?: string;
}

export function ChatTopbar({
  taskName,
  onSearch,
  onToggleRightPanel,
  rightPanelOpen,
  onOpenAgentSettings,
  agentState,
  activitySummary,
}: ChatTopbarProps) {
  const { t } = useTranslation();

  return (
    <div className="chat-topbar">
      <div className="chat-topbar-left">
        <span className="chat-topbar-title">{taskName}</span>
        {(agentState || activitySummary) && (
          <span className={`chat-topbar-agent-state ${activitySummary ? "working" : agentState?.living || ""}`}>
            {agentState?.focusSummary || activitySummary || (agentState ? livingStateName(agentState.living) : "")}
          </span>
        )}
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

function livingStateName(state: AgentStateSnapshot["living"]): string {
  return {
    dormant: "休眠",
    waking: "正在苏醒",
    awake: "清醒",
    idle: "空闲",
    working: "工作中",
    sleeping: "睡眠中",
    dreaming: "做梦中",
  }[state];
}
