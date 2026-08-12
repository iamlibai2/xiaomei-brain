import { useTranslation } from "react-i18next";
import { Button } from "../ui";

export function BootstrapScreen({ error = "", onRetry }: {
  error?: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <main className="bootstrap-screen" role="status">
      <section className="bootstrap-loading-card">
        <span className="bootstrap-mark" aria-hidden="true">小</span>
        <h1>{error ? t("bootstrap.statusFailed") : t("bootstrap.starting")}</h1>
        <p>{error || t("bootstrap.readingState")}</p>
        {!error && <span className="bootstrap-spinner" aria-hidden="true" />}
        {error && onRetry && (
          <div className="bootstrap-error-actions">
            <Button variant="primary" size="md" onClick={onRetry}>{t("common.retry")}</Button>
            <Button variant="secondary" size="md" onClick={() => void window.desktop.openLogDirectory()}>
              {t("bootstrap.openLogs")}
            </Button>
          </div>
        )}
      </section>
    </main>
  );
}
