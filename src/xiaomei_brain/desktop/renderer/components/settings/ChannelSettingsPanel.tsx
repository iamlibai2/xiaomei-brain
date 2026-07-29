import { useCallback, useEffect, useState } from "react";
import { AgentSettingsDialog, type ChannelProvider } from "../agent-settings/AgentSettingsDialog";
import { Button, Icon } from "../ui";

interface Props {
  agentId: string;
  agentName: string;
  connected: boolean;
}

interface ChannelSummary {
  configured: boolean;
  appId: string;
  displayName: string;
  runtimeState: string;
  identityCount: number;
}

const PROVIDERS: Array<{
  id: ChannelProvider;
  name: string;
  mark: string;
  description: string;
}> = [
  { id: "feishu", name: "飞书", mark: "飞", description: "通过飞书私聊和群聊与 Agent 协作" },
  { id: "dingtalk", name: "钉钉", mark: "钉", description: "通过钉钉机器人接收消息和交付结果" },
];

const EMPTY_SUMMARY: ChannelSummary = {
  configured: false,
  appId: "",
  displayName: "",
  runtimeState: "stopped",
  identityCount: 0,
};

const RUNTIME_LABELS: Record<string, string> = {
  starting: "连接中",
  running: "在线",
  reconnecting: "重连中",
  error: "异常",
  stopped: "未启用",
};

export function ChannelSettingsPanel({ agentId, agentName, connected }: Props) {
  const [summaries, setSummaries] = useState<Record<ChannelProvider, ChannelSummary>>({
    feishu: EMPTY_SUMMARY,
    dingtalk: EMPTY_SUMMARY,
  });
  const [editing, setEditing] = useState<ChannelProvider | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!agentId || !connected) return;
    setLoading(true);
    try {
      const entries = await Promise.all(PROVIDERS.map(async ({ id }) => {
        const [configResponse, linkResponse] = await Promise.all([
          window.gateway.getChannelConfig({ agentId, channel: id }),
          window.gateway.listIdentityLinks({ agentId, provider: id }),
        ]);
        if (configResponse.error) throw new Error(configResponse.error.message);
        const config = (configResponse.result?.config || {}) as Record<string, unknown>;
        const runtime = (configResponse.result?.runtime || {}) as Record<string, unknown>;
        const bindings = Array.isArray(linkResponse.result?.bindings)
          ? linkResponse.result.bindings
          : [];
        return [id, {
          configured: Boolean(config.secret_configured),
          appId: String(config.app_id || ""),
          displayName: String(config.display_name || ""),
          runtimeState: String(runtime.state || "stopped"),
          identityCount: bindings.length,
        }] as const;
      }));
      setSummaries(Object.fromEntries(entries) as Record<ChannelProvider, ChannelSummary>);
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
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [connected, load]);

  if (!agentId) return <div className="settings-empty">请先选择一个 Agent。</div>;
  if (!connected) return <div className="settings-empty">连接 Agent 后才能配置它的外部渠道。</div>;

  return (
    <div className="channel-settings-library">
      <header className="model-page-heading">
        <div>
          <h2>渠道与绑定</h2>
          <p>让 {agentName} 通过企业通讯工具接收消息，并将外部身份认作同一个人。</p>
        </div>
        {loading && <span className="settings-badge">刷新中</span>}
      </header>

      <section className="settings-card channel-library-card">
        <div className="settings-card-heading">
          <div>
            <h3>可用渠道</h3>
            <p>每个应用只绑定一个 Agent；群聊使用内置策略，无需额外配置。</p>
          </div>
        </div>
        <div className="channel-library-list">
          {PROVIDERS.map((provider) => {
            const summary = summaries[provider.id];
            const runtimeLabel = RUNTIME_LABELS[summary.runtimeState] || summary.runtimeState;
            return (
              <article className="channel-library-row" key={provider.id}>
                <span className={`channel-library-logo ${provider.id}`}>{provider.mark}</span>
                <div className="channel-library-copy">
                  <strong>{provider.name}</strong>
                  <p>{summary.configured
                    ? summary.displayName || summary.appId
                    : provider.description}</p>
                  <div className="channel-library-meta">
                    <span className={`channel-runtime ${summary.runtimeState}`}>{runtimeLabel}</span>
                    {summary.identityCount > 0 && <span>当前人物已绑定 {summary.identityCount} 个身份</span>}
                  </div>
                </div>
                <Button
                  variant={summary.configured ? "secondary" : "primary"}
                  onClick={() => setEditing(provider.id)}
                >
                  {summary.configured ? "管理" : "配置"}
                  <Icon name="chevron-right" size={14} />
                </Button>
              </article>
            );
          })}
        </div>
      </section>

      {error && <div className="settings-error">{error}</div>}
      <AgentSettingsDialog
        key={editing || "closed"}
        open={editing !== null}
        agentId={agentId}
        agentName={agentName}
        initialChannel={editing || "feishu"}
        onChanged={() => void load()}
        onClose={() => {
          setEditing(null);
          void load();
        }}
      />
    </div>
  );
}
