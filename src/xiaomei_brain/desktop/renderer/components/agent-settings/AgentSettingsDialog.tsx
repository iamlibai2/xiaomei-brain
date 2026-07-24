import { useEffect, useState } from "react";
import { Button, Icon } from "../ui";

interface Props {
  open: boolean;
  agentId: string;
  agentName: string;
  onClose: () => void;
}

type ChannelConfig = {
  enabled?: boolean;
  app_id?: string;
  display_name?: string;
  secret_configured?: boolean;
};

export function AgentSettingsDialog({ open, agentId, agentName, onClose }: Props) {
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

  useEffect(() => {
    if (!open || !agentId) return;
    setError("");
    setNotice("");
    void window.gateway.getChannelConfig({ agentId, channel: "feishu" }).then((response) => {
      if (response.error) {
        setError(response.error.message);
        return;
      }
      const config = (response.result?.config || {}) as ChannelConfig;
      const runtime = (response.result?.runtime || {}) as Record<string, unknown>;
      setAppId(config.app_id || "");
      setDisplayName(config.display_name || `${agentName}飞书机器人`);
      setSecretConfigured(Boolean(config.secret_configured));
      setRuntimeState(typeof runtime.state === "string" ? runtime.state : "stopped");
      setAppSecret("");
    });
  }, [agentId, agentName, open]);

  useEffect(() => {
    if (!open || !linkRequestId || linkStatus === "completed") return;
    const timer = window.setInterval(() => {
      void window.gateway.getIdentityLinkStatus({ agentId, requestId: linkRequestId })
        .then((response) => {
          if (response.error) return;
          const status = String(response.result?.status || "");
          setLinkStatus(status);
          if (status === "completed") {
            setNotice("飞书身份已绑定到当前人物。");
            window.clearInterval(timer);
          }
        });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [agentId, linkRequestId, linkStatus, open]);

  useEffect(() => {
    if (!open || !agentId || !secretConfigured) return;
    const refresh = () => {
      void window.gateway.getChannelStatus({ agentId, channel: "feishu" })
        .then((response) => {
          if (!response.error) setRuntimeState(String(response.result?.state || "stopped"));
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [agentId, open, secretConfigured]);

  if (!open) return null;

  const test = async () => {
    setBusy("test");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.testChannel({
        agentId, channel: "feishu", appId, appSecret,
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
        channel: "feishu",
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
      setNotice("飞书渠道已保存并启用。");
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
        agentId, provider: "feishu",
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
      const response = await window.gateway.removeChannel({ agentId, channel: "feishu" });
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
      setNotice("飞书渠道已移除。");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="agent-settings-backdrop" onMouseDown={onClose}>
      <section className="agent-settings-dialog" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h2>{agentName}</h2>
            <p>Agent 设置 · 渠道</p>
          </div>
          <button type="button" className="agent-settings-close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>

        <div className="channel-heading">
          <div className="channel-logo">飞</div>
          <div>
            <h3>飞书</h3>
            <span className={`channel-runtime ${runtimeState}`}>{runtimeState}</span>
          </div>
        </div>

        <label>
          机器人名称
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        <label>
          App ID
          <input value={appId} onChange={(event) => setAppId(event.target.value)} placeholder="cli_xxx" />
        </label>
        <label>
          App Secret
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
            <p>生成绑定码后，在飞书中私聊机器人并发送下面的命令。</p>
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
                  {linkStatus === "completed" ? "绑定成功" : "等待飞书消息…"}
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
                飞书连接尚未建立，请等待状态变为 running 后再生成绑定码。
              </div>
            )}
          </div>
        )}

        {notice && <div className="channel-notice">{notice}</div>}
        {error && <div className="channel-error">{error}</div>}

        <footer>
          {secretConfigured && (
            <button type="button" className="channel-remove" disabled={Boolean(busy)} onClick={() => void remove()}>
              移除飞书渠道
            </button>
          )}
          <Button variant="secondary" onClick={onClose}>完成</Button>
        </footer>
      </section>
    </div>
  );
}
