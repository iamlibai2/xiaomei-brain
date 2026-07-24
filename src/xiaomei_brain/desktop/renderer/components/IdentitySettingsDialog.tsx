import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { useCoreStore } from "../store";
import { Button } from "./ui";

interface IdentitySettingsDialogProps {
  onClose: () => void;
}

interface LegacySession {
  session_id: string;
  first_user_message: string;
  message_count: number;
  updated_at: number;
  legacy_user_ids: string[];
}

export function IdentitySettingsDialog({ onClose }: IdentitySettingsDialogProps) {
  const { t } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const disconnectAgent = useCoreStore((state) => state.disconnectAgent);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const searchSessions = useCoreStore((state) => state.searchSessions);
  const [status, setStatus] = useState<IdentityStatus | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [legacySessions, setLegacySessions] = useState<LegacySession[]>([]);
  const [claimingSessionId, setClaimingSessionId] = useState("");
  const activeAgent = agents.find((agent) => agent.id === activeAgentId);
  const isLocalAgent = Boolean(
    activeAgent
    && (
      activeAgent.source === "local"
      || ["localhost", "127.0.0.1", "::1"].includes(activeAgent.host.toLowerCase())
    ),
  );
  const canManageLegacy = Boolean(
    activeAgent
    && isLocalAgent
    && connectionByAgent[activeAgent.id]?.status === "connected",
  );
  const [legacyLoading, setLegacyLoading] = useState(false);
  const [legacyError, setLegacyError] = useState("");

  useEffect(() => {
    void window.identity.status().then(setStatus);
  }, []);

  useEffect(() => {
    if (!activeAgentId || !canManageLegacy) {
      setLegacySessions([]);
      setLegacyError("");
      return;
    }
    let cancelled = false;
    setLegacyLoading(true);
    setLegacyError("");
    void window.gateway.listLegacySessions({ agentId: activeAgentId }).then((response) => {
      if (cancelled) return;
      if (response.error) {
        setLegacyError(response.error.message);
        return;
      }
      const values = response.result?.sessions;
      setLegacySessions(Array.isArray(values) ? values as LegacySession[] : []);
    }).catch((loadError) => {
      if (!cancelled) setLegacyError(String(loadError));
    }).finally(() => {
      if (!cancelled) setLegacyLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [activeAgentId, canManageLegacy]);

  const changePassword = async () => {
    if (newPassword !== confirmation) {
      setError(t("identity.passwordMismatch"));
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    const result = await window.identity.changePassword({ currentPassword, newPassword });
    setBusy(false);
    if (!result.ok) {
      setError(result.error || t("identity.failed"));
      return;
    }
    setCurrentPassword("");
    setNewPassword("");
    setConfirmation("");
    setMessage(t("identity.passwordChanged"));
  };

  const exportBackup = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    const result = await window.identity.exportBackup();
    setBusy(false);
    if (result.canceled) return;
    if (!result.ok) {
      setError(result.error || t("identity.failed"));
      return;
    }
    setMessage(t("identity.backupExported"));
  };

  const lockIdentity = async () => {
    setBusy(true);
    await Promise.all(agents.map((agent) => disconnectAgent(agent.id)));
    const nextStatus = await window.identity.lock();
    window.dispatchEvent(new CustomEvent("xiaomei:identity-locked", { detail: nextStatus }));
    onClose();
  };

  const claimLegacySession = async (session: LegacySession) => {
    if (!activeAgentId) return;
    const confirmed = window.confirm(t("identity.claimLegacyConfirm", {
      count: session.message_count,
    }));
    if (!confirmed) return;
    setClaimingSessionId(session.session_id);
    setError("");
    const response = await window.gateway.claimLegacySession({
      agentId: activeAgentId,
      sessionId: session.session_id,
    });
    setClaimingSessionId("");
    if (response.error) {
      setError(response.error.message);
      return;
    }
    setLegacySessions((current) => current.filter(
      (item) => item.session_id !== session.session_id,
    ));
    await searchSessions("");
    setMessage(t("identity.legacyClaimed"));
  };

  return (
    <div className="identity-settings-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="identity-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="identity-settings-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="identity-settings-header">
          <div>
            <h2 id="identity-settings-title">{t("identity.settingsTitle")}</h2>
            <p>{t("identity.settingsDescription")}</p>
          </div>
          <button onClick={onClose} aria-label={t("about.close")}>×</button>
        </header>

        {status && (
          <div className="identity-summary">
            <div className="identity-avatar">{(status.displayName || "?").charAt(0)}</div>
            <div>
              <strong>{status.displayName}</strong>
              <code title={status.subject}>{status.subject?.slice(0, 16)}…</code>
            </div>
          </div>
        )}

        <div className="identity-settings-section">
          <h3>{t("identity.backupTitle")}</h3>
          <p>{t("identity.backupDescription")}</p>
          <Button variant="secondary" onClick={() => void exportBackup()} disabled={busy}>
            {t("identity.exportBackup")}
          </Button>
        </div>

        <div className="identity-settings-section">
          <h3>{t("identity.legacyTitle")}</h3>
          <p>{t("identity.legacyDescription")}</p>
          {!activeAgent ? (
            <p className="identity-empty">{t("identity.legacySelectAgent")}</p>
          ) : !isLocalAgent ? (
            <p className="identity-empty">{t("identity.legacyLocalOnly")}</p>
          ) : !canManageLegacy ? (
            <p className="identity-empty">{t("identity.legacyConnectAgent", { name: activeAgent.name })}</p>
          ) : legacyLoading ? (
            <p className="identity-empty">{t("identity.legacyLoading")}</p>
          ) : legacyError ? (
            <p className="connect-error">{legacyError}</p>
          ) : legacySessions.length === 0 ? (
              <p className="identity-empty">{t("identity.noLegacySessions")}</p>
          ) : (
            <div className="identity-legacy-list">
              {legacySessions.map((session) => (
                <div className="identity-legacy-item" key={session.session_id}>
                  <div>
                    <strong>{session.first_user_message || session.session_id}</strong>
                    <span>
                      {t("identity.legacyMeta", {
                        count: session.message_count,
                        ids: session.legacy_user_ids.join(", "),
                      })}
                    </span>
                  </div>
                  <Button
                    variant="secondary"
                    disabled={busy || claimingSessionId === session.session_id}
                    onClick={() => void claimLegacySession(session)}
                  >
                    {claimingSessionId === session.session_id
                      ? t("identity.processing")
                      : t("identity.claimLegacy")}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="identity-settings-section">
          <h3>{t("identity.changePasswordTitle")}</h3>
          <div className="connect-field">
            <label>{t("identity.currentPassword")}</label>
            <input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
          </div>
          <div className="identity-password-row">
            <div className="connect-field">
              <label>{t("identity.newPassword")}</label>
              <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </div>
            <div className="connect-field">
              <label>{t("identity.confirmPassword")}</label>
              <input type="password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
            </div>
          </div>
          <Button
            variant="secondary"
            onClick={() => void changePassword()}
            disabled={busy || !currentPassword || !newPassword}
          >
            {t("identity.changePassword")}
          </Button>
        </div>

        {message && <p className="identity-settings-message">{message}</p>}
        {error && <p className="connect-error">{error}</p>}

        <footer className="identity-settings-footer">
          <Button variant="ghost" onClick={() => void lockIdentity()} disabled={busy}>
            {t("identity.lockNow")}
          </Button>
          <Button variant="primary" onClick={onClose}>{t("identity.done")}</Button>
        </footer>
      </section>
    </div>
  );
}
