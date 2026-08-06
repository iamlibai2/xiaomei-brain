import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { useCoreStore } from "../store";
import { Button, Icon } from "./ui";
import { PersonBiometricModal } from "./PersonBiometricModal";

interface IdentitySettingsDialogProps {
  onClose: () => void;
  embedded?: boolean;
}

type AccountAction = {
  type: "switch" | "password" | "delete";
  subject: string;
} | null;

export function IdentitySettingsDialog({ onClose, embedded = false }: IdentitySettingsDialogProps) {
  const { t } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const disconnectAgent = useCoreStore((state) => state.disconnectAgent);
  const resetIdentityState = useCoreStore((state) => state.resetIdentityState);
  const [status, setStatus] = useState<IdentityStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [addingAccount, setAddingAccount] = useState(false);
  const [importingAccount, setImportingAccount] = useState(false);
  const [action, setAction] = useState<AccountAction>(null);
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountPassword, setNewAccountPassword] = useState("");
  const [newAccountConfirmation, setNewAccountConfirmation] = useState("");
  const [showBiometrics, setShowBiometrics] = useState(false);

  const connectedAgents = agents.filter(
    (agent) => connectionByAgent[agent.id]?.status === "connected",
  );

  useEffect(() => {
    void window.identity.status().then(setStatus);
  }, []);

  const publishStatus = (nextStatus: IdentityStatus, locked = false) => {
    setStatus(nextStatus);
    window.dispatchEvent(new CustomEvent(
      locked ? "xiaomei:identity-locked" : "xiaomei:identity-status-changed",
      { detail: nextStatus },
    ));
  };

  const disconnectAll = async () => {
    await Promise.all(agents.map((agent) => disconnectAgent(agent.id)));
    resetIdentityState();
  };

  const clearFeedback = () => {
    setError("");
    setMessage("");
  };

  const openAction = (type: NonNullable<AccountAction>["type"], subject: string) => {
    clearFeedback();
    setAction({ type, subject });
    setPassword("");
    setNewPassword("");
    setConfirmation("");
  };

  const closeAction = () => {
    setAction(null);
    setPassword("");
    setNewPassword("");
    setConfirmation("");
  };

  const createAccount = async () => {
    if (!newAccountName.trim()) return setError(t("identityUi.nameRequired"));
    if (newAccountPassword !== newAccountConfirmation) {
      return setError(t("identity.passwordMismatch"));
    }
    setBusy("create");
    clearFeedback();
    const result = await window.identity.create({
      displayName: newAccountName,
      password: newAccountPassword,
    });
    if (!result.ok || !result.status) {
      setBusy("");
      return setError(result.error || t("identity.failed"));
    }
    await disconnectAll();
    publishStatus(result.status);
    setAddingAccount(false);
    setNewAccountName("");
    setNewAccountPassword("");
    setNewAccountConfirmation("");
    setBusy("");
    setMessage(t("identityUi.created", { name: result.status.displayName || newAccountName }));
  };

  const switchAccount = async (subject: string) => {
    if (!password) return;
    setBusy(`switch:${subject}`);
    clearFeedback();
    const result = await window.identity.unlock({ subject, password });
    if (!result.ok || !result.status) {
      setBusy("");
      return setError(result.error || t("identity.failed"));
    }
    await disconnectAll();
    publishStatus(result.status);
    closeAction();
    setBusy("");
    setMessage(t("identityUi.switched", { name: result.status.displayName || t("common.unknown") }));
  };

  const changePassword = async (subject: string) => {
    if (newPassword !== confirmation) return setError(t("identity.passwordMismatch"));
    setBusy(`password:${subject}`);
    clearFeedback();
    const result = await window.identity.changePassword({
      subject,
      currentPassword: password,
      newPassword,
    });
    if (!result.ok) {
      setBusy("");
      return setError(result.error || t("identity.failed"));
    }
    if (result.status) setStatus(result.status);
    closeAction();
    setBusy("");
    setMessage(t("identity.passwordChanged"));
  };

  const exportBackup = async (subject: string) => {
    setBusy(`export:${subject}`);
    clearFeedback();
    const result = await window.identity.exportBackup({ subject });
    setBusy("");
    if (result.canceled) return;
    if (!result.ok) return setError(result.error || t("identity.failed"));
    setMessage(t("identity.backupExported"));
  };

  const importAccount = async () => {
    if (!password) return setError(t("identity.importPasswordRequired"));
    setBusy("import");
    clearFeedback();
    const result = await window.identity.importBackup({ password });
    if (result.canceled) {
      setBusy("");
      return;
    }
    if (!result.ok || !result.status) {
      setBusy("");
      return setError(result.error || t("identity.failed"));
    }
    await disconnectAll();
    publishStatus(result.status);
    setImportingAccount(false);
    setPassword("");
    setBusy("");
    setMessage(t("identityUi.imported", { name: result.status.displayName || "" }));
  };

  const removeAccount = async (subject: string) => {
    if (!password) return;
    setBusy(`delete:${subject}`);
    clearFeedback();
    const wasActive = subject === status?.activeSubject;
    const result = await window.identity.remove({ subject, password });
    if (!result.ok || !result.status) {
      setBusy("");
      return setError(result.error || t("identity.failed"));
    }
    if (wasActive) await disconnectAll();
    publishStatus(result.status, wasActive);
    closeAction();
    setBusy("");
    if (wasActive) onClose();
    else setMessage(t("identityUi.closedAccount"));
  };

  const actionAccount = action
    ? status?.accounts.find((account) => account.subject === action.subject)
    : undefined;

  return (
    <div
      className={embedded ? "identity-settings-embedded" : "identity-settings-overlay"}
      role="presentation"
      onMouseDown={embedded ? undefined : onClose}
    >
      <section
        className={`identity-settings-dialog ${embedded ? "is-embedded" : ""}`}
        role="dialog"
        aria-modal={!embedded}
        aria-labelledby="identity-settings-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="identity-settings-header">
          <div>
            <h2 id="identity-settings-title">{t("identityUi.accountManagement")}</h2>
            <p>{t("identityUi.accountDescription")}</p>
          </div>
          <div className="identity-settings-header-actions">
            <Button
              variant="secondary"
              size="sm"
              icon="file-text"
              disabled={Boolean(busy)}
              onClick={() => {
                setImportingAccount(true);
                setAddingAccount(false);
                closeAction();
              }}
            >
              {t("identityUi.importBackup")}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon="plus"
              disabled={Boolean(busy)}
              onClick={() => {
                setAddingAccount(true);
                setImportingAccount(false);
                closeAction();
              }}
            >
              {t("identityUi.addAccount")}
            </Button>
            {!embedded && (
              <button className="identity-settings-close" onClick={onClose} aria-label={t("about.close")}>
                <Icon name="x" size={18} />
              </button>
            )}
          </div>
        </header>

        <div className="identity-settings-section identity-account-section">
          <div className="identity-account-list">
            {status?.accounts.map((account) => (
              <div className={`identity-account-item ${account.active ? "active" : ""}`} key={account.subject}>
                <div className="identity-avatar">{account.displayName.charAt(0)}</div>
                <div className="identity-account-copy">
                  <div>
                    <strong>{account.displayName}</strong>
                    {account.active && <span>{t("identityUi.current")}</span>}
                  </div>
                  <code title={account.subject}>{account.subject.slice(0, 16)}…</code>
                </div>
                <div className="identity-account-actions">
                  {!account.active && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon="external-link"
                      className="settings-list-action primary"
                      disabled={Boolean(busy)}
                      onClick={() => openAction("switch", account.subject)}
                    >
                      {t("identityUi.switch")}
                    </Button>
                  )}
                  {account.active && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon="camera"
                      className="settings-list-action primary"
                      disabled={Boolean(busy)}
                      onClick={() => setShowBiometrics(true)}
                    >
                      {t("identityUi.faceAndVoiceprint")}
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="shield"
                    className="settings-list-action"
                    disabled={Boolean(busy)}
                    onClick={() => openAction("password", account.subject)}
                  >
                    {t("identityUi.changePassword")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="file-text"
                    className="settings-list-action"
                    disabled={Boolean(busy)}
                    onClick={() => void exportBackup(account.subject)}
                  >
                    {busy === `export:${account.subject}` ? t("identityUi.exporting") : t("identityUi.exportBackup")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="trash"
                    className="settings-list-action danger"
                    disabled={Boolean(busy)}
                    onClick={() => openAction("delete", account.subject)}
                  >
                    {t("identityUi.delete")}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {message && <p className="identity-settings-message">{message}</p>}
        {error && <p className="connect-error">{error}</p>}

        {addingAccount && (
          <div
            className="identity-account-modal-backdrop"
            onMouseDown={() => !busy && setAddingAccount(false)}
          >
            <section
              className="identity-account-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="identity-account-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header>
                <div>
                  <h3 id="identity-account-modal-title">{t("identityUi.addAccount")}</h3>
                  <p>{t("identityUi.createDescription")}</p>
                </div>
                <button
                  type="button"
                  aria-label={t("common.close")}
                  disabled={Boolean(busy)}
                  onClick={() => setAddingAccount(false)}
                >
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>{t("identityUi.accountName")}</label>
                <input
                  autoFocus
                  value={newAccountName}
                  onChange={(event) => setNewAccountName(event.target.value)}
                  placeholder={t("identityUi.exampleName")}
                />
              </div>
              <div className="connect-field">
                <label>{t("identityUi.password")}</label>
                <input
                  type="password"
                  value={newAccountPassword}
                  onChange={(event) => setNewAccountPassword(event.target.value)}
                  placeholder={t("identityUi.atLeastEight")}
                />
              </div>
              <div className="connect-field">
                <label>{t("identityUi.confirmPassword")}</label>
                <input
                  type="password"
                  value={newAccountConfirmation}
                  onChange={(event) => setNewAccountConfirmation(event.target.value)}
                  placeholder={t("identityUi.enterAgain")}
                />
              </div>
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setAddingAccount(false)}>
                  {t("identityUi.cancel")}
                </Button>
                <Button
                  variant="primary"
                  disabled={Boolean(busy) || !newAccountName.trim() || !newAccountPassword}
                  onClick={() => void createAccount()}
                >
                  {busy === "create" ? t("identityUi.creating") : t("identityUi.createAndSwitch")}
                </Button>
              </footer>
            </section>
          </div>
        )}

        {importingAccount && (
          <div
            className="identity-account-modal-backdrop"
            onMouseDown={() => !busy && setImportingAccount(false)}
          >
            <section
              className="identity-account-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="identity-import-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header>
                <div>
                  <h3 id="identity-import-modal-title">{t("identityUi.importTitle")}</h3>
                  <p>{t("identityUi.importDescription")}</p>
                </div>
                <button type="button" aria-label={t("common.close")} disabled={Boolean(busy)} onClick={() => setImportingAccount(false)}>
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>{t("identityUi.backupPassword")}</label>
                <input type="password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} />
              </div>
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setImportingAccount(false)}>{t("identityUi.cancel")}</Button>
                <Button variant="primary" disabled={Boolean(busy) || !password} onClick={() => void importAccount()}>
                  {busy === "import" ? t("identityUi.importing") : t("identityUi.selectAndImport")}
                </Button>
              </footer>
            </section>
          </div>
        )}

        {action && actionAccount && (
          <div
            className="identity-account-modal-backdrop"
            onMouseDown={() => !busy && closeAction()}
          >
            <section
              className={`identity-account-modal ${action.type === "delete" ? "is-danger" : ""}`}
              role="dialog"
              aria-modal="true"
              aria-labelledby="identity-action-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <header>
                <div>
                  <h3 id="identity-action-modal-title">
                    {action.type === "switch"
                      ? t("identityUi.switchTitle", { name: actionAccount.displayName })
                      : action.type === "password"
                        ? t("identityUi.passwordTitle", { name: actionAccount.displayName })
                        : t("identityUi.deleteTitle", { name: actionAccount.displayName })}
                  </h3>
                  <p>
                    {action.type === "switch" && t("identityUi.switchDescription")}
                    {action.type === "password" && t("identityUi.passwordDescription")}
                    {action.type === "delete" && t("identityUi.deleteDescription")}
                  </p>
                </div>
                <button type="button" aria-label={t("common.close")} disabled={Boolean(busy)} onClick={closeAction}>
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>{action.type === "password" ? t("identityUi.currentPassword") : t("identityUi.accountPassword")}</label>
                <input type="password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} />
              </div>
              {action.type === "password" && (
                <>
                  <div className="connect-field">
                    <label>{t("identityUi.newPassword")}</label>
                    <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder={t("identityUi.atLeastEight")} />
                  </div>
                  <div className="connect-field">
                    <label>{t("identityUi.confirmNewPassword")}</label>
                    <input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
                  </div>
                </>
              )}
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={closeAction}>{t("identityUi.cancel")}</Button>
                <Button
                  variant={action.type === "delete" ? "danger" : "primary"}
                  disabled={Boolean(busy) || !password || (action.type === "password" && !newPassword)}
                  onClick={() => {
                    if (action.type === "switch") void switchAccount(action.subject);
                    if (action.type === "password") void changePassword(action.subject);
                    if (action.type === "delete") void removeAccount(action.subject);
                  }}
                >
                  {action.type === "switch" ? t("identityUi.confirmSwitch") : action.type === "password" ? t("identityUi.savePassword") : t("identityUi.confirmDelete")}
                </Button>
              </footer>
            </section>
          </div>
        )}
        {showBiometrics && (
          <PersonBiometricModal
            agents={connectedAgents}
            initialAgentId={activeAgentId}
            onClose={() => setShowBiometrics(false)}
          />
        )}
      </section>
    </div>
  );
}
