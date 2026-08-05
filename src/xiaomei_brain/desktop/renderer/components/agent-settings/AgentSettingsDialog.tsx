import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon } from "../ui";

interface Props {
  open: boolean;
  agentId: string;
  agentName: string;
  onClose: () => void;
  initialChannel?: ChannelProvider;
  onChanged?: () => void;
}

type ChannelConfig = {
  enabled?: boolean;
  app_id?: string;
  display_name?: string;
  secret_configured?: boolean;
};

type IdentityLink = {
  binding_id: string;
  subject_hint: string;
  created_at: number;
  last_verified_at?: number | null;
};

export type ChannelProvider = "feishu" | "dingtalk";

export function AgentSettingsDialog({
  open,
  agentId,
  agentName,
  onClose,
  initialChannel = "feishu",
  onChanged,
}: Props) {
  const { t } = useTranslation();
  const [channel, setChannel] = useState<ChannelProvider>(initialChannel);
  const [appId, setAppId] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [secretConfigured, setSecretConfigured] = useState(false);
  const [runtimeState, setRuntimeState] = useState("stopped");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [linkRequestId, setLinkRequestId] = useState("");
  const [linkCommand, setLinkCommand] = useState("");
  const [linkStatus, setLinkStatus] = useState("");
  const [identityLinks, setIdentityLinks] = useState<IdentityLink[]>([]);
  const channelName = channel === "feishu" ? t("channelUi.feishu") : t("channelUi.dingtalk");
  const runtimeLabel = ({
    starting: t("channelUi.connecting"),
    running: t("channelUi.online"),
    reconnecting: t("channelUi.reconnecting"),
    error: t("channelUi.error"),
    stopped: t("channelUi.disabled"),
  } as Record<string, string>)[runtimeState] || runtimeState || t("channelUi.unknown");

  useEffect(() => {
    if (open) setChannel(initialChannel);
  }, [initialChannel, open]);

  const refreshIdentityLinks = useCallback(async () => {
    if (!agentId) return;
    const response = await window.gateway.listIdentityLinks({
      agentId,
      provider: channel,
    });
    if (response.error) return;
    const raw = response.result?.bindings;
    setIdentityLinks(Array.isArray(raw) ? raw as IdentityLink[] : []);
  }, [agentId, channel]);

  useEffect(() => {
    if (!open || !agentId) return;
    setError("");
    setNotice("");
    setAppId("");
    setAppSecret("");
    setDisplayName("");
    setSecretConfigured(false);
    setRuntimeState("stopped");
    setLinkRequestId("");
    setLinkCommand("");
    setLinkStatus("");
    setIdentityLinks([]);
    void window.gateway.getChannelConfig({ agentId, channel }).then((response) => {
      if (response.error) {
        setError(response.error.message);
        return;
      }
      const config = (response.result?.config || {}) as ChannelConfig;
      const runtime = (response.result?.runtime || {}) as Record<string, unknown>;
      setAppId(config.app_id || "");
      const channelName = channel === "feishu" ? t("channelUi.feishu") : t("channelUi.dingtalk");
      setDisplayName(config.display_name || `${agentName} ${channelName}`);
      setSecretConfigured(Boolean(config.secret_configured));
      setRuntimeState(typeof runtime.state === "string" ? runtime.state : "stopped");
      setAppSecret("");
    });
  }, [agentId, agentName, channel, open]);

  useEffect(() => {
    if (open) void refreshIdentityLinks();
  }, [open, refreshIdentityLinks]);

  useEffect(() => {
    if (!open || !linkRequestId || linkStatus === "completed") return;
    const timer = window.setInterval(() => {
      void window.gateway.getIdentityLinkStatus({ agentId, requestId: linkRequestId })
        .then((response) => {
          if (response.error) return;
          const status = String(response.result?.status || "");
          setLinkStatus(status);
          if (status === "completed") {
            setNotice(t("channelUi.boundSuccess"));
            void refreshIdentityLinks();
            window.clearInterval(timer);
          }
        });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [agentId, channel, linkRequestId, linkStatus, open, refreshIdentityLinks]);

  useEffect(() => {
    if (!open || !agentId || !secretConfigured) return;
    const refresh = () => {
      void window.gateway.getChannelStatus({ agentId, channel })
        .then((response) => {
          if (!response.error) setRuntimeState(String(response.result?.state || "stopped"));
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [agentId, channel, open, secretConfigured]);

  if (!open) return null;

  const test = async () => {
    setBusy("test");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.testChannel({
        agentId, channel, appId, appSecret,
      });
      if (response.error) setError(response.error.message);
      else setNotice(t("channelUi.testSuccess"));
    } finally {
      setBusy("");
    }
  };

  const save = async () => {
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.configureChannel({
        agentId,
        channel,
        appId,
        appSecret,
        displayName,
        accountId: "default",
      });
      if (response.error) {
        setError(response.error.message);
        return;
      }
      const runtime = (response.result?.runtime || {}) as Record<string, unknown>;
      setRuntimeState(String(runtime.state || "running"));
      setSecretConfigured(true);
      setAppSecret("");
      setNotice(t("channelUi.saved", { channel: channelName }));
      onChanged?.();
    } finally {
      setBusy("");
    }
  };

  const beginLink = async () => {
    setBusy("link");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.beginIdentityLink({
        agentId, provider: channel,
      });
      if (response.error) {
        setError(response.error.message);
        return;
      }
      setLinkRequestId(String(response.result?.request_id || ""));
      setLinkCommand(String(response.result?.command || ""));
      setLinkStatus(String(response.result?.status || "pending"));
    } finally {
      setBusy("");
    }
  };

  const remove = async () => {
    setBusy("remove");
    setError("");
    try {
      const response = await window.gateway.removeChannel({ agentId, channel });
      if (response.error) {
        setError(response.error.message);
        return;
      }
      setRuntimeState("stopped");
      setAppId("");
      setAppSecret("");
      setSecretConfigured(false);
      setLinkRequestId("");
      setLinkCommand("");
      setNotice(t("channelUi.removed", { channel: channelName }));
      onChanged?.();
    } finally {
      setBusy("");
    }
  };

  const revokeIdentity = async (bindingId: string) => {
    setBusy(`revoke:${bindingId}`);
    setError("");
    try {
      const response = await window.gateway.revokeIdentityLink({
        agentId,
        provider: channel,
        bindingId,
      });
      if (response.error) {
        setError(response.error.message);
        return;
      }
      setNotice(t("channelUi.unbound", { channel: channelName }));
      setLinkRequestId("");
      setLinkCommand("");
      setLinkStatus("");
      await refreshIdentityLinks();
      onChanged?.();
    } finally {
      setBusy("");
    }
  };

  return (
    <div
      className="agent-settings-backdrop"
      onMouseDown={onClose}
    >
      <section className="agent-settings-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>{channelName}</h2>
            <p>{agentName} · {t("channelUi.settings")}</p>
          </div>
          <button type="button" className="agent-settings-close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>

        <div className="channel-heading">
          <div className="channel-logo">{channel === "feishu" ? "飞" : "钉"}</div>
          <div>
            <h3>{channelName}</h3>
            <span className={`channel-runtime ${runtimeState}`} title={runtimeState}>
              {runtimeLabel}
            </span>
          </div>
        </div>

        <label>
          {t("channelUi.botName")}
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        <label>
          {channel === "feishu" ? "App ID" : "Client ID (AppKey)"}
          <input
            value={appId}
            onChange={(event) => setAppId(event.target.value)}
            placeholder={channel === "feishu" ? "cli_xxx" : "ding_xxx"}
          />
        </label>
        <label>
          {channel === "feishu" ? "App Secret" : "Client Secret"}
          <input
            type="password"
            value={appSecret}
            onChange={(event) => setAppSecret(event.target.value)}
            placeholder={secretConfigured ? t("channelUi.secretConfigured") : t("channelUi.secretPlaceholder")}
          />
        </label>

        <div className="channel-actions">
          <Button variant="secondary" disabled={!appId || Boolean(busy)} onClick={() => void test()}>
            {busy === "test" ? t("channelUi.testing") : t("channelUi.test")}
          </Button>
          <Button variant="primary" disabled={!appId || Boolean(busy)} onClick={() => void save()}>
            {busy === "save" ? t("channelUi.enabling") : t("channelUi.saveEnable")}
          </Button>
        </div>

        {secretConfigured && (
          <div className="identity-link-panel">
            <h3>{t("channelUi.bindTitle")}</h3>
            <p>{t("channelUi.bindDescription", { channel: channelName })}</p>
            {identityLinks.length > 0 && (
              <div className="identity-link-list">
                {identityLinks.map((binding) => (
                  <div className="identity-link-item" key={binding.binding_id}>
                    <div>
                      <strong>{t("channelUi.bound", { channel: channelName })}</strong>
                      <code>{binding.subject_hint}</code>
                    </div>
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => void revokeIdentity(binding.binding_id)}
                    >
                      {busy === `revoke:${binding.binding_id}` ? t("channelUi.generating") : t("channelUi.unbind")}
                    </button>
                  </div>
                ))}
              </div>
            )}
            {linkCommand ? (
              <>
                <button
                  type="button"
                  className="link-command"
                  onClick={() => void navigator.clipboard.writeText(linkCommand)}
                >
                  <code>{linkCommand}</code>
                  <span>{t("channelUi.copy")}</span>
                </button>
                <div className={`link-status ${linkStatus}`}>
                  {linkStatus === "completed" ? t("channelUi.boundSuccess") : t("channelUi.waitingMessage", { channel: channelName })}
                </div>
              </>
            ) : (
              <Button
                variant="secondary"
                disabled={Boolean(busy) || runtimeState !== "running"}
                onClick={() => void beginLink()}
              >
                {busy === "link" ? t("channelUi.generating") : t("channelUi.generate")}
              </Button>
            )}
            {runtimeState !== "running" && (
              <div className="link-status">
                {t("channelUi.notConnected", { channel: channelName, status: runtimeLabel })}
              </div>
            )}
          </div>
        )}

        {notice && <div className="channel-notice">{notice}</div>}
        {error && <div className="channel-error">{error}</div>}

        <footer>
          {secretConfigured && (
            <button type="button" className="channel-remove" disabled={Boolean(busy)} onClick={() => void remove()}>
              {t("channelUi.remove", { channel: channelName })}
            </button>
          )}
          <Button variant="secondary" onClick={onClose}>{t("channelUi.done")}</Button>
        </footer>
      </section>
    </div>
  );
}
