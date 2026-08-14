import { useTranslation } from "react-i18next";
import type { CapabilityPackageInspection } from "../../types";
import { Button, Icon } from "../ui";

export function CapabilityPackageInspectionDialog({
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
              {installing
                ? (updating ? t("capabilityUi.updating") : t("capabilityUi.installing"))
                : (updating ? t("capabilityUi.updateAndEnable") : t("capabilityUi.installAndEnable"))}
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
