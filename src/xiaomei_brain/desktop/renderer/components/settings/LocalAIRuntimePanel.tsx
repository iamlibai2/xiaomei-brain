import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DesktopSettings, LocalAIServiceStatus, LocalAISystemStatus } from "../../types";
import { Button, Icon, SelectMenu } from "../ui";

const STATE_KEYS: Record<LocalAIServiceStatus["state"], string> = {
  online: "statusOnline", starting: "statusStarting", downloading: "statusDownloading",
  not_installed: "statusNotInstalled", download_error: "statusDownloadError", stopped: "statusStopped",
  unavailable: "statusUnavailable", available: "statusAvailable", error: "statusError",
};
const SERVICE_NAME_KEYS: Record<LocalAIServiceStatus["id"], string> = {
  embedding: "embeddingName", stt: "sttName", tts_voxcpm: "ttsName", voiceprint: "voiceprintName", face: "faceName",
};
const SERVICE_DESCRIPTION_KEYS: Record<LocalAIServiceStatus["id"], string> = {
  embedding: "embeddingDescription", stt: "sttDescription", tts_voxcpm: "ttsDescription", voiceprint: "voiceprintDescription", face: "faceDescription",
};
const ACTIVE_TASK_POLL_INTERVAL_MS = 3_000;

export function LocalAIRuntimePanel({ language }: { language: DesktopSettings["language"] }) {
  const { t } = useTranslation();
  const [services, setServices] = useState<LocalAIServiceStatus[]>([]);
  const [system, setSystem] = useState<LocalAISystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [log, setLog] = useState<{ id: string; content: string } | null>(null);
  const [downloadTarget, setDownloadTarget] = useState<LocalAIServiceStatus | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const result = await window.localAI.list();
    if (result.ok) {
      setServices(result.services);
      setSystem(result.system || null);
      setError("");
    } else {
      setError(result.error || t("localAiUi.readStatusError"));
    }
    if (!quiet) setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      const cached = await window.localAI.cachedList();
      if (cancelled) return;
      const hasCachedSnapshot = cached.ok && cached.services.length > 0;
      if (hasCachedSnapshot) {
        setServices(cached.services);
        setSystem(cached.system || null);
        setLoading(false);
      }
      // Refresh slow facts such as cache sizes and GPU load in the background.
      await load(hasCachedSnapshot);
    };
    void initialize();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const summary = useMemo(() => {
    const online = services.filter((item) => item.state === "online").length;
    const active = services.filter((item) => ["starting", "downloading"].includes(item.state)).length;
    return active
      ? `${active} ${t("localAiUi.preparing")}`
      : t("localAiUi.onlineSummary", { online, total: services.length });
  }, [services, t]);
  const downloadingKey = useMemo(() => services
    .filter((service) => service.state === "downloading")
    .map((service) => `${service.id}:${service.selected_model_id}`)
    .join("|"), [services]);
  const startingKey = useMemo(() => services
    .filter((service) => service.state === "starting")
    .map((service) => service.id)
    .join("|"), [services]);

  useEffect(() => {
    if (!downloadingKey) return undefined;
    const targets = downloadingKey.split("|").map((value) => {
      const [serviceId, modelId] = value.split(":", 2);
      return { serviceId, modelId };
    });
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const results = await Promise.all(targets.map((target) => window.localAI.downloadProgress(target)));
      if (cancelled) return;
      let terminal = false;
      setServices((current) => current.map((service) => {
        const result = results.find((item) => item.progress?.serviceId === service.id);
        const progress = result?.progress;
        if (!result?.ok || !progress) return service;
        terminal ||= progress.completed || progress.failed;
        return {
          ...service,
          download_progress: progress.progress,
          downloaded_bytes: Math.round(service.expected_size_bytes * progress.progress / 100),
          model_present: progress.completed || service.model_present,
          state: progress.completed ? "stopped" : progress.failed ? "download_error" : "downloading",
          error: progress.error,
        };
      }));
      if (terminal) {
        await load(true);
      } else if (!cancelled) {
        timer = window.setTimeout(() => void poll(), ACTIVE_TASK_POLL_INTERVAL_MS);
      }
    };
    timer = window.setTimeout(() => void poll(), ACTIVE_TASK_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [downloadingKey, load]);

  useEffect(() => {
    if (!startingKey) return undefined;
    const serviceIds = startingKey.split("|");
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const results = await Promise.all(serviceIds.map((serviceId) => (
        window.localAI.startupState({ serviceId })
      )));
      if (cancelled) return;
      const terminal = results.some((result) => (
        result.ok && (result.state?.online || result.state?.failed)
      ));
      if (terminal) {
        await load(true);
      } else if (!cancelled) {
        timer = window.setTimeout(() => void poll(), ACTIVE_TASK_POLL_INTERVAL_MS);
      }
    };
    timer = window.setTimeout(() => void poll(), ACTIVE_TASK_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [startingKey, load]);

  async function control(
    service: LocalAIServiceStatus,
    action: "start" | "stop" | "restart" | "download" | "cancel-download",
  ) {
    setBusy(`${service.id}:${action}`);
    setError("");
    const result = await window.localAI.control({
      serviceId: service.id,
      action,
    });
    if (!result.ok) setError(result.error || `${service.name}${t("localAiUi.operationFailed")}`);
    await load(true);
    setBusy("");
  }

  async function toggleLog(service: LocalAIServiceStatus) {
    if (log?.id === service.id) {
      setLog(null);
      return;
    }
    const result = await window.localAI.readLog({ serviceId: service.id });
    if (!result.ok) {
      setError(result.error || t("localAiUi.readLogError"));
      return;
    }
    setLog({ id: service.id, content: result.content || t("localAiUi.emptyLog") });
  }

  async function selectModel(service: LocalAIServiceStatus, modelId: string) {
    if (modelId === service.selected_model_id) return;
    const selected = service.models.find((model) => model.id === modelId);
    setServices((current) => current.map((item) => (
      item.id === service.id
        ? {
          ...item,
          selected_model_id: modelId,
          model: selected?.name || item.model,
          expected_size: selected?.expected_size || item.expected_size,
          expected_size_bytes: selected?.expected_size_bytes || item.expected_size_bytes,
          downloaded_bytes: selected?.downloaded_bytes || 0,
          model_present: selected?.model_present || false,
          model_path: "",
          download_progress: selected?.model_present ? 100 : 0,
          supported_devices: (selected?.supported_devices || item.supported_devices) as LocalAIServiceStatus["supported_devices"],
          state: selected?.model_present ? "stopped" : "not_installed",
          error: "",
        }
        : item
    )));
    setBusy(`${service.id}:select`);
    setError("");
    const result = await window.localAI.selectModel({ serviceId: service.id, modelId });
    if (result.ok && result.service) {
      await load(true);
    } else {
      setServices((current) => current.map((item) => (
        item.id === service.id ? service : item
      )));
      setError(result.error || `${service.name}${t("localAiUi.modelSwitchFailed")}`);
    }
    setBusy("");
  }

  async function selectDevice(
    service: LocalAIServiceStatus,
    device: "auto" | "cpu" | "cuda",
  ) {
    if (device === service.selected_device) return;
    setServices((current) => current.map((item) => (
      item.id === service.id ? { ...item, selected_device: device } : item
    )));
    setBusy(`${service.id}:device`);
    setError("");
    const result = await window.localAI.selectDevice({ serviceId: service.id, device });
    if (result.ok && result.service) {
      await load(true);
    } else {
      setServices((current) => current.map((item) => (
        item.id === service.id ? service : item
      )));
      setError(result.error || `${service.name}${t("localAiUi.deviceSwitchFailed")}`);
    }
    setBusy("");
  }

  return (
    <div className="desktop-settings-panel local-ai-runtime-panel">
      <header className="desktop-settings-intro">
        <h2>{t("localAiUi.title")}</h2>
        <p>{t("localAiUi.description")}</p>
      </header>

      <section className="local-ai-runtime-section">
        <div className="settings-card-heading">
        <div>
          <h3>{t("localAiUi.sharedInference")}</h3>
        </div>
        <span className="desktop-setting-status">{loading ? t("localAiUi.checking") : summary}</span>
      </div>

      {system && (
        <div className="local-ai-system-load" aria-label={t("localAiUi.systemLoad")}>
          <div>
            <span>CPU</span>
            <strong>{Math.round(system.cpu_percent)}%</strong>
            <meter min={0} max={100} value={system.cpu_percent} />
          </div>
          <div>
            <span>{t("localAiUi.memory")}</span>
            <strong>{Math.round(system.memory_percent)}%</strong>
            <small>{formatBytes(system.memory_used_bytes)} / {formatBytes(system.memory_total_bytes)}</small>
            <meter min={0} max={100} value={system.memory_percent} />
          </div>
          {system.gpus.map((gpu, index) => (
            <div key={`${gpu.name}:${index}`} title={gpu.name}>
              <span>GPU{system.gpus.length > 1 ? ` ${index + 1}` : ""}</span>
              <strong>{Math.round(gpu.utilization_percent)}%</strong>
              <small>{formatBytes(gpu.memory_used_bytes)} / {formatBytes(gpu.memory_total_bytes)} {t("localAiUi.gpuMemory")}</small>
              <meter min={0} max={100} value={gpu.utilization_percent} />
            </div>
          ))}
        </div>
      )}

      <div className="local-ai-service-list">
        {services.map((service) => {
          const working = busy.startsWith(`${service.id}:`);
          return (
            <article className="local-ai-service-row" key={service.id}>
              <span className="desktop-setting-icon"><Icon name="cpu" size={17} /></span>
              <div className="local-ai-service-copy">
                <div className="local-ai-service-title">
                <strong>{t(`localAiUi.${SERVICE_NAME_KEYS[service.id]}`)}</strong>
                  {service.required && <span className="local-ai-required">{t("localAiUi.coreDependency")}</span>}
                  <span className={`local-ai-state ${service.state}`}>{t(`localAiUi.${STATE_KEYS[service.state]}`)}</span>
                </div>
                <p>{t(`localAiUi.${SERVICE_DESCRIPTION_KEYS[service.id]}`)}</p>
                <div className="local-ai-runtime-controls">
                  {(service.models.length > 1 || service.supported_devices.length > 1) && (
                    <div className="local-ai-runtime-selectors">
                    {service.models.length > 1 && (
                      <label className="local-ai-model-selector is-model">
                        <span>{t("localAiUi.model")}</span>
                        <SelectMenu
                          value={service.selected_model_id}
                          placeholder={t("localAiUi.selectModel")}
                          disabled={working || service.selection_locked || ["online", "starting", "downloading"].includes(service.state)}
                          options={service.models.map((model) => ({
                            value: model.id,
                            label: model.name,
                            description: `${model.expected_size}${model.model_present ? ` · ${t("localAiUi.downloaded")}` : ""}`,
                          }))}
                          onChange={(value) => void selectModel(service, value)}
                        />
                      </label>
                    )}
                    {service.supported_devices.length > 1 && (
                      <label className="local-ai-model-selector is-device">
                        <span>{t("localAiUi.device")}</span>
                        <SelectMenu
                          value={service.selected_device}
                          placeholder={t("localAiUi.selectDevice")}
                          disabled={working || ["online", "starting", "downloading"].includes(service.state)}
                          options={[
                            ...(service.supported_devices.includes("auto") ? [{ value: "auto", label: t("localAiUi.auto") }] : []),
                            ...(service.supported_devices.includes("cpu") ? [{ value: "cpu", label: "CPU" }] : []),
                            ...(service.supported_devices.includes("cuda") && system?.gpus.length
                              ? [{ value: "cuda", label: "CUDA", description: system.gpus[0]?.name }]
                              : []),
                          ]}
                          onChange={(value) => void selectDevice(
                            service,
                            value as "auto" | "cpu" | "cuda",
                          )}
                        />
                      </label>
                    )}
                    </div>
                  )}
                  <div className="local-ai-service-actions">
                    {service.downloadable && !service.model_present && service.state !== "downloading" && (
                      <Button size="sm" disabled={working} onClick={() => setDownloadTarget(service)}>
                        {service.state === "download_error" ? t("localAiUi.retryDownload") : t("localAiUi.download")}
                      </Button>
                    )}
                    {service.state === "downloading" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "cancel-download")}>{t("localAiUi.cancel")}</Button>
                    )}
                    {service.controllable && service.installed && service.model_present && ["stopped", "error"].includes(service.state) && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "start")}>{t("localAiUi.start")}</Button>
                    )}
                    {service.controllable && service.state === "starting" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "stop")}>{t("localAiUi.stop")}</Button>
                    )}
                    {service.controllable && service.state === "online" && (
                      <Button size="sm" variant="secondary" disabled={working} onClick={() => void control(service, "restart")}>{t("localAiUi.restart")}</Button>
                    )}
                    {service.controllable && service.state === "online" && (
                      <Button size="sm" variant="ghost" disabled={working} onClick={() => void control(service, "stop")}>{t("localAiUi.stop")}</Button>
                    )}
                    {service.controllable && (
                      <Button size="sm" variant="ghost" onClick={() => void toggleLog(service)}>
                        {log?.id === service.id ? t("localAiUi.collapseLog") : t("localAiUi.log")}
                      </Button>
                    )}
                  </div>
                </div>
                <small>
                  {service.model} · {service.expected_size}
                  {service.state === "online" ? ` · ${t("localAiUi.actualRuntime", { device: service.device.toUpperCase() })}` : ` · ${deviceLabel(service.selected_device, t)}`}
                  {service.pid ? ` · PID ${service.pid}` : ""}
                </small>
                {["online", "starting"].includes(service.state) && (
                  <small className="local-ai-resource-usage">
                    {service.memory_bytes > 0 ? t("localAiUi.memoryUsage", { value: formatBytes(service.memory_bytes) }) : t("localAiUi.memoryUnavailable")}
                    {service.gpu_memory_bytes > 0
                      ? ` · ${t("localAiUi.gpuUsage", { value: `${formatBytes(service.gpu_memory_bytes)}${service.gpu_memory_total_bytes > 0 ? ` / ${formatBytes(service.gpu_memory_total_bytes)}` : ""}` })}`
                      : service.device.startsWith("cuda") ? ` · ${t("localAiUi.gpuUnavailable")}` : ""}
                  </small>
                )}
                {service.model_path && <small title={service.model_path}>{t("localAiUi.location")}：{service.model_path}</small>}
                {service.selection_locked && (
                  <small className="local-ai-selection-lock">
                    {t("localAiUi.locked", { reason: service.selection_lock_reason || "compatibility data exists for this model" })}
                  </small>
                )}
                {service.downloadable
                  && !service.model_present
                  && ["downloading", "download_error"].includes(service.state) && (
                  <div className="local-ai-download-progress">
                    <div className="local-ai-download-track" aria-label={t("localAiUi.downloadProgress", { progress: service.download_progress })}>
                      <span style={{ width: `${service.download_progress}%` }} />
                    </div>
                    <small>
                      {formatBytes(service.downloaded_bytes)} / {formatBytes(service.expected_size_bytes)}
                      {service.state === "downloading" ? ` · ${service.download_progress}%` : ""}
                    </small>
                  </div>
                )}
                {service.error && <small className="local-ai-error">{service.error}</small>}
              </div>
            </article>
          );
        })}
        {!loading && services.length === 0 && <div className="settings-empty">{t("localAiUi.empty")}</div>}
      </div>

      <div className="local-ai-runtime-footer">
        <Button variant="secondary" size="sm" onClick={() => void load()}>{t("localAiUi.refresh")}</Button>
        <Button variant="ghost" size="sm" onClick={() => void window.localAI.openDirectory()}>{t("localAiUi.openDirectory")}</Button>
      </div>
      {log && <pre className="desktop-settings-log local-ai-log">{log.content}</pre>}
      {error && <p className="settings-error">{error}</p>}
      </section>
      {downloadTarget && (
        <DownloadConfirmationDialog
          service={downloadTarget}
          onCancel={() => setDownloadTarget(null)}
          onConfirm={() => {
            const target = downloadTarget;
            setDownloadTarget(null);
            void control(target, "download");
          }}
        />
      )}
    </div>
  );
}

function DownloadConfirmationDialog({
  service,
  onCancel,
  onConfirm,
}: {
  service: LocalAIServiceStatus;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const model = service.models.find((item) => item.id === service.selected_model_id);
  const remaining = Math.max(0, service.expected_size_bytes - service.downloaded_bytes);
  return (
    <div className="model-editor-backdrop" onMouseDown={onCancel}>
      <section
        className="model-editor-dialog local-ai-download-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="local-ai-download-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="model-editor-header">
          <div>
            <h2 id="local-ai-download-title">{t("localAiUi.downloadTitle", { model: model?.name || service.model })}</h2>
            <p>{t("localAiUi.downloadDescription")}</p>
          </div>
          <button type="button" aria-label={t("localAiUi.close")} onClick={onCancel}>
            <Icon name="x" size={18} />
          </button>
        </header>
        <div className="model-editor-body local-ai-download-body">
          <dl>
            <div><dt>{t("localAiUi.service")}</dt><dd>{service.name}</dd></div>
            <div><dt>{t("localAiUi.model")}</dt><dd>{model?.name || service.model}</dd></div>
            <div><dt>{t("localAiUi.source")}</dt><dd>{model?.source || t("capabilityUi.undeclared")}</dd></div>
            <div><dt>{t("localAiUi.expectedSize")}</dt><dd>{service.expected_size}</dd></div>
            <div><dt>{t("localAiUi.remaining")}</dt><dd>{formatBytes(remaining)}</dd></div>
          </dl>
          <p>{t("localAiUi.downloadWarning")}</p>
        </div>
        <footer className="model-editor-footer">
          <span>{t("localAiUi.confirmDownload")}</span>
          <div>
            <Button variant="secondary" onClick={onCancel}>{t("localAiUi.cancel")}</Button>
            <Button variant="primary" onClick={onConfirm}>{t("localAiUi.confirm")}</Button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function formatBytes(value: number): string {
  if (!value) return "0 MB";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(value / 1024 ** 2))} MB`;
}

function deviceLabel(device: "auto" | "cpu" | "cuda", t: (key: string) => string): string {
  if (device === "auto") return t("localAiUi.selectDeviceAuto");
  return device.toUpperCase();
}
