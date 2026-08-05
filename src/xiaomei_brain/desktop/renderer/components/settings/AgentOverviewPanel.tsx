import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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

export function AgentOverviewPanel(props: Props) {
  const { t } = useTranslation();
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

  if (!name) return <div className="settings-empty">{t("overviewUi.selectAgent")}</div>;
  const channelValues = Object.values(channels);
  const configuredCount = channelValues.filter((item) => item.configured).length;
  const onlineCount = channelValues.filter((item) => item.state === "running").length;

  return (
    <div className="settings-overview agent-overview-page">
      <section className="settings-card settings-agent-profile">
        <span className="settings-agent-avatar">{name.charAt(0)}</span>
        <div>
          <h3>{name}</h3>
          <p>{description || t("overviewUi.localAgent")}</p>
          <span className={`settings-connection ${connected ? "online" : ""}`}>
            <i />{connected ? t("overviewUi.online") : t("overviewUi.disconnected")}
          </span>
        </div>
        {loading && <span className="settings-badge agent-overview-refreshing">{t("overviewUi.refreshing")}</span>}
      </section>

      <section className="agent-overview-facts">
        <OverviewFact icon="external-link" label={t("overviewUi.connection")} value={connected ? t("overviewUi.connected") : t("overviewUi.disconnected")} detail={address || "—"} tone={connected ? "success" : "muted"} />
        <OverviewFact icon="terminal" label={t("overviewUi.location")} value={source === "local" ? t("settings.local") : t("settings.remote")} detail={pid ? `PID ${pid}` : source === "local" ? t("overviewUi.processUnavailable") : t("overviewUi.remoteMaintained")} />
        <OverviewFact icon="shield" label={t("overviewUi.desktopAccount")} value={identity?.displayName || t("overviewUi.notUnlocked")} detail={identity?.subject ? `${identity.subject.slice(0, 12)}…` : t("overviewUi.noCredential")} />
        <OverviewFact icon="bell" label={t("overviewUi.externalChannels")} value={t("overviewUi.onlineCount", { count: onlineCount })} detail={t("overviewUi.configuredCount", { count: configuredCount })} tone={onlineCount ? "success" : "muted"} />
      </section>

      <section className="settings-card agent-overview-config">
        <div className="settings-card-heading">
          <div>
            <h3>{t("overviewUi.coreConfig")}</h3>
            <p>{t("overviewUi.coreConfigHint")}</p>
          </div>
        </div>
        <button type="button" onClick={() => onNavigate("capabilities")}>
          <span className="agent-overview-config-icon"><Icon name="file-text" size={17} /></span>
          <span>
            <strong>{t("overviewUi.capabilities")}</strong>
            <small>{t("overviewUi.capabilitiesHint")}</small>
          </span>
          <Icon name="chevron-right" size={15} />
        </button>
        <button type="button" onClick={() => onNavigate("models")}>
          <span className="agent-overview-config-icon"><Icon name="sparkles" size={17} /></span>
          <span>
            <strong>{t("overviewUi.models")}</strong>
            <small>{t("overviewUi.primaryModel", { name: shortModelName(model?.selection.primary) || (connected ? t("overviewUi.notConfigured") : t("overviewUi.connectToView")) })}</small>
            {model?.selection.vision && <small>{t("overviewUi.visionModel", { name: shortModelName(model.selection.vision) })}</small>}
          </span>
          <Icon name="chevron-right" size={15} />
        </button>
        <button type="button" onClick={() => onNavigate("channels")}>
          <span className="agent-overview-config-icon"><Icon name="bell" size={17} /></span>
          <span>
            <strong>{t("overviewUi.channels")}</strong>
            <small>{t("overviewUi.feishu")}：{channelLabel(channels.feishu, t)} · {t("overviewUi.dingtalk")}：{channelLabel(channels.dingtalk, t)}</small>
          </span>
          <Icon name="chevron-right" size={15} />
        </button>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("overviewUi.runtimeInfo")}</h3>
            <p>{t("overviewUi.runtimeHint")}</p>
          </div>
        </div>
        <dl className="settings-facts">
          <div><dt>{t("overviewUi.address")}</dt><dd>{address || "—"}</dd></div>
          <div><dt>{t("overviewUi.source")}</dt><dd>{source === "local" ? t("overviewUi.localSource") : t("overviewUi.remoteSource")}</dd></div>
          {pid && <div><dt>{t("overviewUi.process")}</dt><dd>PID {pid}</dd></div>}
          {source === "local" && agentDirectory && <div><dt>{t("overviewUi.dataDirectory")}</dt><dd title={agentDirectory}>{agentDirectory}</dd></div>}
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

function channelLabel(summary: ChannelSummary, t: (key: string) => string): string {
  if (!summary.configured) return t("overviewUi.notConfiguredChannel");
  const labels: Record<string, string> = {
    starting: t("channelUi.connecting"),
    running: t("channelUi.online"),
    reconnecting: t("channelUi.reconnecting"),
    error: t("channelUi.error"),
    stopped: t("channelUi.disabled"),
  };
  return labels[summary.state] || summary.state;
}

function shortModelName(value?: string): string {
  if (!value) return "";
  return value.includes("/") ? value.split("/", 2)[1] : value;
}
