import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui";
import { BootstrapWizard } from "./BootstrapWizard";

export function BootstrapAgentSetup({ preview, onComplete }: {
  preview: boolean;
  onComplete: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(t("bootstrap.defaultAgentName"));
  const [description, setDescription] = useState(t("bootstrap.defaultAgentRole"));
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!name.trim() || !description.trim()) {
      setError(t("bootstrap.agentSetup.incomplete"));
      return;
    }
    setWorking(true);
    setError("");
    try {
      const result = preview
        ? await window.bootstrap.advancePreview()
        : await window.bootstrap.provisionInitialAgent({ name: name.trim(), description: description.trim() });
      if (!result.ok) throw new Error(result.error || t("bootstrap.operationFailed"));
      await onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setWorking(false);
    }
  };

  return (
    <BootstrapWizard
      mode="custom"
      current="agent"
      preview={preview}
      title={t("bootstrap.agentSetup.title")}
      description={t("bootstrap.agentSetup.description")}
      actions={(
        <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={working} onClick={() => void submit()}>
          {working ? t("bootstrap.creatingAgent") : t("bootstrap.next")}
        </Button>
      )}
    >
      <div className="bootstrap-form bootstrap-agent-form">
        <label>
          <span>{t("bootstrap.agentSetup.name")}</span>
          <input value={name} maxLength={80} disabled={working} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>{t("bootstrap.agentSetup.responsibility")}</span>
          <textarea value={description} maxLength={500} disabled={working} rows={4} onChange={(event) => setDescription(event.target.value)} />
          <small>{t("bootstrap.agentSetup.responsibilityHint")}</small>
        </label>
      </div>
      {error && <div className="setup-error"><span>{error}</span></div>}
    </BootstrapWizard>
  );
}
