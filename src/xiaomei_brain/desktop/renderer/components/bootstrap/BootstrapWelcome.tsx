import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon } from "../ui";

export function BootstrapWelcome({ onSelect }: {
  onSelect: (mode: "quick" | "custom") => Promise<void>;
}) {
  const { t } = useTranslation();
  const [working, setWorking] = useState(false);
  const [selected, setSelected] = useState<"quick" | "custom">("quick");

  const continueSetup = async () => {
    setWorking(true);
    try { await onSelect(selected); } finally { setWorking(false); }
  };

  return (
    <main className="bootstrap-flow">
      <section className="bootstrap-window bootstrap-welcome">
        <header className="bootstrap-titlebar">
          <span className="bootstrap-mark" aria-hidden="true">小</span>
          <strong>xiaomei-brain</strong>
        </header>
        <section className="bootstrap-content">
          <header className="bootstrap-page-heading bootstrap-welcome-heading">
            <h1>{t("bootstrap.welcomeTitle")}</h1>
            <p>{t("bootstrap.welcomeDescription")}</p>
          </header>
          <div className="bootstrap-mode-list">
            <button type="button" className={selected === "quick" ? "selected" : ""} onClick={() => setSelected("quick")}>
              <span className="bootstrap-mode-icon"><Icon name="sparkles" size={20} /></span>
              <span className="bootstrap-mode-copy"><strong>{t("bootstrap.quickTitle")}</strong><small>{t("bootstrap.quickDescription")}</small></span>
              <em>{t("bootstrap.recommended")}</em>
              <i aria-hidden="true">{selected === "quick" && <Icon name="check" size={13} />}</i>
            </button>
            <button type="button" className={selected === "custom" ? "selected" : ""} onClick={() => setSelected("custom")}>
              <span className="bootstrap-mode-icon"><Icon name="settings" size={20} /></span>
              <span className="bootstrap-mode-copy"><strong>{t("bootstrap.customTitle")}</strong><small>{t("bootstrap.customDescription")}</small></span>
              <i aria-hidden="true">{selected === "custom" && <Icon name="check" size={13} />}</i>
            </button>
          </div>
        </section>
        <footer className="bootstrap-footer">
          <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={working} onClick={() => void continueSetup()}>
            {working ? t("bootstrap.preparing") : t("bootstrap.next")}
          </Button>
        </footer>
      </section>
    </main>
  );
}
