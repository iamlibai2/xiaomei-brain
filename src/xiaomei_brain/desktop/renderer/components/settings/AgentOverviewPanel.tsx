import { useCallback, useEffect, useMemo, useState } from "react";
import type { DesktopInfo, IdentityStatus, ModelConfigSnapshot } from "../../types";
import { Icon } from "../ui";
import type { SettingsSection } from "./events";

interface Props {
  agentId: string;
  name: string;
  description: string;
  address: string;
  source: "manual" | "local";
  localAgentId?: string;
  connected: boolean;
  pid?: number;
  onNavigate: (section: SettingsSection) => void;
}

type ChannelProvider = "feishu" | "dingtalk";
interface ChannelSummary {
  configured: boolean;
  state: string;
}

const RUNTIME_LABELS: Record<string, string> = {
  starting: "连接中",
  running: "在线",
  reconnecting: "重连中",
  error: "异常",
  stopped: "未启用",
};

export function AgentOverviewPanel(props: Props) {
  const {
    agentId, name, description, address, source, localAgentId, connected, pid, onNavigate,
  } = props;
  const [identity, setIdentity] = useState<IdentityStatus | null>(null);
  const [desktopInfo, setDesktopInfo] = useState<DesktopInfo | null>(null);
  const [model, setModel] = useState<ModelConfigSnapshot | null>(null);
  const [channels, setChannels] = useState<Record<ChannelProvider, ChannelSummary>>({
    feishu: { configured: false, state: "stopped" },
    dingtalk: { configured: false, state: "stopped" },
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    try {
      const [identityStatus, info] = await Promise.all([
        window.identity.status(),
        window.desktop.getInfo(),
      ]);
      setIdentity(identityStatus);
      setDesktopInfo(info);
      if (!connected) {
        setModel(null);
        setChannels({
          feishu: { configured: false, state: "stopped" },
          dingtalk: { configured: false, state: "stopped" },
        });
        setError("");
        return;
      }
      const [modelResponse, feishuResponse, dingtalkResponse] = await Promise.all([
        window.gateway.getModelConfig({ agentId }),
        window.gateway.getChannelConfig({ agentId, channel: "feishu" }),
        window.gateway.getChannelConfig({ agentId, channel: "dingtalk" }),
      ]);
      if (modelResponse.error) throw new Error(modelResponse.error.message);
      setModel(modelResponse.result as unknown as ModelConfigSnapshot);
      setChannels({
        feishu: channelSummary(feishuResponse),
        dingtalk: channelSummary(dingtalkResponse),
      });
      setError("");
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setLoading(false);
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!connected) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [connected, load]);

  const agentDirectory = useMemo(() => {
    if (!desktopInfo?.agentDirectory || !localAgentId) return "";
    const separator = desktopInfo.agentDirectory.includes("\\") ? "\\" : "/";
    return `${desktopInfo.agentDirectory}${separator}${localAgentId}`;
  }, [desktopInfo, localAgentId]);

  if (!name) return <div className="settings-empty">请先选择一个 Agent。</div>;
  const channelValues = Object.values(channels);
  const configuredCount = channelValues.filter((item) => item.configured).length;
  const onlineCount = channelValues.filter((item) => item.state === "running").length;

  return (
    <div className="settings-overview agent-overview-page">
      <section className="settings-card settings-agent-profile">
        <span className="settings-agent-avatar">{name.charAt(0)}</span>
        <div>
          <h3>{name}</h3>
          <p>{description || "本地 AI Agent"}</p>
          <span className={`settings-connection ${connected ? "online" : ""}`}>
            <i />{connected ? "在线" : "未连接"}
          </span>
        </div>
        {loading && <span className="settings-badge agent-overview-refreshing">刷新中</span>}
      </section>

      <section className="agent-overview-facts">
        <OverviewFact icon="external-link" label="连接" value={connected ? "已连接" : "未连接"} detail={address || "—"} tone={connected ? "success" : "muted"} />
        <OverviewFact icon="terminal" label="运行位置" value={source === "local" ? "本机" : "远程"} detail={pid ? `PID ${pid}` : source === "local" ? "进程信息不可用" : "由远端维护"} />
        <OverviewFact icon="shield" label="Desktop 账户" value={identity?.displayName || "未解锁"} detail={identity?.subject ? `${identity.subject.slice(0, 12)}…` : "未提供身份凭证"} />
        <OverviewFact icon="bell" label="外部渠道" value={`${onlineCount} 个在线`} detail={`${configuredCount} 个已配置`} tone={onlineCount ? "success" : "muted"} />
      </section>

      <section className="settings-card agent-overview-config">
        <div className="settings-card-heading">
          <div>
            <h3>核心配置</h3>
            <p>这里只汇总当前状态；具体修改进入对应设置页面。</p>
          </div>
        </div>
        <button type="button" onClick={() => onNavigate("models")}>
          <span className="agent-overview-config-icon"><Icon name="sparkles" size={17} /></span>
          <span>
            <strong>模型</strong>
            <small>主模型：{shortModelName(model?.selection.primary) || (connected ? "未配置" : "连接后查看")}</small>
            {model?.selection.vision && <small>视觉模型：{shortModelName(model.selection.vision)}</small>}
          </span>
          <Icon name="chevron-right" size={15} />
        </button>
        <button type="button" onClick={() => onNavigate("channels")}>
          <span className="agent-overview-config-icon"><Icon name="bell" size={17} /></span>
          <span>
            <strong>渠道与绑定</strong>
            <small>飞书：{channelLabel(channels.feishu)} · 钉钉：{channelLabel(channels.dingtalk)}</small>
          </span>
          <Icon name="chevron-right" size={15} />
        </button>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>运行信息</h3>
            <p>本地 Agent 由本机维护；远程 Agent 的运行由其所在主机维护。</p>
          </div>
        </div>
        <dl className="settings-facts">
          <div><dt>地址</dt><dd>{address || "—"}</dd></div>
          <div><dt>来源</dt><dd>{source === "local" ? "本地 Agent" : "远程 / 手动连接"}</dd></div>
          {pid && <div><dt>进程</dt><dd>PID {pid}</dd></div>}
          {source === "local" && agentDirectory && <div><dt>数据目录</dt><dd title={agentDirectory}>{agentDirectory}</dd></div>}
        </dl>
      </section>
      {error && <div className="settings-error">{error}</div>}
    </div>
  );
}

function OverviewFact({ icon, label, value, detail, tone = "" }: {
  icon: "external-link" | "terminal" | "shield" | "bell";
  label: string;
  value: string;
  detail: string;
  tone?: "success" | "muted" | "";
}) {
  return (
    <article className={`agent-overview-fact ${tone}`}>
      <Icon name={icon} size={16} />
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function channelSummary(response: Awaited<ReturnType<typeof window.gateway.getChannelConfig>>): ChannelSummary {
  if (response.error) return { configured: false, state: "error" };
  const config = (response.result?.config || {}) as Record<string, unknown>;
  const runtime = (response.result?.runtime || {}) as Record<string, unknown>;
  return {
    configured: Boolean(config.secret_configured),
    state: String(runtime.state || "stopped"),
  };
}

function channelLabel(summary: ChannelSummary): string {
  if (!summary.configured) return "未配置";
  return RUNTIME_LABELS[summary.state] || summary.state;
}

function shortModelName(value?: string): string {
  if (!value) return "";
  return value.includes("/") ? value.split("/", 2)[1] : value;
}
