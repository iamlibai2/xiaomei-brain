import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { useCoreStore } from "../store";
import { Button } from "./ui";
import { BootstrapWizard } from "./bootstrap/BootstrapWizard";

interface IdentityPageProps {
  status: IdentityStatus;
  onReady: (status: IdentityStatus) => void;
  bootstrapMode?: "quick" | "custom" | "";
}

export function IdentityPage({ status, onReady, bootstrapMode }: IdentityPageProps) {
  const { t } = useTranslation();
  const resetIdentityState = useCoreStore((state) => state.resetIdentityState);
  const [creating, setCreating] = useState(!status.exists);
  const [restoring, setRestoring] = useState(false);
  const [selectedSubject, setSelectedSubject] = useState(
    status.activeSubject || status.subject || status.accounts[0]?.subject || "",
  );
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(status.error || "");

  useEffect(() => {
    setCreating(!status.exists);
    setRestoring(false);
    setSelectedSubject(
      status.activeSubject || status.subject || status.accounts[0]?.subject || "",
    );
  }, [status.activeSubject, status.exists, status.subject, status.accounts]);

  const selectedAccount = useMemo(
    () => status.accounts.find((account) => account.subject === selectedSubject),
    [selectedSubject, status.accounts],
  );

  const submit = async () => {
    if (restoring) {
      await importBackup();
      return;
    }
    if (creating && password !== confirmation) {
      setError(t("identity.passwordMismatch"));
      return;
    }
    setLoading(true);
    setError("");
    const result = creating
      ? await window.identity.create({ displayName, password })
      : await window.identity.unlock({ password, subject: selectedSubject });
    setLoading(false);
    if (!result.ok || !result.status) {
      setError(result.error || t("identity.failed"));
      return;
    }
    if (creating || selectedSubject !== status.activeSubject) resetIdentityState();
    onReady(result.status);
  };

  const importBackup = async () => {
    if (!password) {
      setError(t("identity.importPasswordRequired"));
      return;
    }
    setLoading(true);
    setError("");
    const result = await window.identity.importBackup({ password });
    setLoading(false);
    if (result.canceled) return;
    if (!result.ok || !result.status) {
      setError(result.error || t("identity.failed"));
      return;
    }
    resetIdentityState();
    onReady(result.status);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !loading) void submit();
  };

  const form = (
    <div className={bootstrapMode ? "bootstrap-identity-form" : ""}>
        {!creating && status.accounts.length > 1 && (
          <div className="connect-field">
            <label>{t("identity.account")}</label>
            <select
              value={selectedSubject}
              onChange={(event) => {
                setSelectedSubject(event.target.value);
                setPassword("");
                setError("");
              }}
            >
              {status.accounts.map((account) => (
                <option key={account.subject} value={account.subject}>
                  {account.displayName}
                </option>
              ))}
            </select>
          </div>
        )}

        {creating && !restoring && (
          <div className="connect-field">
            <label>{t("identity.displayName")}</label>
            <input
              autoFocus
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t("identity.displayNamePlaceholder")}
            />
          </div>
        )}

        <div className="connect-field">
          <label>{t(restoring ? "identity.backupPassword" : "identity.password")}</label>
          <input
            autoFocus={!creating}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("identity.passwordPlaceholder")}
          />
        </div>

        {creating && !restoring && (
          <div className="connect-field">
            <label>{t("identity.confirmPassword")}</label>
            <input
              type="password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              onKeyDown={handleKeyDown}
            />
          </div>
        )}

        {error && <p className="connect-error">{error}</p>}
        <div className="identity-login-actions">
          {(status.exists || restoring) && (
            <Button
              variant="secondary"
              size="md"
              icon={creating || restoring ? "chevron-left" : "plus"}
              className="identity-login-action"
              onClick={() => {
                if (restoring) {
                  setRestoring(false);
                } else {
                  setCreating((current) => !current);
                }
                setPassword("");
                setConfirmation("");
                setError("");
              }}
              disabled={loading}
            >
              {restoring
                ? t(creating ? "identity.backToCreate" : "identity.backToLogin")
                : creating ? t("identity.backToLogin") : t("identity.addLocalAccount")}
            </Button>
          )}
          {!restoring && (
            <Button
              variant="secondary"
              size="md"
              icon="file-text"
              className="identity-login-action"
              onClick={() => {
                setRestoring(true);
                setPassword("");
                setConfirmation("");
                setError("");
              }}
              disabled={loading}
            >
              {t("identity.importBackup")}
            </Button>
          )}
        </div>
    </div>
  );

  const primaryAction = (
    <Button
      variant="primary"
      size="lg"
      className={bootstrapMode ? "bootstrap-primary-action" : "connect-btn"}
      onClick={() => void submit()}
      disabled={loading || (restoring
        ? !password
        : creating
          ? !displayName.trim() || password.length < 8 || confirmation.length < 8
          : !selectedSubject || !password)}
    >
      {loading
        ? t("identity.processing")
        : restoring
          ? t("identity.importBackup")
          : bootstrapMode
            ? t("bootstrap.next")
            : creating ? t("identity.create") : t("identity.unlock")}
    </Button>
  );

  if (bootstrapMode) {
    return (
      <BootstrapWizard
        mode={bootstrapMode}
        current="identity"
        title={restoring ? t("identity.restoreTitle") : creating ? t("bootstrap.accountTitle") : t("identity.welcomeBack")}
        description={restoring
          ? t("identity.restoreDescription")
          : creating
            ? t("bootstrap.accountDescription")
            : t("identity.unlockDescription", { name: selectedAccount?.displayName || status.displayName || "" })}
        actions={primaryAction}
      >
        {form}
      </BootstrapWizard>
    );
  }

  return (
    <div className="connect-page">
      <div className="connect-card identity-card">
        <h1>{restoring ? t("identity.restoreTitle") : creating ? t("identity.createTitle") : t("identity.welcomeBack")}</h1>
        <p className="connect-subtitle">
          {restoring
            ? t("identity.restoreDescription")
            : creating
              ? t("identity.createDescription")
              : t("identity.unlockDescription", { name: selectedAccount?.displayName || status.displayName || "" })}
        </p>
        {form}
        {primaryAction}
      </div>
    </div>
  );
}
