import { useTranslation } from "react-i18next";
import { Button } from "../ui";
import type { AgentStateSnapshot } from "../../store";

interface ChatTopbarProps {
  taskName: string;
  onToggleRightPanel?: () => void;
  rightPanelOpen?: boolean;
  onOpenAgentSettings?: () => void;
  agentState?: AgentStateSnapshot;
  speaking?: boolean;
  activitySummary?: string;
}

export function ChatTopbar({
  taskName,
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
    ? t("home.livingDreaming")
    : speaking
      ? t("home.speaking")
    : agentState?.focusSummary
      || activitySummary
      || (agentState ? livingStateName(agentState.living, t) : "");
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
          title={t("home.agentSettings")}
        />
        {!rightPanelOpen && (
          <Button
            variant="ghost"
            size="icon-md"
            icon="sidebar-panel-right"
            className="right-panel-toggle"
            onClick={onToggleRightPanel}
            aria-pressed={false}
            title={`${t("home.toggleRightPanel")} (Ctrl+Shift+B)`}
          />
        )}
      </div>
    </div>
  );
}

function livingStateName(state: AgentStateSnapshot["living"], t: (key: string) => string): string {
  return {
    dormant: t("home.livingDormant"),
    waking: t("home.livingWaking"),
    awake: t("home.livingAwake"),
    idle: t("home.agentReady"),
    working: t("sidebar.agentWorking"),
    sleeping: t("home.livingSleeping"),
    dreaming: t("home.livingDreaming"),
  }[state];
}
