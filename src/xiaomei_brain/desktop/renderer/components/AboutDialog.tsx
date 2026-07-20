import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDesktopInfo } from "../desktop-info";
import { Button } from "./ui";

export function AboutDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const info = useDesktopInfo();
  const [showLog, setShowLog] = useState(false);
  const [logContent, setLogContent] = useState("");
  const [logLoading, setLogLoading] = useState(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function loadLog() {
    setLogLoading(true);
    setActionError("");
    try {
      const result = await window.desktop.readLog();
      setLogContent(result.content || t("about.emptyLog"));
      setShowLog(true);
    } catch (error) {
      setActionError(String(error));
    } finally {
      setLogLoading(false);
    }
  }

  async function openDirectory(kind: "config" | "log") {
    setActionError("");
    const result = kind === "config"
      ? await window.desktop.openConfigDirectory()
      : await window.desktop.openLogDirectory();
    if (!result.ok) setActionError(result.error || t("about.openFailed"));
  }

  return (
    <div className="about-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className={`about-dialog ${showLog ? "with-log" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="about-header">
          <div>
            <h2 id="about-title">xiaomei-brain Desktop</h2>
            <p>{t("about.subtitle")}</p>
          </div>
          <button className="about-close" onClick={onClose} aria-label={t("about.close")}>×</button>
        </header>

        {info ? (
          <div className="about-details">
            <InfoRow label={t("about.version")} value={info.version} />
            <InfoRow
              label={t("about.environment")}
              value={`${t(`about.${info.environment}`)} · ${info.platform} ${info.arch}`}
            />
            <InfoRow label={t("about.runtime")} value={`Electron ${info.electronVersion} · Node.js ${info.nodeVersion}`} />
            <InfoRow label={t("about.configDirectory")} value={info.configDirectory} />
            <InfoRow label={t("about.agentDirectory")} value={info.agentDirectory} />
            <InfoRow label={t("about.logDirectory")} value={info.logDirectory} />
          </div>
        ) : (
          <div className="about-loading">{t("about.loading")}</div>
        )}

        <div className="about-actions">
          <Button variant="secondary" size="sm" onClick={() => { void openDirectory("config"); }}>
            {t("about.openConfigDirectory")}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => { void openDirectory("log"); }}>
            {t("about.openLogDirectory")}
          </Button>
          <Button variant="primary" size="sm" disabled={logLoading} onClick={() => { void loadLog(); }}>
            {logLoading ? t("about.loadingLog") : t("about.viewLog")}
          </Button>
        </div>

        {actionError && <div className="about-error">{actionError}</div>}
        {showLog && (
          <div className="about-log-panel">
            <div className="about-log-header">
              <span>{t("about.desktopLog")}</span>
              <button onClick={() => setShowLog(false)}>{t("about.hideLog")}</button>
            </div>
            <pre>{logContent}</pre>
          </div>
        )}
      </section>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="about-info-row">
      <span>{label}</span>
      <code title={value}>{value}</code>
    </div>
  );
}
