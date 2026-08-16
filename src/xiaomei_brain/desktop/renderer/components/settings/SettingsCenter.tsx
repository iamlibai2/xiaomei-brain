import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DesktopSettings } from "../../types";
import { useCoreStore } from "../../store";
import { IdentitySettingsDialog } from "../IdentitySettingsDialog";
import { Button, Icon, type IconName } from "../ui";
import { AgentManagementPanel } from "./AgentManagementPanel";
import { AgentOverviewPanel } from "./AgentOverviewPanel";
import { AgentRhythmSettingsPanel } from "./AgentRhythmSettingsPanel";
import { ConversationUsageSettingsPanel } from "./ConversationUsageSettingsPanel";
import { ContextControlPanel } from "../ContextControlPanel";
import { ChannelSettingsPanel } from "./ChannelSettingsPanel";
import { CapabilitySettingsPanel } from "./CapabilitySettingsPanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";
import { MediaServiceSettingsPanel } from "./MediaServiceSettingsPanel";
import { SearchServiceSettingsPanel } from "./SearchServiceSettingsPanel";
import { SystemSettingsPanel } from "./SystemSettingsPanel";
import { LocalAIRuntimePanel } from "./LocalAIRuntimePanel";
import { ExecutionEnvironmentSettingsPanel } from "./ExecutionEnvironmentSettingsPanel";
import { SETTINGS_EVENT, type SettingsSection } from "./events";

const DESKTOP_NAVIGATION: Array<{
  id: SettingsSection;
  labelKey: string;
  descriptionKey: string;
  icon: IconName;
}> = [
  { id: "agents", labelKey: "settings.agents.label", descriptionKey: "settings.agents.description", icon: "robot" },
  { id: "accounts", labelKey: "settings.accounts.label", descriptionKey: "settings.accounts.description", icon: "shield" },
  { id: "local-ai", labelKey: "settings.localAi.label", descriptionKey: "settings.localAi.description", icon: "sparkles" },
  { id: "system", labelKey: "settings.system.label", descriptionKey: "settings.system.description", icon: "settings" },
];

const AGENT_NAVIGATION: Array<{
  id: SettingsSection;
  labelKey: string;
  descriptionKey: string;
  icon: IconName;
}> = [
  { id: "overview", labelKey: "settings.overview.label", descriptionKey: "settings.overview.description", icon: "info" },
  { id: "rhythm", labelKey: "settings.rhythm.label", descriptionKey: "settings.rhythm.description", icon: "clock" },
  { id: "conversation", labelKey: "settings.conversation.label", descriptionKey: "settings.conversation.description", icon: "chart-bar" },
  { id: "context", labelKey: "settings.context.label", descriptionKey: "settings.context.description", icon: "file-text" },
  { id: "capabilities", labelKey: "settings.capabilities.label", descriptionKey: "settings.capabilities.description", icon: "file-text" },
  { id: "models", labelKey: "settings.models.label", descriptionKey: "settings.models.description", icon: "sparkles" },
  { id: "media", labelKey: "settings.media.label", descriptionKey: "settings.media.description", icon: "image" },
  { id: "search", labelKey: "settings.search.label", descriptionKey: "settings.search.description", icon: "search" },
  { id: "execution", labelKey: "settings.execution.label", descriptionKey: "settings.execution.description", icon: "terminal" },
  { id: "channels", labelKey: "settings.channels.label", descriptionKey: "settings.channels.description", icon: "bell" },
];

const AGENT_SECTIONS = new Set<SettingsSection>(["overview", "rhythm", "conversation", "context", "capabilities", "models", "media", "search", "execution", "channels"]);

export function SettingsCenter() {
  const { t, i18n } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const localInfoByAgent = useCoreStore((state) => state.localInfoByAgent);
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<SettingsSection>("agents");
  const [settingsAgentId, setSettingsAgentId] = useState<string | null>(null);
  const [settingsTarget, setSettingsTarget] = useState("");

  const settingsAgent = agents.find((agent) => agent.id === settingsAgentId);
  const connected = Boolean(
    settingsAgentId && connectionByAgent[settingsAgentId]?.status === "connected",
  );

  useEffect(() => {
    const handleOpen = (event: Event) => {
      const detail = (
        event as CustomEvent<{ section?: SettingsSection; agentId?: string; target?: string }>
      ).detail;
      const nextSection = detail?.section || "agents";
      setSettingsTarget(detail?.target || "");
      if (AGENT_SECTIONS.has(nextSection)) {
        const targetAgentId = detail?.agentId || activeAgentId;
        if (targetAgentId) {
          setSettingsAgentId(targetAgentId);
          setSection(nextSection);
        } else {
          setSettingsAgentId(null);
          setSection("agents");
        }
      } else {
        if (nextSection === "agents") setSettingsAgentId(null);
        setSection(nextSection);
      }
      setOpen(true);
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener(SETTINGS_EVENT, handleOpen);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener(SETTINGS_EVENT, handleOpen);
      window.removeEventListener("keydown", handleKey);
    };
  }, [activeAgentId]);

  useEffect(() => {
    if (settingsAgentId && !agents.some((agent) => agent.id === settingsAgentId)) {
      setSettingsAgentId(null);
      setSection("agents");
    }
  }, [agents, settingsAgentId]);

  if (!open) return null;

  function openAgentSettings(agentId: string) {
    setSettingsAgentId(agentId);
    setSection("overview");
    setSettingsTarget("");
  }

  function openAgentList() {
    setSettingsAgentId(null);
    setSection("agents");
    setSettingsTarget("");
  }

  function navigateAgentSection(nextSection: SettingsSection, target = "") {
    setSection(nextSection);
    setSettingsTarget(target);
  }

  return (
    <div className="settings-center-backdrop" onMouseDown={() => setOpen(false)}>
      <section
        className="settings-center"
        role="dialog"
        aria-modal="true"
          aria-label={t("settings.title")}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings-center-header">
          <div>
            <h2>{t("settings.title")}</h2>
            <p>{t("settings.description")}</p>
          </div>
          <button type="button" aria-label={t("settings.close")} onClick={() => setOpen(false)}>
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="settings-center-body">
          <nav className="settings-center-nav" aria-label={t("settings.categories")}>
            <span className="settings-nav-group">{t("settings.desktop")}</span>
            {DESKTOP_NAVIGATION.map((item) => (
              <button
                key={item.id}
                type="button"
                className={section === item.id && !settingsAgentId ? "active" : ""}
                onClick={() => {
                  if (item.id === "agents") {
                    openAgentList();
                  } else {
                    setSettingsAgentId(null);
                    setSection(item.id);
                    setSettingsTarget("");
                  }
                }}
              >
                <Icon name={item.icon} size={17} />
                <span>
                  <strong>{t(item.labelKey)}</strong>
                  <small>{t(item.descriptionKey)}</small>
                </span>
              </button>
            ))}

            {settingsAgent && (
              <>
                <span className="settings-nav-group">{t("settings.agent")}</span>
                <div className="settings-nav-agent">
                  <span className="settings-nav-avatar">
                    {settingsAgent.name.charAt(0) || "A"}
                  </span>
                  <div>
                    <strong>{settingsAgent.name}</strong>
                    <small className={connected ? "online" : ""}>
                      {settingsAgent.source === "local" ? t("settings.local") : t("settings.remote")}
                      {" · "}
                      {connected ? t("settings.online") : t("settings.disconnected")}
                    </small>
                  </div>
                </div>
                {AGENT_NAVIGATION.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={section === item.id ? "active" : ""}
                    onClick={() => navigateAgentSection(item.id)}
                  >
                    <Icon name={item.icon} size={17} />
                    <span>
                      <strong>{t(item.labelKey)}</strong>
                      <small>{t(item.descriptionKey)}</small>
                    </span>
                  </button>
                ))}
              </>
            )}
          </nav>

          <main className="settings-center-content">
            {settingsAgent && AGENT_SECTIONS.has(section) && (
              <div className="settings-agent-back">
                <Button
                  variant="ghost"
                  size="sm"
                  icon="chevron-left"
                  onClick={openAgentList}
                >
                  {t("settings.backToAgents")}
                </Button>
              </div>
            )}
            {section === "agents" && (
              <AgentManagementPanel
                onConfigure={openAgentSettings}
                onOpenConversation={() => setOpen(false)}
              />
            )}
            {section === "system" && <SystemSettingsPanel />}
            {section === "local-ai" && (
              <LocalAIRuntimePanel language={i18n.language as DesktopSettings["language"]} />
            )}
            {section === "accounts" && (
              <IdentitySettingsDialog embedded onClose={() => setOpen(false)} />
            )}
            {section === "overview" && settingsAgent && (
              <AgentOverviewPanel
                agentId={settingsAgent.id}
                name={settingsAgent.name}
                description={settingsAgent.description || ""}
                address={`${settingsAgent.host}:${settingsAgent.port}`}
                source={settingsAgent.source || "manual"}
                localAgentId={settingsAgent.localAgentId}
                connected={connected}
                pid={localInfoByAgent[settingsAgent.id]?.pid}
                onNavigate={(next) => navigateAgentSection(next)}
              />
            )}
            {section === "models" && settingsAgent && (
              <ModelSettingsPanel agentId={settingsAgent.id} connected={connected} />
            )}
            {section === "rhythm" && settingsAgent && (
              <AgentRhythmSettingsPanel
                agentId={settingsAgent.id}
                connected={connected}
              />
            )}
            {section === "conversation" && settingsAgent && (
              <ConversationUsageSettingsPanel agentId={settingsAgent.id} connected={connected} />
            )}
            {section === "context" && settingsAgent && (
              <ContextControlPanel
                agentId={settingsAgent.id}
                agentName={settingsAgent.name}
                connected={connected}
                embedded
              />
            )}
            {section === "capabilities" && settingsAgent && (
              <CapabilitySettingsPanel
                agentId={settingsAgent.id}
                connected={connected}
                target={section === "capabilities" ? settingsTarget : ""}
                onTargetConsumed={() => setSettingsTarget("")}
                onNavigate={(nextSection, target) => {
                  const next = nextSection as SettingsSection;
                  if (AGENT_SECTIONS.has(next)) navigateAgentSection(next, target);
                }}
              />
            )}
            {section === "media" && settingsAgent && (
              <MediaServiceSettingsPanel
                agentId={settingsAgent.id}
                connected={connected}
              />
            )}
            {section === "search" && settingsAgent && (
              <SearchServiceSettingsPanel
                agentId={settingsAgent.id}
                connected={connected}
                target={settingsTarget}
                onTargetConsumed={() => setSettingsTarget("")}
              />
            )}
            {section === "channels" && settingsAgent && (
              <ChannelSettingsPanel
                agentId={settingsAgent.id}
                agentName={settingsAgent.name}
                connected={connected}
              />
            )}
            {section === "execution" && settingsAgent && (
              <ExecutionEnvironmentSettingsPanel
                agentId={settingsAgent.id}
                connected={connected}
              />
            )}
          </main>
        </div>
      </section>
    </div>
  );
}
