import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { Button } from "./ui";

interface IdentityPageProps {
  status: IdentityStatus;
  onReady: (status: IdentityStatus) => void;
}

export function IdentityPage({ status, onReady }: IdentityPageProps) {
  const { t } = useTranslation();
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(status.error || "");

  const submit = async () => {
    if (!status.exists && password !== confirmation) {
      setError(t("identity.passwordMismatch"));
      return;
    }
    setLoading(true);
    setError("");
    const result = status.exists
      ? await window.identity.unlock({ password })
      : await window.identity.create({ displayName, password });
    setLoading(false);
    if (!result.ok || !result.status) {
      setError(result.error || t("identity.failed"));
      return;
    }
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
    onReady(result.status);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !loading) void submit();
  };

  return (
    <div className="connect-page">
      <div className="connect-card identity-card">
        <h1>{status.exists ? t("identity.welcomeBack") : t("identity.createTitle")}</h1>
        <p className="connect-subtitle">
          {status.exists
            ? t("identity.unlockDescription", { name: status.displayName || "" })
            : t("identity.createDescription")}
        </p>

        {!status.exists && (
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
          <label>{t("identity.password")}</label>
          <input
            autoFocus={status.exists}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("identity.passwordPlaceholder")}
          />
        </div>

        {!status.exists && (
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

        <p className="identity-note">{t("identity.localOnly")}</p>
        {error && <p className="connect-error">{error}</p>}
        <Button
          variant="primary"
          size="lg"
          className="connect-btn"
          onClick={() => void submit()}
          disabled={loading}
        >
          {loading
            ? t("identity.processing")
            : status.exists ? t("identity.unlock") : t("identity.create")}
        </Button>
        {!status.exists && (
          <Button
            variant="ghost"
            size="lg"
            className="identity-import-btn"
            onClick={() => void importBackup()}
            disabled={loading}
          >
            {t("identity.importBackup")}
          </Button>
        )}
      </div>
    </div>
  );
}
