import { useEffect, useState } from "react";
import { useCoreStore } from "../../store";
import { IdentitySettingsDialog } from "../IdentitySettingsDialog";
import { Icon, type IconName } from "../ui";
import { ChannelSettingsPanel } from "./ChannelSettingsPanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";
import { SystemSettingsPanel } from "./SystemSettingsPanel";
import { SETTINGS_EVENT, type SettingsSection } from "./events";

const NAVIGATION: Array<{
  id: SettingsSection;
  label: string;
  description: string;
  icon: IconName;
  scope: "desktop" | "agent";
}> = [
  { id: "system", label: "系统设置", description: "Desktop 运行环境与日志", icon: "settings", scope: "desktop" },
  { id: "accounts", label: "账户管理", description: "本机身份、切换与备份", icon: "shield", scope: "desktop" },
  { id: "overview", label: "Agent 概览", description: "当前连接与基本信息", icon: "robot", scope: "agent" },
  { id: "models", label: "模型", description: "主模型、视觉模型与服务商", icon: "sparkles", scope: "agent" },
  { id: "channels", label: "渠道与绑定", description: "飞书、钉钉和人物绑定", icon: "bell", scope: "agent" },
];

export function SettingsCenter() {
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const localInfoByAgent = useCoreStore((state) => state.localInfoByAgent);
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<SettingsSection>("overview");

  const activeAgent = agents.find((agent) => agent.id === activeAgentId);
  const connected = Boolean(
    activeAgentId && connectionByAgent[activeAgentId]?.status === "connected",
  );

  useEffect(() => {
    const handleOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ section?: SettingsSection }>).detail;
      setSection(detail?.section || "overview");
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
  }, []);

  if (!open) return null;

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
            <p>管理 Desktop 身份，以及当前 Agent 的模型、渠道和运行信息。</p>
          </div>
          <button type="button" aria-label="关闭设置" onClick={() => setOpen(false)}>
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="settings-center-body">
          <nav className="settings-center-nav" aria-label="设置分类">
            {NAVIGATION.map((item, index) => (
              <div key={item.id}>
                {index === 0 && <span className="settings-nav-group">Desktop</span>}
                {index === 2 && (
                  <>
                    <span className="settings-nav-group">当前 Agent</span>
                    <div className="settings-nav-agent">
                      <span className="settings-nav-avatar">{activeAgent?.name.charAt(0) || "?"}</span>
                      <div>
                        <strong>{activeAgent?.name || "未选择 Agent"}</strong>
                        <small className={connected ? "online" : ""}>{connected ? "已连接" : "未连接"}</small>
                      </div>
                    </div>
                  </>
                )}
                <button
                  type="button"
                  className={section === item.id ? "active" : ""}
                  onClick={() => setSection(item.id)}
                >
                  <Icon name={item.icon} size={17} />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </button>
              </div>
            ))}
          </nav>

          <main className="settings-center-content">
            {section === "system" && (
              <SystemSettingsPanel />
            )}
            {section === "accounts" && (
              <IdentitySettingsDialog embedded onClose={() => setOpen(false)} />
            )}
            {section === "overview" && (
              <AgentOverview
                name={activeAgent?.name || ""}
                description={activeAgent?.description || ""}
                address={activeAgent ? `${activeAgent.host}:${activeAgent.port}` : ""}
                source={activeAgent?.source || "manual"}
                connected={connected}
                pid={activeAgentId ? localInfoByAgent[activeAgentId]?.pid : undefined}
              />
            )}
            {section === "models" && (
              <ModelSettingsPanel agentId={activeAgentId || ""} connected={connected} />
            )}
            {section === "channels" && (
              activeAgentId ? (
                <ChannelSettingsPanel
                  agentId={activeAgentId}
                  agentName={activeAgent?.name || "Agent"}
                  connected={connected}
                />
              ) : <div className="settings-empty">请先选择一个 Agent。</div>
            )}
          </main>
        </div>
      </section>
    </div>
  );
}

function AgentOverview({
  name,
  description,
  address,
  source,
  connected,
  pid,
}: {
  name: string;
  description: string;
  address: string;
  source: "manual" | "local";
  connected: boolean;
  pid?: number;
}) {
  if (!name) return <div className="settings-empty">请先选择一个 Agent。</div>;
  return (
    <div className="settings-overview">
      <section className="settings-card settings-agent-profile">
        <span className="settings-agent-avatar">{name.charAt(0)}</span>
        <div>
          <h3>{name}</h3>
          <p>{description || "本地 AI Agent"}</p>
          <span className={`settings-connection ${connected ? "online" : ""}`}>
            <i />{connected ? "在线" : "未连接"}
          </span>
        </div>
      </section>
      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>连接信息</h3>
            <p>这里只展示连接事实，不在 Desktop 中直接修改 Agent 内部文件。</p>
          </div>
        </div>
        <dl className="settings-facts">
          <div><dt>地址</dt><dd>{address}</dd></div>
          <div><dt>来源</dt><dd>{source === "local" ? "本地 Agent" : "远程 / 手动连接"}</dd></div>
          {pid && <div><dt>进程</dt><dd>PID {pid}</dd></div>}
        </dl>
      </section>
    </div>
  );
}
