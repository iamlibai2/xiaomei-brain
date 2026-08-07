import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CapabilityRuntimeStatus, CapabilitySetupJob } from "../../types";
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

  const start = useCallback(async (action: "install" | "configure" | "authorize" | "disconnect") => {
    if (action === "disconnect" && !window.confirm(t("feishuCapabilityUi.disconnectConfirm"))) return;
    setBusy(true);
    setError("");
    try {
      const response = await window.gateway.startCapabilitySetup({ agentId, capabilityId, action });
      if (response.error) throw new Error(response.error.message);
      setJob((response.result?.job || null) as CapabilitySetupJob | null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }, [agentId, capabilityId, t]);

  if (!runtime && !error) {
    return <div className="capability-runtime-panel is-loading">{t("feishuCapabilityUi.checking")}</div>;
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
          <strong>{runtime?.message || t("feishuCapabilityUi.unavailable")}</strong>
          {identity && <span>{t("feishuCapabilityUi.connectedAs", { identity })}</span>}
          {!!details.skill_count && <span>{t("feishuCapabilityUi.skillsReady", { count: details.skill_count })}</span>}
        </div>
      </div>

      <div className="capability-runtime-actions">
        {(runtime?.actions || []).map((action) => (
          <Button
            key={action}
            variant={action === "disconnect" ? "ghost" : "secondary"}
            size="sm"
            disabled={busy || running}
            onClick={() => void start(action)}
          >
            {t(`feishuCapabilityUi.action_${action}`)}
          </Button>
        ))}
        {running && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void window.gateway.cancelCapabilitySetup({ agentId, capabilityId, jobId: job.id })}
          >
            {t("feishuCapabilityUi.cancel")}
          </Button>
        )}
      </div>

      {job && (
        <div className={`capability-runtime-job ${job.state}`}>
          <strong>{t(`feishuCapabilityUi.job_${job.state}`)}</strong>
          {job.urls.map((url) => (
            <button type="button" key={url} onClick={() => void window.desktop.openExternal(url)}>
              {t("feishuCapabilityUi.openAuthorization")}
            </button>
          ))}
          {job.error && <span>{job.error}</span>}
          {job.output && <pre>{job.output}</pre>}
        </div>
      )}
      {error && <div className="settings-error">{error}</div>}
    </div>
  );
}
