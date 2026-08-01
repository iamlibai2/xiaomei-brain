import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentCapability, CapabilityStatus } from "../../types";
import { Button, Icon, type IconName } from "../ui";
import { notifyCapabilityStatusChanged } from "./events";

interface Props {
  agentId: string;
  connected: boolean;
  target?: string;
  onTargetConsumed?: () => void;
  onNavigate: (section: string, target?: string) => void;
}

const STATUS_LABELS: Record<CapabilityStatus, string> = {
  not_acquired: "未获得",
  disabled: "已关闭",
  preparing: "准备中",
  needs_setup: "需要完善",
  ready: "可用",
  degraded: "部分可用",
  unavailable: "暂不可用",
  error: "异常",
};

export function CapabilitySettingsPanel({
  agentId,
  connected,
  target = "",
  onTargetConsumed,
  onNavigate,
}: Props) {
  const [capabilities, setCapabilities] = useState<AgentCapability[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [changingId, setChangingId] = useState("");
  const [highlightedId, setHighlightedId] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!connected) {
      setCapabilities([]);
      setError("");
      return;
    }
    setLoading(true);
    try {
      const response = await window.gateway.listCapabilities({ agentId });
      if (response.error) throw new Error(response.error.message);
      const values = response.result?.capabilities;
      setCapabilities(Array.isArray(values) ? values as AgentCapability[] : []);
      setError("");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!target || !capabilities.length) return;
    const exists = capabilities.some((item) => item.id === target);
    if (exists) {
      const selector = `[data-capability-id="${CSS.escape(target)}"]`;
      listRef.current?.querySelector<HTMLElement>(selector)?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
      setHighlightedId(target);
    }
    onTargetConsumed?.();
  }, [target, capabilities, onTargetConsumed]);

  useEffect(() => {
    if (!highlightedId) return;
    const timer = window.setTimeout(() => setHighlightedId(""), 1800);
    return () => window.clearTimeout(timer);
  }, [highlightedId]);

  const setEnabled = useCallback(async (capabilityId: string, enabled: boolean) => {
    setChangingId(capabilityId);
    try {
      const response = await window.gateway.setCapabilityEnabled({
        agentId,
        capabilityId,
        enabled,
      });
      if (response.error) throw new Error(response.error.message);
      const changed = response.result?.capability as AgentCapability | undefined;
      if (changed) {
        setCapabilities((current) => current.map((item) => item.id === changed.id ? changed : item));
      } else {
        await load();
      }
      notifyCapabilityStatusChanged(agentId, capabilityId);
      setError("");
    } catch (changeError) {
      setError(changeError instanceof Error ? changeError.message : String(changeError));
    } finally {
      setChangingId("");
    }
  }, [agentId, load]);

  return (
    <div className="capability-settings-page">
      <div className="capability-page-heading">
        <div>
          <h2>能力</h2>
          <p>查看这个 Agent 当前真正能够完成的工作，以及尚有条件限制的部分。</p>
        </div>
        <Button variant="ghost" size="sm" icon="refresh" disabled={loading || !connected} onClick={() => void load()}>
          {loading ? "刷新中" : "刷新"}
        </Button>
      </div>

      {!connected && (
        <div className="settings-empty capability-empty">
          <Icon name="sparkles" size={22} />
          <strong>连接 Agent 后查看能力</strong>
          <span>能力状态由 Agent 自己确认，Desktop 不在本地猜测。</span>
        </div>
      )}
      {connected && !loading && !error && capabilities.length === 0 && (
        <div className="settings-empty capability-empty">
          <strong>这个 Agent 暂未声明能力</strong>
          <span>后续获得的能力会自然出现在这里。</span>
        </div>
      )}
      {error && (
        <div className="settings-error capability-load-error">
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={() => void load()}>重试</Button>
        </div>
      )}

      <div className="capability-list" ref={listRef}>
        {capabilities.map((capability) => (
          <CapabilityCard
            key={capability.id}
            capability={capability}
            changing={changingId === capability.id}
            highlighted={highlightedId === capability.id}
            onToggle={(enabled) => void setEnabled(capability.id, enabled)}
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  );
}

function CapabilityCard({
  capability,
  changing,
  highlighted,
  onToggle,
  onNavigate,
}: {
  capability: AgentCapability;
  changing: boolean;
  highlighted: boolean;
  onToggle: (enabled: boolean) => void;
  onNavigate: (section: string, target?: string) => void;
}) {
  const issueWithAction = capability.issues.find((issue) => issue.action);
  const setupAction = capability.actions?.[0] || issueWithAction?.action;
  return (
    <section
      className={`settings-card capability-card ${highlighted ? "is-targeted" : ""}`}
      data-capability-id={capability.id}
    >
      <header className="capability-card-header">
        <span className="capability-card-icon"><Icon name={capabilityIcon(capability.category)} size={19} /></span>
        <div>
          <h3>{capability.name}</h3>
          <p>{capability.summary}</p>
        </div>
        <div className="capability-card-actions">
          <span className={`capability-status ${capability.status}`}>
            {STATUS_LABELS[capability.status] || capability.status}
          </span>
          <button
            type="button"
            className={`desktop-switch capability-toggle ${capability.enabled ? "is-on" : ""}`}
            role="switch"
            aria-label={`${capability.enabled ? "关闭" : "启用"}${capability.name}`}
            aria-checked={capability.enabled}
            disabled={changing}
            onClick={() => onToggle(!capability.enabled)}
          >
            <span />
          </button>
        </div>
      </header>

      <div className="capability-outcomes">
        {capability.outcomes.map((outcome) => (
          <div key={outcome.id} className={`capability-outcome ${outcome.available ? "available" : "limited"}`}>
            <span className="capability-outcome-mark">{outcome.available ? "✓" : "—"}</span>
            <div>
              <strong>{outcome.name}</strong>
              {outcome.description && <p>{outcome.description}</p>}
              {!outcome.available && outcome.limitations.map((limitation) => (
                <small key={limitation}>{limitation}</small>
              ))}
            </div>
          </div>
        ))}
      </div>

      {setupAction && capability.enabled && issueWithAction && (
        <div className="capability-setup">
          <div>
            <strong>还需要完成配置</strong>
            <span>{issueWithAction.message}</span>
          </div>
          <Button variant="secondary" size="sm" onClick={() => onNavigate(setupAction.section, setupAction.target)}>
            {setupAction.label}
          </Button>
        </div>
      )}

      {capability.examples.length > 0 && (
        <div className="capability-examples">
          <span>可以这样说</span>
          {capability.examples.slice(0, 3).map((example) => <q key={example}>{example}</q>)}
        </div>
      )}

      {setupAction && capability.enabled && !issueWithAction && (
        <div className="capability-manage">
          <Button variant="ghost" size="sm" onClick={() => onNavigate(setupAction.section, setupAction.target)}>
            {setupAction.label}
          </Button>
        </div>
      )}
    </section>
  );
}

function capabilityIcon(category: string): IconName {
  const icons: Record<string, IconName> = {
    office: "file-text",
    data: "chart-bar",
    creation: "sparkles",
    research: "search",
    development: "terminal",
    enterprise: "folder",
  };
  return icons[category] || "sparkles";
}
