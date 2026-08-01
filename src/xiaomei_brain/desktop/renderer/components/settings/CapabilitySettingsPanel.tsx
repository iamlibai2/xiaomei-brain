import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AgentCapability,
  CapabilityPackageInspection,
  CapabilityStatus,
} from "../../types";
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
  const [packageBusy, setPackageBusy] = useState(false);
  const [packageError, setPackageError] = useState("");
  const [packageInspection, setPackageInspection] = useState<CapabilityPackageInspection | null>(null);
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

  const inspectPackage = useCallback(async () => {
    setPackageBusy(true);
    setPackageError("");
    try {
      const response = await window.gateway.inspectCapabilityPackage({ agentId });
      if (response.error) throw new Error(response.error.message);
      if (response.result?.canceled) return;
      const inspection = response.result?.inspection;
      if (!inspection || typeof inspection !== "object" || Array.isArray(inspection)) {
        throw new Error("Agent 返回了无效的能力包检查结果");
      }
      setPackageInspection(inspection as unknown as CapabilityPackageInspection);
    } catch (inspectError) {
      setPackageError(inspectError instanceof Error ? inspectError.message : String(inspectError));
    } finally {
      setPackageBusy(false);
    }
  }, [agentId]);

  return (
    <div className="capability-settings-page">
      <div className="capability-page-heading">
        <div>
          <h2>能力</h2>
          <p>查看这个 Agent 当前真正能够完成的工作，以及尚有条件限制的部分。</p>
        </div>
        <div className="capability-page-actions">
          <Button
            variant="secondary"
            size="sm"
            icon="folder"
            disabled={packageBusy || !connected}
            onClick={() => void inspectPackage()}
          >
            {packageBusy ? "检查中…" : "导入能力"}
          </Button>
          <Button variant="ghost" size="sm" icon="refresh" disabled={loading || !connected} onClick={() => void load()}>
            {loading ? "刷新中" : "刷新"}
          </Button>
        </div>
      </div>

      {packageError && <div className="settings-error capability-package-error">{packageError}</div>}

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

      {packageInspection && (
        <CapabilityPackageInspectionDialog
          inspection={packageInspection}
          onClose={() => setPackageInspection(null)}
        />
      )}
    </div>
  );
}

function CapabilityPackageInspectionDialog({
  inspection,
  onClose,
}: {
  inspection: CapabilityPackageInspection;
  onClose: () => void;
}) {
  const manifest = inspection.manifest;
  const identity = manifest?.package;
  const requirements = manifest?.requirements;
  const externalRequirements = [
    ...(requirements?.python_packages || []).map((item) => `Python: ${item}`),
    ...(requirements?.node_packages || []).map((item) => `Node: ${item}`),
    ...(requirements?.executables || []).map((item) => `程序: ${item}`),
  ];
  return (
    <div className="model-editor-backdrop" onMouseDown={onClose}>
      <section
        className="model-editor-dialog capability-package-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="capability-package-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="model-editor-header">
          <div>
            <h2 id="capability-package-title">
              {identity?.name || inspection.file_name || "能力包检查"}
            </h2>
            <p>由当前 Agent 完成只读安全检查，未执行或安装包内内容。</p>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose}>
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="model-editor-body capability-package-body">
          <div className={`capability-package-verdict ${inspection.valid ? "valid" : "invalid"}`}>
            <Icon name={inspection.valid ? "shield" : "info"} size={19} />
            <div>
              <strong>{inspection.valid ? "能力包格式与完整性检查通过" : "能力包未通过检查"}</strong>
              <span>{inspection.valid ? "这只说明归档结构有效，不代表已经信任或安装。" : "不会安装或执行此文件。"}</span>
            </div>
          </div>

          {identity && (
            <section className="capability-package-section">
              <h3>包信息</h3>
              <dl className="capability-package-facts">
                <div><dt>标识</dt><dd>{identity.id}</dd></div>
                <div><dt>版本</dt><dd>{identity.version}</dd></div>
                <div><dt>发布者</dt><dd>{identity.publisher || "未声明"}</dd></div>
                <div><dt>文件</dt><dd>{inspection.file_name} · {formatBytes(inspection.archive_size)}</dd></div>
              </dl>
              {identity.description && <p>{identity.description}</p>}
            </section>
          )}

          {manifest?.capabilities.length ? (
            <section className="capability-package-section">
              <h3>提供的能力</h3>
              <div className="capability-package-items">
                {manifest.capabilities.map((capability) => (
                  <div key={capability.id}>
                    <strong>{capability.name}</strong>
                    <span>{capability.summary || capability.id}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {manifest && (
            <section className="capability-package-section">
              <h3>权限声明</h3>
              {manifest.permissions.length ? (
                <div className="capability-package-tags">
                  {manifest.permissions.map((permission) => (
                    <span key={`${permission.category}:${permission.value}`}>
                      {permissionLabel(permission.category)} · {permission.value}
                    </span>
                  ))}
                </div>
              ) : <p>未声明额外权限。</p>}
            </section>
          )}

          {requirements && (
            <section className="capability-package-section">
              <h3>运行要求</h3>
              <p>
                xiaomei-brain {requirements.xiaomei_brain || "未限制"}
                {" · "}Python {requirements.python || "未限制"}
              </p>
              {externalRequirements.length > 0 && (
                <div className="capability-package-tags warning">
                  {externalRequirements.map((item) => <span key={item}>{item}</span>)}
                </div>
              )}
            </section>
          )}

          {inspection.errors.length > 0 && (
            <section className="capability-package-messages error">
              <strong>检查错误</strong>
              {inspection.errors.map((item) => <span key={item}>{item}</span>)}
            </section>
          )}
          {inspection.warnings.length > 0 && (
            <section className="capability-package-messages warning">
              <strong>注意</strong>
              {inspection.warnings.map((item) => <span key={item}>{item}</span>)}
            </section>
          )}
          <div className="capability-package-hash">SHA-256 · {inspection.sha256}</div>
        </div>

        <footer className="model-editor-footer capability-package-footer">
          <span>阶段 D1 仅提供检查预览，尚未安装到 Agent。</span>
          <Button variant="primary" onClick={onClose}>完成</Button>
        </footer>
      </section>
    </div>
  );
}

function permissionLabel(category: string): string {
  return ({
    filesystem: "文件",
    network: "网络",
    process: "进程",
    secrets: "凭证",
  } as Record<string, string>)[category] || category;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
