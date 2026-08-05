import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
}> = [
  { id: "feishu", name: "Feishu", mark: "飞" },
  { id: "dingtalk", name: "DingTalk", mark: "钉" },
];

const EMPTY_SUMMARY: ChannelSummary = {
  configured: false,
  appId: "",
  displayName: "",
  runtimeState: "stopped",
  identityCount: 0,
};

export function ChannelSettingsPanel({ agentId, agentName, connected }: Props) {
  const { t } = useTranslation();
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

  if (!agentId) return <div className="settings-empty">{t("channelUi.selectAgent")}</div>;
  if (!connected) return <div className="settings-empty">{t("channelUi.connectToConfigure")}</div>;

  return (
    <div className="channel-settings-library">
      <header className="model-page-heading">
        <div>
          <h2>{t("channelUi.channelsAndBindings")}</h2>
          <p>{t("channelUi.agentChannelDescription", { name: agentName })}</p>
        </div>
        {loading && <span className="settings-badge">{t("channelUi.refreshing")}</span>}
      </header>

      <section className="settings-card channel-library-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("channelUi.availableChannels")}</h3>
            <p>{t("channelUi.channelPolicy")}</p>
          </div>
        </div>
        <div className="channel-library-list">
          {PROVIDERS.map((provider) => {
            const summary = summaries[provider.id];
            const runtimeLabel = t(`channelUi.runtime${summary.runtimeState.charAt(0).toUpperCase()}${summary.runtimeState.slice(1)}`, { defaultValue: summary.runtimeState });
            return (
              <article className="channel-library-row" key={provider.id}>
                <span className={`channel-library-logo ${provider.id}`}>{provider.mark}</span>
                <div className="channel-library-copy">
                  <strong>{t(`channelUi.${provider.id}`)}</strong>
                  <p>{summary.configured
                    ? summary.displayName || summary.appId
                    : t(`channelUi.${provider.id}Description`)}</p>
                  <div className="channel-library-meta">
                    <span className={`channel-runtime ${summary.runtimeState}`}>{runtimeLabel}</span>
                    {summary.identityCount > 0 && <span>{t("channelUi.identityCount", { count: summary.identityCount })}</span>}
                  </div>
                </div>
                <Button
                  variant={summary.configured ? "secondary" : "primary"}
                  onClick={() => setEditing(provider.id)}
                >
                  {summary.configured ? t("channelUi.manage") : t("channelUi.configure")}
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
