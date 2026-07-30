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
  speaking?: boolean;
  activitySummary?: string;
}

export function ChatTopbar({
  taskName,
  onSearch,
  onToggleRightPanel,
  rightPanelOpen,
  onOpenAgentSettings,
  agentState,
  speaking,
  activitySummary,
}: ChatTopbarProps) {
  const { t } = useTranslation();
  const isDreaming = agentState?.living === "dreaming";
  const stateText = isDreaming
    ? "梦境中"
    : speaking
      ? "正在说话"
    : agentState?.focusSummary
      || activitySummary
      || (agentState ? livingStateName(agentState.living) : "");
  const stateClass = isDreaming
    ? "dreaming"
    : speaking
      ? "speaking"
    : activitySummary ? "working" : agentState?.living || "";

  return (
    <div className="chat-topbar">
      <div className="chat-topbar-left">
        <span className="chat-topbar-title">{taskName}</span>
        {(agentState || activitySummary || speaking) && (
          <span className={`chat-topbar-agent-state ${stateClass}`}>
            {stateText}
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
        {!rightPanelOpen && (
          <Button
            variant="ghost"
            size="icon-md"
            icon="sidebar-panel-right"
            className="right-panel-toggle"
            onClick={onToggleRightPanel}
            aria-pressed={false}
            title={t("home.toggleRightPanel")}
          />
        )}
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
    dreaming: "梦境中",
  }[state];
}
