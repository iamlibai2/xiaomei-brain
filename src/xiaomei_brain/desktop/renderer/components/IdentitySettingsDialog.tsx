import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { useCoreStore } from "../store";
import { Button } from "./ui";

interface IdentitySettingsDialogProps {
  onClose: () => void;
  embedded?: boolean;
}

export function IdentitySettingsDialog({ onClose, embedded = false }: IdentitySettingsDialogProps) {
  const { t } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const disconnectAgent = useCoreStore((state) => state.disconnectAgent);
  const resetIdentityState = useCoreStore((state) => state.resetIdentityState);
  const [status, setStatus] = useState<IdentityStatus | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [addingAccount, setAddingAccount] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountPassword, setNewAccountPassword] = useState("");
  const [newAccountConfirmation, setNewAccountConfirmation] = useState("");
  const [removingSubject, setRemovingSubject] = useState("");
  const [removePassword, setRemovePassword] = useState("");
  const [importPassword, setImportPassword] = useState("");
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

  const createAccount = async () => {
    if (!newAccountName.trim()) {
      setError("请输入账户名称。");
      return;
    }
    if (newAccountPassword !== newAccountConfirmation) {
      setError(t("identity.passwordMismatch"));
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    const result = await window.identity.create({
      displayName: newAccountName,
      password: newAccountPassword,
    });
    if (!result.ok || !result.status) {
      setBusy(false);
      setError(result.error || t("identity.failed"));
      return;
    }
    await disconnectAll();
    setBusy(false);
    publishStatus(result.status);
    setAddingAccount(false);
    setNewAccountName("");
    setNewAccountPassword("");
    setNewAccountConfirmation("");
    setMessage(`账户“${result.status.displayName || newAccountName}”已创建并切换。`);
  };

  const selectAccount = async (subject: string) => {
    setBusy(true);
    setError("");
    const result = await window.identity.select({ subject });
    if (!result.ok || !result.status) {
      setBusy(false);
      setError(result.error || t("identity.failed"));
      return;
    }
    await disconnectAll();
    setBusy(false);
    publishStatus(result.status, true);
    onClose();
  };

  const removeAccount = async () => {
    if (!removingSubject || !removePassword) return;
    const account = status?.accounts.find((item) => item.subject === removingSubject);
    const confirmed = window.confirm(
      `只从这台电脑删除“${account?.displayName || "该账户"}”的身份密钥？Agent 中的人物、会话和关系不会被删除。`,
    );
    if (!confirmed) return;
    setBusy(true);
    setError("");
    const wasActive = removingSubject === status?.activeSubject;
    const result = await window.identity.remove({
      subject: removingSubject,
      password: removePassword,
    });
    if (!result.ok || !result.status) {
      setBusy(false);
      setError(result.error || t("identity.failed"));
      return;
    }
    if (wasActive) await disconnectAll();
    setBusy(false);
    setRemovingSubject("");
    setRemovePassword("");
    publishStatus(result.status, wasActive);
    if (wasActive) onClose();
    else setMessage("本机账户已删除，Agent 中的数据没有改变。");
  };

  const importAccount = async () => {
    if (!importPassword) {
      setError(t("identity.importPasswordRequired"));
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    const result = await window.identity.importBackup({ password: importPassword });
    if (result.canceled) {
      setBusy(false);
      return;
    }
    if (!result.ok || !result.status) {
      setBusy(false);
      setError(result.error || t("identity.failed"));
      return;
    }
    await disconnectAll();
    setBusy(false);
    setImportPassword("");
    publishStatus(result.status);
    setMessage(`账户“${result.status.displayName || ""}”已导入并切换。`);
  };

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
    if (result.status) setStatus(result.status);
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
    await disconnectAll();
    const nextStatus = await window.identity.lock();
    publishStatus(nextStatus, true);
    onClose();
  };

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
            <h2 id="identity-settings-title">账户管理</h2>
            <p>管理这台电脑用于向各个 Agent 证明身份的本地账户。</p>
          </div>
          <button onClick={onClose} aria-label={t("about.close")}>×</button>
        </header>

        <div className="identity-settings-section identity-account-section">
          <div className="identity-section-heading">
            <div>
              <h3>本机账户</h3>
              <p>不同账户拥有不同密钥；切换账户后，各 Agent 会识别为不同的人。</p>
            </div>
            <Button variant="secondary" onClick={() => setAddingAccount((current) => !current)} disabled={busy}>
              {addingAccount ? "取消" : "添加账户"}
            </Button>
          </div>

          <div className="identity-account-list">
            {status?.accounts.map((account) => (
              <div className={`identity-account-item ${account.active ? "active" : ""}`} key={account.subject}>
                <div className="identity-avatar">{account.displayName.charAt(0)}</div>
                <div className="identity-account-copy">
                  <div>
                    <strong>{account.displayName}</strong>
                    {account.active && <span>当前账户</span>}
                  </div>
                  <code title={account.subject}>{account.subject.slice(0, 16)}…</code>
                </div>
                <div className="identity-account-actions">
                  {!account.active && (
                    <button type="button" disabled={busy} onClick={() => void selectAccount(account.subject)}>
                      切换
                    </button>
                  )}
                  <button
                    type="button"
                    className="danger"
                    disabled={busy}
                    onClick={() => {
                      setRemovingSubject(account.subject);
                      setRemovePassword("");
                    }}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>

          {addingAccount && (
            <div className="identity-inline-form">
              <div className="connect-field">
                <label>账户名称</label>
                <input value={newAccountName} onChange={(event) => setNewAccountName(event.target.value)} />
              </div>
              <div className="identity-password-row">
                <div className="connect-field">
                  <label>本机密码</label>
                  <input type="password" value={newAccountPassword} onChange={(event) => setNewAccountPassword(event.target.value)} />
                </div>
                <div className="connect-field">
                  <label>确认密码</label>
                  <input type="password" value={newAccountConfirmation} onChange={(event) => setNewAccountConfirmation(event.target.value)} />
                </div>
              </div>
              <Button variant="primary" disabled={busy || !newAccountName || !newAccountPassword} onClick={() => void createAccount()}>
                创建并切换
              </Button>
            </div>
          )}

          {removingSubject && (
            <div className="identity-inline-form danger">
              <p>请输入这个账户的本机密码以确认删除。这里只删除本机密钥，不删除任何 Agent 数据。</p>
              <div className="identity-inline-action">
                <input
                  type="password"
                  autoFocus
                  value={removePassword}
                  onChange={(event) => setRemovePassword(event.target.value)}
                  placeholder="账户密码"
                />
                <Button variant="secondary" onClick={() => setRemovingSubject("")}>取消</Button>
                <Button variant="primary" disabled={busy || !removePassword} onClick={() => void removeAccount()}>确认删除</Button>
              </div>
            </div>
          )}
        </div>

        <div className="identity-settings-section">
          <h3>当前账户的备份与密码</h3>
          <p>备份文件仍由账户密码加密，可以在其他 Desktop 中导入。</p>
          <div className="identity-backup-actions">
            <Button variant="secondary" onClick={() => void exportBackup()} disabled={busy}>
              {t("identity.exportBackup")}
            </Button>
            <input
              type="password"
              value={importPassword}
              onChange={(event) => setImportPassword(event.target.value)}
              placeholder="备份文件密码"
            />
            <Button variant="secondary" onClick={() => void importAccount()} disabled={busy || !importPassword}>
              导入其他账户
            </Button>
          </div>
        </div>

        <div className="identity-settings-section">
          <h3>{t("identity.changePasswordTitle")}</h3>
          <div className="connect-field">
            <label>{t("identity.currentPassword")}</label>
            <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
          </div>
          <div className="identity-password-row">
            <div className="connect-field">
              <label>{t("identity.newPassword")}</label>
              <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
            </div>
            <div className="connect-field">
              <label>{t("identity.confirmPassword")}</label>
              <input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
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
