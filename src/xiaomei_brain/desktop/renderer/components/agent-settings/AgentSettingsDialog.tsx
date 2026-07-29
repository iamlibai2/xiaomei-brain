import { useCallback, useEffect, useState } from "react";
import { Button, Icon } from "../ui";

interface Props {
  open: boolean;
  agentId: string;
  agentName: string;
  onClose: () => void;
  embedded?: boolean;
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

type ChannelProvider = "feishu" | "dingtalk";

const CHANNEL_RUNTIME_LABELS: Record<string, string> = {
  starting: "连接中",
  running: "在线",
  reconnecting: "重连中",
  error: "异常",
  stopped: "未启用",
};

function channelRuntimeLabel(state: string): string {
  return CHANNEL_RUNTIME_LABELS[state] || state || "未知";
}

export function AgentSettingsDialog({ open, agentId, agentName, onClose, embedded = false }: Props) {
  const [channel, setChannel] = useState<ChannelProvider>("feishu");
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
  const channelName = channel === "feishu" ? "飞书" : "钉钉";
  const runtimeLabel = channelRuntimeLabel(runtimeState);

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
      const channelName = channel === "feishu" ? "飞书" : "钉钉";
      setDisplayName(config.display_name || `${agentName}${channelName}机器人`);
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
            setNotice(`${channel === "feishu" ? "飞书" : "钉钉"}身份已绑定到当前人物。`);
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
      else setNotice("连接测试成功。");
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
      setNotice(`${channelName}渠道已保存并启用。`);
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
      setNotice(`${channelName}渠道已移除。`);
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
      setNotice(`${channelName}身份已解除绑定。`);
      setLinkRequestId("");
      setLinkCommand("");
      setLinkStatus("");
      await refreshIdentityLinks();
    } finally {
      setBusy("");
    }
  };

  return (
    <div
      className={embedded ? "agent-settings-embedded" : "agent-settings-backdrop"}
      onMouseDown={embedded ? undefined : onClose}
    >
      <section className={`agent-settings-dialog ${embedded ? "is-embedded" : ""}`} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>{agentName}</h2>
            <p>Agent 设置 · 渠道</p>
          </div>
          {!embedded && (
            <button type="button" className="agent-settings-close" onClick={onClose}>
              <Icon name="x" />
            </button>
          )}
        </header>

        <div className="channel-tabs" role="tablist" aria-label="渠道">
          {(["feishu", "dingtalk"] as ChannelProvider[]).map((item) => (
            <button
              type="button"
              role="tab"
              aria-selected={channel === item}
              className={channel === item ? "active" : ""}
              key={item}
              onClick={() => setChannel(item)}
            >
              {item === "feishu" ? "飞书" : "钉钉"}
            </button>
          ))}
        </div>

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
          机器人名称
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
            placeholder={secretConfigured ? "已配置；留空表示不修改" : "请输入 App Secret"}
          />
        </label>

        <div className="channel-actions">
          <Button variant="secondary" disabled={!appId || Boolean(busy)} onClick={() => void test()}>
            {busy === "test" ? "测试中…" : "测试连接"}
          </Button>
          <Button variant="primary" disabled={!appId || Boolean(busy)} onClick={() => void save()}>
            {busy === "save" ? "启用中…" : "保存并启用"}
          </Button>
        </div>

        {secretConfigured && (
          <div className="identity-link-panel">
            <h3>绑定当前人物</h3>
            <p>生成绑定码后，在{channelName}中私聊机器人并发送下面的命令。</p>
            {identityLinks.length > 0 && (
              <div className="identity-link-list">
                {identityLinks.map((binding) => (
                  <div className="identity-link-item" key={binding.binding_id}>
                    <div>
                      <strong>已绑定{channelName}身份</strong>
                      <code>{binding.subject_hint}</code>
                    </div>
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => void revokeIdentity(binding.binding_id)}
                    >
                      {busy === `revoke:${binding.binding_id}` ? "解除中…" : "解除绑定"}
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
                  <span>点击复制</span>
                </button>
                <div className={`link-status ${linkStatus}`}>
                  {linkStatus === "completed" ? "绑定成功" : `等待${channelName}消息…`}
                </div>
              </>
            ) : (
              <Button
                variant="secondary"
                disabled={Boolean(busy) || runtimeState !== "running"}
                onClick={() => void beginLink()}
              >
                {busy === "link" ? "生成中…" : "生成绑定码"}
              </Button>
            )}
            {runtimeState !== "running" && (
              <div className="link-status">
                {channelName}连接尚未建立，当前状态：{runtimeLabel}。连接在线后可生成绑定码。
              </div>
            )}
          </div>
        )}

        {notice && <div className="channel-notice">{notice}</div>}
        {error && <div className="channel-error">{error}</div>}

        <footer>
          {secretConfigured && (
            <button type="button" className="channel-remove" disabled={Boolean(busy)} onClick={() => void remove()}>
              移除{channelName}渠道
            </button>
          )}
          <Button variant="secondary" onClick={onClose}>完成</Button>
        </footer>
      </section>
    </div>
  );
}
