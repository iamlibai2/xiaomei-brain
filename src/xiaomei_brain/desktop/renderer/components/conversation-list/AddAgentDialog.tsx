import { useEffect, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import { Button, Icon } from "../ui";

export function AddAgentDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const createLocalAgent = useCoreStore((state) => state.createLocalAgent);
  const addAgent = useCoreStore((state) => state.addAgent);
  const [mode, setMode] = useState<"local" | "remote">("local");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("19766");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, submitting]);

  async function submitLocal(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !role.trim() || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await createLocalAgent(name, role);
      if (!result.ok) {
        setError(result.message);
        return;
      }
      onClose();
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  function submitRemote(event: FormEvent) {
    event.preventDefault();
    const numericPort = Number(port);
    if (!host.trim() || !Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
      setError(t("agentDialog.invalidRemoteAddress"));
      return;
    }
    addAgent(host.trim(), numericPort, token);
    onClose();
  }

  return createPortal(
    <div className="agent-dialog-overlay" role="presentation" onMouseDown={() => { if (!submitting) onClose(); }}>
      <section
        className="agent-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="agent-dialog-header">
          <div>
            <h2 id="agent-dialog-title">
              {mode === "local" ? t("agentDialog.createTitle") : t("agentDialog.remoteTitle")}
            </h2>
            <p>{mode === "local" ? t("agentDialog.createSubtitle") : t("agentDialog.remoteSubtitle")}</p>
          </div>
          <button className="agent-dialog-close" onClick={onClose} disabled={submitting} aria-label={t("agentDialog.close")}>
            <Icon name="x" size={18} />
          </button>
        </header>

        {mode === "local" ? (
          <form className="agent-dialog-form" onSubmit={(event) => { void submitLocal(event); }}>
            <label>
              <span>{t("agentDialog.nameLabel")}</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("agentDialog.namePlaceholder")}
                maxLength={80}
                autoFocus
              />
            </label>
            <label>
              <span>{t("agentDialog.roleLabel")}</span>
              <textarea
                value={role}
                onChange={(event) => setRole(event.target.value)}
                placeholder={t("agentDialog.rolePlaceholder")}
                maxLength={500}
                rows={4}
              />
            </label>
            <button className="agent-dialog-secondary-entry" type="button" onClick={() => { setMode("remote"); setError(""); }}>
              {t("agentDialog.connectRemote")} <span>›</span>
            </button>
            {error && <div className="agent-dialog-error">{error}</div>}
            <footer className="agent-dialog-actions">
              <Button type="button" variant="ghost" size="md" onClick={onClose} disabled={submitting}>
                {t("agentDialog.cancel")}
              </Button>
              <Button type="submit" variant="primary" size="md" disabled={!name.trim() || !role.trim() || submitting}>
                {submitting ? t("agentDialog.creating") : t("agentDialog.create")}
              </Button>
            </footer>
          </form>
        ) : (
          <form className="agent-dialog-form" onSubmit={submitRemote}>
            <button className="agent-dialog-back" type="button" onClick={() => { setMode("local"); setError(""); }}>
              ‹ {t("agentDialog.backToCreate")}
            </button>
            <label>
              <span>{t("agentDialog.hostLabel")}</span>
              <input value={host} onChange={(event) => setHost(event.target.value)} autoFocus />
            </label>
            <label>
              <span>{t("agentDialog.portLabel")}</span>
              <input value={port} onChange={(event) => setPort(event.target.value)} inputMode="numeric" />
            </label>
            <label>
              <span>{t("agentDialog.tokenLabel")}</span>
              <input value={token} onChange={(event) => setToken(event.target.value)} type="password" />
            </label>
            {error && <div className="agent-dialog-error">{error}</div>}
            <footer className="agent-dialog-actions">
              <Button type="button" variant="ghost" size="md" onClick={onClose}>
                {t("agentDialog.cancel")}
              </Button>
              <Button type="submit" variant="primary" size="md">
                {t("agentDialog.connect")}
              </Button>
            </footer>
          </form>
        )}
      </section>
    </div>,
    document.body,
  );
}
