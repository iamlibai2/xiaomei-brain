import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  CapabilityRuntimeStatus,
  CapabilitySetupAction,
  CapabilitySetupForm,
  CapabilitySetupJob,
} from "../../types";
import { Button, Icon } from "../ui";

interface Props {
  agentId: string;
  capabilityId: string;
  onChanged: () => void;
}

export function CapabilityRuntimeSetup({ agentId, capabilityId, onChanged }: Props) {
  const { t } = useTranslation();
  const [runtime, setRuntime] = useState<CapabilityRuntimeStatus | null>(null);
  const [job, setJob] = useState<CapabilitySetupJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activeForm, setActiveForm] = useState<CapabilitySetupForm | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});

  const refresh = useCallback(async (jobId = "") => {
    const response = await window.gateway.getCapabilitySetupStatus({
      agentId,
      capabilityId,
      jobId,
    });
    if (response.error) throw new Error(response.error.message);
    setRuntime((response.result?.runtime || null) as CapabilityRuntimeStatus | null);
    setJob((response.result?.job || null) as CapabilitySetupJob | null);
    return (response.result?.job || null) as CapabilitySetupJob | null;
  }, [agentId, capabilityId]);

  useEffect(() => {
    setRuntime(null);
    setJob(null);
    setError("");
    void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [refresh]);

  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(() => {
      void refresh(job.id).then((next) => {
        if (next && next.state !== "running") onChanged();
      }).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.state, onChanged, refresh]);

  const start = useCallback(async (
    action: CapabilitySetupAction,
    input: Record<string, string> = {},
  ) => {
    if (action === "disconnect" && !window.confirm(t("capabilityRuntimeUi.disconnectConfirm"))) return false;
    setBusy(true);
    setError("");
    try {
      const response = await window.gateway.startCapabilitySetup({ agentId, capabilityId, action, input });
      if (response.error) throw new Error(response.error.message);
      setJob((response.result?.job || null) as CapabilitySetupJob | null);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return false;
    } finally {
      setBusy(false);
    }
  }, [agentId, capabilityId, t]);

  const requestAction = useCallback((action: CapabilitySetupAction) => {
    const form = runtime?.details.setup_forms?.find((candidate) => candidate.action === action);
    if (!form) {
      void start(action);
      return;
    }
    setConfigValues(Object.fromEntries(
      form.fields.map((field) => [field.key, String(field.value ?? "")]),
    ));
    setActiveForm(form);
  }, [runtime, start]);

  const openAuthorization = useCallback(async (url: string) => {
    if (!job || job.callback_mode !== "desktop") {
      await window.desktop.openExternal(url);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await window.gateway.runCapabilityOAuth({
        agentId,
        capabilityId,
        jobId: job.id,
        authorizationUrl: url,
      });
      if (response.error) throw new Error(response.error.message);
      setJob((response.result?.job || job) as CapabilitySetupJob);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }, [agentId, capabilityId, job]);

  if (!runtime && !error) {
    return <div className="capability-runtime-panel is-loading">{t("capabilityRuntimeUi.checking")}</div>;
  }

  const details = runtime?.details || {};
  const identity = details.name || details.email || details.tenant_name || "";
  const running = job?.state === "running";
  return (
    <div className="capability-runtime-panel">
      <div className="capability-runtime-summary">
        <span className={`capability-runtime-mark ${runtime?.available ? "ready" : "waiting"}`}>
          <Icon name={runtime?.available ? "check" : "settings"} size={15} />
        </span>
        <div>
          <strong>{runtime?.message || t("capabilityRuntimeUi.unavailable")}</strong>
          {identity && <span>{t("capabilityRuntimeUi.connectedAs", { identity })}</span>}
          {!!details.skill_count && <span>{t("capabilityRuntimeUi.skillsReady", { count: details.skill_count })}</span>}
        </div>
      </div>

      <div className="capability-runtime-actions">
        {(runtime?.actions || []).map((action) => (
          <Button
            key={action}
            variant={action === "disconnect" ? "ghost" : "secondary"}
            size="sm"
            disabled={busy || running}
            onClick={() => requestAction(action)}
          >
            {details.setup_forms?.find((form) => form.action === action)?.action_label
              || t(`capabilityRuntimeUi.action_${action}`)}
          </Button>
        ))}
        {running && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void window.gateway.cancelCapabilitySetup({ agentId, capabilityId, jobId: job.id })}
          >
            {t("capabilityRuntimeUi.cancel")}
          </Button>
        )}
      </div>

      {job && (
        <div className={`capability-runtime-job ${job.state}`}>
          <strong>{t(`capabilityRuntimeUi.job_${job.state}`)}</strong>
          {job.urls.map((url) => (
            <button type="button" key={url} disabled={busy} onClick={() => void openAuthorization(url)}>
              {t("capabilityRuntimeUi.openAuthorization")}
            </button>
          ))}
          {job.error && <span>{job.error}</span>}
          {job.output && <pre>{job.output}</pre>}
        </div>
      )}
      {error && <div className="settings-error">{error}</div>}
      {activeForm && (
        <div className="model-editor-backdrop" onMouseDown={() => !busy && setActiveForm(null)}>
          <section
            className="model-editor-dialog"
            role="dialog"
            aria-modal="true"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="model-editor-header">
              <div>
                <h2>{activeForm.title}</h2>
                <p>{activeForm.description || t(`capabilityRuntimeUi.scope_${activeForm.scope}`)}</p>
              </div>
              <button type="button" aria-label={t("capabilityRuntimeUi.close")} onClick={() => setActiveForm(null)}>
                <Icon name="x" size={18} />
              </button>
            </header>
            <div className="model-editor-body capability-runtime-form">
              <div className="capability-runtime-scope">
                {t(`capabilityRuntimeUi.scope_${activeForm.scope}`)}
              </div>
              {activeForm.fields.map((field) => (
                <label className="settings-field" key={field.key}>
                  <span>{field.label}</span>
                  {field.type === "select" ? (
                    <select
                      value={configValues[field.key] || ""}
                      required={field.required}
                      onChange={(event) => setConfigValues((current) => ({
                        ...current,
                        [field.key]: event.target.value,
                      }))}
                    >
                      {(field.options || []).map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  ) : field.type === "boolean" ? (
                    <input
                      type="checkbox"
                      checked={configValues[field.key] === "true"}
                      onChange={(event) => setConfigValues((current) => ({
                        ...current,
                        [field.key]: String(event.target.checked),
                      }))}
                    />
                  ) : (
                    <input
                      type={field.type === "secret" ? "password" : field.type === "number" ? "number" : "text"}
                      value={configValues[field.key] || ""}
                      placeholder={field.placeholder || (field.type === "secret" && field.configured
                        ? t("capabilityRuntimeUi.keepExistingSecret")
                        : "")}
                      required={field.required}
                      onChange={(event) => setConfigValues((current) => ({
                        ...current,
                        [field.key]: event.target.value,
                      }))}
                    />
                  )}
                  {field.help && <small>{field.help}</small>}
                </label>
              ))}
              {details.documentation_url && (
                <button
                  type="button"
                  className="capability-runtime-doc-link"
                  onClick={() => void window.desktop.openExternal(details.documentation_url || "")}
                >
                  <span className="capability-runtime-doc-icon">
                    <Icon name="file-text" size={16} />
                  </span>
                  <strong>{t("capabilityRuntimeUi.openDocumentation")}</strong>
                  <Icon name="external-link" size={15} />
                </button>
              )}
            </div>
            <footer className="model-editor-footer">
              <Button variant="secondary" disabled={busy} onClick={() => setActiveForm(null)}>
                {t("capabilityRuntimeUi.cancel")}
              </Button>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => void start(activeForm.action, configValues).then((saved) => {
                  if (saved) setActiveForm(null);
                })}
              >
                {activeForm.submit_label || t("capabilityRuntimeUi.save")}
              </Button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
