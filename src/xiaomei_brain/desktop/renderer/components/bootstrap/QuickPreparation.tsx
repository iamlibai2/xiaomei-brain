import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui";
import { BootstrapWizard } from "./BootstrapWizard";

export function QuickPreparation({ task = "environment", onComplete }: {
  task?: "environment" | "agent";
  onComplete: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const started = useRef(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let cancelled = false;
    const operation = task === "agent"
      ? window.bootstrap.provisionInitialAgent()
      : window.bootstrap.prepareQuick();
    void operation.then(async (result) => {
      if (cancelled) return;
      if (!result.ok) throw new Error(result.error || t("bootstrap.operationFailed"));
      if (task === "agent") {
        await onComplete();
        return;
      }
      // The initial Agent is part of installation, not a user-facing setup
      // decision. Create it quietly before account registration.
      if (!result.status?.preview) {
        const provisioned = await window.bootstrap.provisionInitialAgent();
        if (!provisioned.ok) throw new Error(provisioned.error || t("bootstrap.operationFailed"));
      }
      if (!cancelled) setComplete(true);
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { cancelled = true; };
  }, [attempt, onComplete, t, task]);

  if (task === "agent") {
    return (
      <BootstrapWizard mode="quick" current="agent" title={t("bootstrap.quickAgentPreparing")} description={t("bootstrap.quickAgentPreparingDescription")}>
        <div className="quick-installation-progress">
          <div className="quick-installation-track"><span /></div>
        </div>
      </BootstrapWizard>
    );
  }

  return (
    <BootstrapWizard
      mode="quick"
      current="runtime"
      title={error ? t("bootstrap.quickFailed") : complete ? t("bootstrap.quickReadyTitle") : t("bootstrap.quickPreparing")}
      description={error || (complete ? t("bootstrap.quickReadyDescription") : t("bootstrap.quickPreparingDescription"))}
      actions={complete ? (
        <Button variant="primary" size="lg" className="bootstrap-primary-action" onClick={() => void onComplete()}>
          {t("bootstrap.next")}
        </Button>
      ) : undefined}
    >
      <div className="quick-installation-progress">
        <div className={`quick-installation-track ${complete ? "is-complete" : ""}`}><span /></div>
        {!complete && <p>{t("bootstrap.quickInstallingStatus")}</p>}
      </div>
      {error && (
        <div className="bootstrap-error-actions quick-installation-actions">
          <Button variant="primary" size="md" onClick={() => {
            started.current = false;
            setError("");
            setComplete(false);
            setAttempt((value) => value + 1);
          }}>{t("common.retry")}</Button>
          <Button variant="secondary" size="md" onClick={() => void window.desktop.openLogDirectory()}>{t("bootstrap.openLogs")}</Button>
        </div>
      )}
    </BootstrapWizard>
  );
}
