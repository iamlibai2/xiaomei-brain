import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  AgentCapability,
  CapabilityPackageInspection,
  CapabilityStatus,
  InstalledCapabilityPackage,
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

const STATUS_KEYS: Record<CapabilityStatus, string> = {
  not_acquired: "statusNotAcquired",
  disabled: "statusDisabled",
  preparing: "statusPreparing",
  needs_setup: "statusNeedsSetup",
  ready: "statusReady",
  degraded: "statusDegraded",
  unavailable: "statusUnavailable",
  error: "statusError",
};

export function CapabilitySettingsPanel({
  agentId,
  connected,
  target = "",
  onTargetConsumed,
  onNavigate,
}: Props) {
  const { t } = useTranslation();
  const [capabilities, setCapabilities] = useState<AgentCapability[]>([]);
  const [packages, setPackages] = useState<InstalledCapabilityPackage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [changingId, setChangingId] = useState("");
  const [packageBusy, setPackageBusy] = useState(false);
  const [packageError, setPackageError] = useState("");
  const [packageNotice, setPackageNotice] = useState("");
  const [changingPackageId, setChangingPackageId] = useState("");
  const [packageInspection, setPackageInspection] = useState<CapabilityPackageInspection | null>(null);
  const [highlightedId, setHighlightedId] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!connected) {
      setCapabilities([]);
      setPackages([]);
      setError("");
      return;
    }
    setLoading(true);
    try {
      const [response, packageResponse] = await Promise.all([
        window.gateway.listCapabilities({ agentId }),
        window.gateway.listCapabilityPackages({ agentId }),
      ]);
      if (response.error) throw new Error(response.error.message);
      if (packageResponse.error) throw new Error(packageResponse.error.message);
      const values = response.result?.capabilities;
      const packageValues = packageResponse.result?.packages;
      setCapabilities(Array.isArray(values) ? values as AgentCapability[] : []);
      setPackages(Array.isArray(packageValues) ? packageValues as InstalledCapabilityPackage[] : []);
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
    setPackageNotice("");
    try {
      const response = await window.gateway.inspectCapabilityPackage({ agentId });
      if (response.error) throw new Error(response.error.message);
      if (response.result?.canceled) return;
      const inspection = response.result?.inspection;
      if (!inspection || typeof inspection !== "object" || Array.isArray(inspection)) {
        throw new Error(t("capabilityUi.invalidInspection"));
      }
      setPackageInspection(inspection as unknown as CapabilityPackageInspection);
    } catch (inspectError) {
      setPackageError(inspectError instanceof Error ? inspectError.message : String(inspectError));
    } finally {
      setPackageBusy(false);
    }
  }, [agentId]);

  const installPackage = useCallback(async (inspection: CapabilityPackageInspection) => {
    setPackageBusy(true);
    setPackageError("");
    setPackageNotice("");
    try {
      const response = await window.gateway.installCapabilityPackage({
        agentId,
        sha256: inspection.sha256,
      });
      if (response.error) throw new Error(response.error.message);
      const operation = response.result?.operation;
      const affectedAgents = Array.isArray(response.result?.affected_agents)
        ? response.result.affected_agents.length
        : 0;
      setPackageInspection(null);
      await load();
      setPackageNotice(operation === "upgraded"
        ? t("capabilityUi.upgradeNotice", { suffix: affectedAgents ? ` (${affectedAgents})` : "" })
        : t("capabilityUi.installNotice"));
    } catch (installError) {
      setPackageError(installError instanceof Error ? installError.message : String(installError));
      await load();
    } finally {
      setPackageBusy(false);
    }
  }, [agentId, load]);

  const uninstallPackage = useCallback(async (item: InstalledCapabilityPackage) => {
    if (!window.confirm(t("capabilityUi.confirmUninstall", { name: item.name }))) return;
    setChangingPackageId(item.id);
    setPackageError("");
    setPackageNotice("");
    try {
      const response = await window.gateway.uninstallCapabilityPackage({
        agentId,
        packageId: item.id,
      });
      if (response.error) throw new Error(response.error.message);
      const affected = Array.isArray(response.result?.affected_agents)
        ? response.result.affected_agents.length
        : 0;
      await load();
      setPackageNotice(t("capabilityUi.uninstallNotice", { suffix: affected ? ` (${affected})` : "" }));
    } catch (uninstallError) {
      setPackageError(uninstallError instanceof Error ? uninstallError.message : String(uninstallError));
    } finally {
      setChangingPackageId("");
    }
  }, [agentId, load]);

  const setPackageActive = useCallback(async (item: InstalledCapabilityPackage, active: boolean) => {
    setChangingPackageId(item.id);
    setPackageError("");
    setPackageNotice("");
    try {
      const response = await window.gateway.setCapabilityPackageActive({
        agentId,
        packageId: item.id,
        version: item.version,
        sha256: item.sha256,
        active,
      });
      if (response.error) throw new Error(response.error.message);
      await load();
      setPackageNotice(active
        ? t("capabilityUi.enableNotice")
        : t("capabilityUi.disableNotice"),
      );
    } catch (changeError) {
      setPackageError(changeError instanceof Error ? changeError.message : String(changeError));
    } finally {
      setChangingPackageId("");
    }
  }, [agentId, load]);

  return (
    <div className="capability-settings-page">
      <div className="capability-page-heading">
        <div>
          <h2>{t("capabilityUi.title")}</h2>
          <p>{t("capabilityUi.description")}</p>
        </div>
        <div className="capability-page-actions">
          <Button
            variant="secondary"
            size="sm"
            icon="folder"
            disabled={packageBusy || !connected}
            onClick={() => void inspectPackage()}
          >
            {packageBusy ? t("capabilityUi.checking") : t("capabilityUi.import")}
          </Button>
          <Button variant="ghost" size="sm" icon="refresh" disabled={loading || !connected} onClick={() => void load()}>
            {loading ? t("capabilityUi.refreshing") : t("capabilityUi.refresh")}
          </Button>
        </div>
      </div>

      {packageError && <div className="settings-error capability-package-error">{packageError}</div>}
      {packageNotice && <div className="settings-notice capability-package-error">{packageNotice}</div>}

      {!connected && (
        <div className="settings-empty capability-empty">
          <Icon name="sparkles" size={22} />
          <strong>{t("capabilityUi.connectTitle")}</strong>
          <span>{t("capabilityUi.connectDescription")}</span>
        </div>
      )}
      {connected && !loading && !error && capabilities.length === 0 && (
        <div className="settings-empty capability-empty">
          <strong>{t("capabilityUi.noDeclaredTitle")}</strong>
          <span>{t("capabilityUi.noDeclaredDescription")}</span>
        </div>
      )}
      {error && (
        <div className="settings-error capability-load-error">
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={() => void load()}>{t("capabilityUi.retry")}</Button>
        </div>
      )}

      {packages.length > 0 && (
        <section className="capability-installed-section">
          <div className="settings-card-heading">
            <div>
              <h3>{t("capabilityUi.installedPackages")}</h3>
              <p>{t("capabilityUi.installedHint")}</p>
            </div>
          </div>
          <div className="capability-package-list">
            {packages.map((item) => (
              <article key={`${item.id}:${item.version}`} className="capability-package-row">
                <span className="model-library-icon"><Icon name="folder" size={16} /></span>
                <div className="capability-package-row-copy">
                  <strong>{item.name}</strong>
                  <span>{item.id} · {item.version}</span>
                  <small>{packageRuntimeLabel(item, t)}</small>
                  {item.issue && <small className="error">{item.issue}</small>}
                </div>
                <span className={`capability-package-state ${item.active ? "active" : ""} ${item.runtime_valid ? "" : "error"}`}>
                  {!item.runtime_valid ? t("capabilityUi.packageError") : item.active ? t("capabilityUi.packageEnabled") : t("capabilityUi.packageDisabled")}
                </span>
                <button
                  type="button"
                  className={`desktop-switch capability-toggle ${item.active ? "is-on" : ""}`}
                  role="switch"
                  aria-label={`${item.active ? t("capabilityUi.disable") : t("capabilityUi.enable")}${item.name}`}
                  aria-checked={item.active}
                  disabled={changingPackageId === item.id || !item.runtime_valid}
                  onClick={() => void setPackageActive(item, !item.active)}
                >
                  <span />
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  icon="trash"
                  title={`${t("capabilityUi.uninstall")}${item.name}`}
                  aria-label={`${t("capabilityUi.uninstall")}${item.name}`}
                  disabled={changingPackageId === item.id}
                  onClick={() => void uninstallPackage(item)}
                />
              </article>
            ))}
          </div>
        </section>
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
          installing={packageBusy}
          actionError={packageError}
          updating={Boolean(
            packageInspection.manifest?.package.id
            && packages.some((item) => (
              item.id === packageInspection.manifest?.package.id
              && item.version !== packageInspection.manifest?.package.version
            )),
          )}
          onInstall={() => void installPackage(packageInspection)}
          onClose={() => setPackageInspection(null)}
        />
      )}
    </div>
  );
}

function CapabilityPackageInspectionDialog({
  inspection,
  installing,
  actionError,
  updating,
  onInstall,
  onClose,
}: {
  inspection: CapabilityPackageInspection;
  installing: boolean;
  actionError: string;
  updating: boolean;
  onInstall: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const manifest = inspection.manifest;
  const identity = manifest?.package;
  const requirements = manifest?.requirements;
  const externalRequirements = [
    ...(requirements?.python_packages || []).map((item) => `Python: ${item}`),
    ...(requirements?.node_packages || []).map((item) => `Node: ${item}`),
    ...(requirements?.executables || []).map((item) => `${t("capabilityUi.program")}: ${item}`),
  ];
  const installable = inspection.valid && externalRequirements.length === 0;
  return (
    <div className="model-editor-backdrop" onMouseDown={() => !installing && onClose()}>
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
              {identity?.name || inspection.file_name || t("capabilityUi.packageCheck")}
            </h2>
            <p>{t("capabilityUi.inspectionDescription")}</p>
          </div>
          <button type="button" aria-label={t("capabilityUi.close")} disabled={installing} onClick={onClose}>
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="model-editor-body capability-package-body">
          <div className={`capability-package-verdict ${inspection.valid ? "valid" : "invalid"}`}>
            <Icon name={inspection.valid ? "shield" : "info"} size={19} />
            <div>
              <strong>{inspection.valid ? t("capabilityUi.inspectionPassed") : t("capabilityUi.inspectionFailed")}</strong>
              <span>{inspection.valid ? t("capabilityUi.inspectionPassedHint") : t("capabilityUi.inspectionFailedHint")}</span>
            </div>
          </div>

          {identity && (
            <section className="capability-package-section">
              <h3>{t("capabilityUi.packageInfo")}</h3>
              <dl className="capability-package-facts">
                <div><dt>{t("capabilityUi.identifier")}</dt><dd>{identity.id}</dd></div>
                <div><dt>{t("capabilityUi.version")}</dt><dd>{identity.version}</dd></div>
                <div><dt>{t("capabilityUi.publisher")}</dt><dd>{identity.publisher || t("capabilityUi.undeclared")}</dd></div>
                <div><dt>{t("capabilityUi.file")}</dt><dd>{inspection.file_name} · {formatBytes(inspection.archive_size)}</dd></div>
              </dl>
              {identity.description && <p>{identity.description}</p>}
            </section>
          )}

          {manifest?.capabilities.length ? (
            <section className="capability-package-section">
              <h3>{t("capabilityUi.providedCapabilities")}</h3>
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
              <h3>{t("capabilityUi.permissions")}</h3>
              {manifest.permissions.length ? (
                <div className="capability-package-tags">
                  {manifest.permissions.map((permission) => (
                    <span key={`${permission.category}:${permission.value}`}>
                      {permissionLabel(permission.category, t)} · {permission.value}
                    </span>
                  ))}
                </div>
              ) : <p>{t("capabilityUi.noExtraPermissions")}</p>}
            </section>
          )}

          {requirements && (
            <section className="capability-package-section">
              <h3>{t("capabilityUi.requirements")}</h3>
              <p>
                xiaomei-brain {requirements.xiaomei_brain || t("capabilityUi.unlimited")}
                {" · "}Python {requirements.python || t("capabilityUi.unlimited")}
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
              <strong>{t("capabilityUi.checkErrors")}</strong>
              {inspection.errors.map((item) => <span key={item}>{item}</span>)}
            </section>
          )}
          {inspection.warnings.length > 0 && (
            <section className="capability-package-messages warning">
              <strong>{t("capabilityUi.warnings")}</strong>
              {inspection.warnings.map((item) => <span key={item}>{item}</span>)}
            </section>
          )}
          {actionError && (
            <section className="capability-package-messages error">
              <strong>{t("capabilityUi.installFailed")}</strong>
              <span>{actionError}</span>
            </section>
          )}
          <div className="capability-package-hash">SHA-256 · {inspection.sha256}</div>
        </div>

        <footer className="model-editor-footer capability-package-footer">
          <span>{installable
            ? t("capabilityUi.installHint")
            : t("capabilityUi.cannotInstall")}</span>
          <div>
            <Button variant="secondary" disabled={installing} onClick={onClose}>{t("capabilityUi.cancel")}</Button>
            <Button variant="primary" disabled={!installable || installing} onClick={onInstall}>
              {installing ? (updating ? t("capabilityUi.updating") : t("capabilityUi.installing")) : (updating ? t("capabilityUi.updateAndEnable") : t("capabilityUi.installAndEnable"))}
            </Button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function permissionLabel(category: string, t: (key: string) => string): string {
  const keys: Record<string, string> = {
    filesystem: "capabilityUi.filePermission",
    network: "capabilityUi.networkPermission",
    process: "capabilityUi.processPermission",
    secrets: "capabilityUi.secretsPermission",
  };
  return keys[category] ? t(keys[category]) : category;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function packageRuntimeLabel(item: InstalledCapabilityPackage, t: (key: string) => string): string {
  if (!item.runtime_valid) return t("capabilityUi.packageCheckError");
  if (item.active && item.loaded) return t("capabilityUi.packageLoaded");
  if (item.active) return t("capabilityUi.packageRestartLoad");
  if (item.loaded) return t("capabilityUi.packageRestartUnload");
  return t("capabilityUi.packageReady");
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
  const { t } = useTranslation();
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
            {STATUS_KEYS[capability.status] ? t(`capabilityUi.${STATUS_KEYS[capability.status]}`) : capability.status}
          </span>
          <button
            type="button"
            className={`desktop-switch capability-toggle ${capability.enabled ? "is-on" : ""}`}
            role="switch"
            aria-label={`${capability.enabled ? t("capabilityUi.disableCapability") : t("capabilityUi.enableCapability")}${capability.name}`}
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
            <strong>{t("capabilityUi.setupNeeded")}</strong>
            <span>{issueWithAction.message}</span>
          </div>
          <Button variant="secondary" size="sm" onClick={() => onNavigate(setupAction.section, setupAction.target)}>
            {setupAction.label}
          </Button>
        </div>
      )}

      {capability.examples.length > 0 && (
        <div className="capability-examples">
          <span>{t("capabilityUi.sayThis")}</span>
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
