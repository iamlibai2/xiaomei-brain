import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { BootstrapStep } from "../../types";
import { BootstrapProgress } from "./BootstrapProgress";

export function BootstrapWizard({
  mode,
  current,
  title,
  description,
  preview = false,
  children,
  actions,
  className = "",
}: {
  mode: "quick" | "custom" | "";
  current: BootstrapStep;
  title: ReactNode;
  description: ReactNode;
  preview?: boolean;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <main className="bootstrap-flow">
      <section className={`bootstrap-window ${className}`.trim()}>
        <header className="bootstrap-titlebar">
          <span className="bootstrap-mark" aria-hidden="true">小</span>
          <strong>xiaomei-brain</strong>
        </header>
        <BootstrapProgress mode={mode} current={current} />
        <section className="bootstrap-content">
          {preview && <div className="bootstrap-preview-banner">{t("bootstrap.previewBanner")}</div>}
          <header className="bootstrap-page-heading">
            <h1>{title}</h1>
            <p>{description}</p>
          </header>
          <div className="bootstrap-page-body">{children}</div>
        </section>
        {actions && <footer className="bootstrap-footer">{actions}</footer>}
      </section>
    </main>
  );
}
