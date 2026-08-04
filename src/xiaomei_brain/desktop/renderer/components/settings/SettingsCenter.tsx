import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DesktopSettings } from "../../types";
import { useCoreStore } from "../../store";
import { IdentitySettingsDialog } from "../IdentitySettingsDialog";
import { Button, Icon, type IconName } from "../ui";
import { AgentManagementPanel } from "./AgentManagementPanel";
import { AgentOverviewPanel } from "./AgentOverviewPanel";
import { ChannelSettingsPanel } from "./ChannelSettingsPanel";
import { CapabilitySettingsPanel } from "./CapabilitySettingsPanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";
import { MediaServiceSettingsPanel } from "./MediaServiceSettingsPanel";
import { SearchServiceSettingsPanel } from "./SearchServiceSettingsPanel";
import { SystemSettingsPanel } from "./SystemSettingsPanel";
import { LocalAIRuntimePanel } from "./LocalAIRuntimePanel";
import { SETTINGS_EVENT, type SettingsSection } from "./events";

const DESKTOP_NAVIGATION: Array<{
  id: SettingsSection;
  label: string;
  description: string;
  icon: IconName;
}> = [
  { id: "agents", label: "Agent 管理", description: "创建、连接与管理所有 Agent", icon: "robot" },
  { id: "accounts", label: "账户管理", description: "本机身份、切换与备份", icon: "shield" },
  { id: "local-ai", label: "本机 AI 服务", description: "下载模型与管理共享推理服务", icon: "sparkles" },
  { id: "system", label: "系统设置", description: "Desktop 运行环境与日志", icon: "settings" },
];

const AGENT_NAVIGATION: Array<{
  id: SettingsSection;
  label: string;
  description: string;
  icon: IconName;
}> = [
  { id: "overview", label: "概览", description: "连接与基本信息", icon: "info" },
  { id: "capabilities", label: "能力", description: "这个 Agent 能完成什么", icon: "file-text" },
  { id: "models", label: "模型", description: "主模型、视觉模型与服务商", icon: "sparkles" },
  { id: "media", label: "媒体服务", description: "图片、语音与音乐生成", icon: "image" },
  { id: "search", label: "联网搜索", description: "网页搜索服务与访问凭证", icon: "search" },
  { id: "channels", label: "渠道与绑定", description: "飞书、钉钉和人物绑定", icon: "bell" },
];

const AGENT_SECTIONS = new Set<SettingsSection>(["overview", "capabilities", "models", "media", "search", "channels"]);

export function SettingsCenter() {
  const { i18n } = useTranslation();
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
        aria-label="设置"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings-center-header">
          <div>
            <h2>设置</h2>
            <p>管理 Desktop、本机账户，以及每个 Agent 独立的配置。</p>
          </div>
          <button type="button" aria-label="关闭设置" onClick={() => setOpen(false)}>
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="settings-center-body">
          <nav className="settings-center-nav" aria-label="设置分类">
            <span className="settings-nav-group">Desktop</span>
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
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            ))}

            {settingsAgent && (
              <>
                <span className="settings-nav-group">正在设置</span>
                <div className="settings-nav-agent">
                  <span className="settings-nav-avatar">
                    {settingsAgent.name.charAt(0) || "A"}
                  </span>
                  <div>
                    <strong>{settingsAgent.name}</strong>
                    <small className={connected ? "online" : ""}>
                      {settingsAgent.source === "local" ? "本地" : "远程"}
                      {" · "}
                      {connected ? "在线" : "未连接"}
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
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
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
                  返回 Agent 列表
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
          </main>
        </div>
      </section>
    </div>
  );
}
