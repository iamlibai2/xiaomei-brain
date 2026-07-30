import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IdentityStatus } from "../types";
import { useCoreStore } from "../store";
import { Button, Icon } from "./ui";

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
    if (!newAccountName.trim()) return setError("请输入账户名称。");
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
    setMessage(`账户“${result.status.displayName || newAccountName}”已创建并切换。`);
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
    setMessage(`已切换到“${result.status.displayName || "该账户"}”。Desktop 将使用此账户重新连接 Agent。`);
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
    setMessage(`账户“${result.status.displayName || ""}”已导入并切换。`);
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
    else setMessage("本机账户已删除，Agent 中的数据没有改变。");
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
            <h2 id="identity-settings-title">账户管理</h2>
            <p>管理这台电脑用于向各个 Agent 证明身份的本地账户。</p>
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
              导入备份
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
              添加账户
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
                    {account.active && <span>当前账户</span>}
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
                      切换到此账户
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
                    修改密码
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="file-text"
                    className="settings-list-action"
                    disabled={Boolean(busy)}
                    onClick={() => void exportBackup(account.subject)}
                  >
                    {busy === `export:${account.subject}` ? "导出中…" : "导出备份"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="trash"
                    className="settings-list-action danger"
                    disabled={Boolean(busy)}
                    onClick={() => openAction("delete", account.subject)}
                  >
                    删除
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
                  <h3 id="identity-account-modal-title">添加账户</h3>
                  <p>创建一个独立的本机身份，用于连接和被 Agent 识别。</p>
                </div>
                <button
                  type="button"
                  aria-label="关闭"
                  disabled={Boolean(busy)}
                  onClick={() => setAddingAccount(false)}
                >
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>账户名称</label>
                <input
                  autoFocus
                  value={newAccountName}
                  onChange={(event) => setNewAccountName(event.target.value)}
                  placeholder="例如：李白"
                />
              </div>
              <div className="connect-field">
                <label>本机密码</label>
                <input
                  type="password"
                  value={newAccountPassword}
                  onChange={(event) => setNewAccountPassword(event.target.value)}
                  placeholder="至少 8 个字符"
                />
              </div>
              <div className="connect-field">
                <label>确认密码</label>
                <input
                  type="password"
                  value={newAccountConfirmation}
                  onChange={(event) => setNewAccountConfirmation(event.target.value)}
                  placeholder="再次输入密码"
                />
              </div>
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setAddingAccount(false)}>
                  取消
                </Button>
                <Button
                  variant="primary"
                  disabled={Boolean(busy) || !newAccountName.trim() || !newAccountPassword}
                  onClick={() => void createAccount()}
                >
                  {busy === "create" ? "创建中…" : "创建并切换"}
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
                  <h3 id="identity-import-modal-title">导入账户备份</h3>
                  <p>输入备份密码，然后选择加密身份备份文件。</p>
                </div>
                <button type="button" aria-label="关闭" disabled={Boolean(busy)} onClick={() => setImportingAccount(false)}>
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>备份文件密码</label>
                <input type="password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} />
              </div>
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setImportingAccount(false)}>取消</Button>
                <Button variant="primary" disabled={Boolean(busy) || !password} onClick={() => void importAccount()}>
                  {busy === "import" ? "导入中…" : "选择文件并导入"}
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
                      ? `切换到“${actionAccount.displayName}”`
                      : action.type === "password"
                        ? `修改“${actionAccount.displayName}”的密码`
                        : `删除“${actionAccount.displayName}”`}
                  </h3>
                  <p>
                    {action.type === "switch" && "验证密码后，Desktop 将使用此账户重新连接各个 Agent。"}
                    {action.type === "password" && "新密码只用于保护这台电脑上的身份私钥。"}
                    {action.type === "delete" && "这里只删除本机身份密钥，不会删除任何 Agent 中的数据。"}
                  </p>
                </div>
                <button type="button" aria-label="关闭" disabled={Boolean(busy)} onClick={closeAction}>
                  <Icon name="x" size={18} />
                </button>
              </header>
              <div className="connect-field">
                <label>{action.type === "password" ? "当前密码" : "账户密码"}</label>
                <input type="password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} />
              </div>
              {action.type === "password" && (
                <>
                  <div className="connect-field">
                    <label>新密码</label>
                    <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="至少 8 个字符" />
                  </div>
                  <div className="connect-field">
                    <label>确认新密码</label>
                    <input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
                  </div>
                </>
              )}
              <footer>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={closeAction}>取消</Button>
                <Button
                  variant={action.type === "delete" ? "danger" : "primary"}
                  disabled={Boolean(busy) || !password || (action.type === "password" && !newPassword)}
                  onClick={() => {
                    if (action.type === "switch") void switchAccount(action.subject);
                    if (action.type === "password") void changePassword(action.subject);
                    if (action.type === "delete") void removeAccount(action.subject);
                  }}
                >
                  {action.type === "switch" ? "确认切换" : action.type === "password" ? "保存密码" : "确认删除"}
                </Button>
              </footer>
            </section>
          </div>
        )}
      </section>
    </div>
  );
}
