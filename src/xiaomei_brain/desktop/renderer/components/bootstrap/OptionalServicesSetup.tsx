import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon, SelectMenu } from "../ui";
import type { IconName } from "../ui";
import type { LocalAIServiceStatus, LocalAISystemStatus, SetupProgress } from "../../types";
import { BootstrapWizard } from "./BootstrapWizard";
import { PREVIEW_LOCAL_AI_SERVICES, PREVIEW_LOCAL_AI_SYSTEM } from "./preview-data";

const SERVICES: Array<{ id: LocalAIServiceStatus["id"] | "ffmpeg"; icon: IconName; recommended: boolean }> = [
  { id: "ffmpeg", icon: "play", recommended: true },
  { id: "stt", icon: "microphone", recommended: true },
  { id: "tts_voxcpm", icon: "volume", recommended: false },
  { id: "face", icon: "camera", recommended: false },
  { id: "voiceprint", icon: "music", recommended: false },
];

export function OptionalServicesSetup({ initial, preview = false, onComplete }: {
  initial: string[];
  preview?: boolean;
  onComplete: (services: string[]) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string[]>(initial.length ? initial : ["ffmpeg", "stt"]);
  const [services, setServices] = useState<LocalAIServiceStatus[]>([]);
  const [system, setSystem] = useState<LocalAISystemStatus | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<SetupProgress | null>(null);

  useEffect(() => window.setup.onProgress(setProgress), []);
  useEffect(() => {
    if (preview) {
      setServices(PREVIEW_LOCAL_AI_SERVICES.filter((service) => service.id !== "embedding"));
      setSystem(PREVIEW_LOCAL_AI_SYSTEM);
      setLoading(false);
      return;
    }
    void window.localAI.list().then((result) => {
      if (result.ok) {
        setServices(result.services);
        setSystem(result.system);
      } else {
        setError(result.error || t("localAiUi.readStatusError"));
      }
      setLoading(false);
    });
  }, [preview, t]);

  const byId = useMemo(() => new Map(services.map((service) => [service.id, service])), [services]);
  const updateService = (next: LocalAIServiceStatus) => setServices((current) => current.map((item) => item.id === next.id ? next : item));

  const toggle = (id: string) => {
    if (busy) return;
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const selectModel = async (service: LocalAIServiceStatus, modelId: string) => {
    if (preview) {
      const selected = service.models.find((model) => model.id === modelId);
      if (selected) updateService({
        ...service,
        selected_model_id: selected.id,
        model: selected.name,
        expected_size: selected.expected_size,
        supported_devices: selected.supported_devices as LocalAIServiceStatus["supported_devices"],
      });
      return;
    }
    setBusy(`${service.id}:model`);
    setError("");
    const result = await window.localAI.selectModel({ serviceId: service.id, modelId });
    if (result.ok && result.service) updateService(result.service);
    else setError(result.error || t("localAiUi.modelSwitchFailed"));
    setBusy("");
  };

  const selectDevice = async (service: LocalAIServiceStatus, device: string) => {
    if (preview) {
      updateService({ ...service, selected_device: device as LocalAIServiceStatus["selected_device"] });
      return;
    }
    setBusy(`${service.id}:device`);
    setError("");
    const result = await window.localAI.selectDevice({
      serviceId: service.id,
      device: device as LocalAIServiceStatus["selected_device"],
    });
    if (result.ok && result.service) updateService(result.service);
    else setError(result.error || t("localAiUi.deviceSwitchFailed"));
    setBusy("");
  };

  const installing = busy === "install";
  const finish = (servicesToInstall: string[]) => {
    setBusy("install");
    setError("");
    void onComplete(servicesToInstall).catch((reason) => {
      setError(reason instanceof Error ? reason.message : String(reason));
      setBusy("");
    });
  };
  return (
    <BootstrapWizard
      mode="custom"
      current="optional_services"
      title={t("bootstrap.optionalTitle")}
      description={t("bootstrap.optionalDescription")}
      actions={(
        <>
          {error && (
            <Button variant="secondary" size="lg" disabled={Boolean(busy)} onClick={() => finish([])}>
              {t("bootstrap.optionalContinueWithout")}
            </Button>
          )}
          <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={Boolean(busy) || loading} onClick={() => finish(selected)}>
            {installing ? t("bootstrap.optionalInstalling") : selected.length ? t("bootstrap.optionalAction") : t("bootstrap.optionalSkip")}
          </Button>
        </>
      )}
    >
      <div className="optional-services-list">
        {SERVICES.map((item) => {
          const service = item.id === "ffmpeg" ? undefined : byId.get(item.id);
          const checked = selected.includes(item.id);
          const serviceBusy = busy.startsWith(`${item.id}:`);
          return (
            <article key={item.id} className={`optional-service ${checked ? "selected" : ""}`}>
              <button type="button" className="optional-service-main" disabled={Boolean(busy)} onClick={() => toggle(item.id)}>
                <span className="optional-service-icon"><Icon name={item.icon} size={18} /></span>
                <span className="optional-service-copy">
                  <strong>{t(`bootstrap.optional.${item.id}.name`)}</strong>
                  <small>{t(`bootstrap.optional.${item.id}.description`)}</small>
                </span>
                {item.recommended && <em>{t("bootstrap.recommended")}</em>}
                <span className="optional-service-check" aria-hidden="true">{checked && <Icon name="check" size={13} />}</span>
              </button>
              {checked && service && (
                <div className="optional-service-config">
                  {service.models.length > 0 && (
                    <label>
                      <span>{t("localAiUi.model")}</span>
                      <SelectMenu
                        value={service.selected_model_id}
                        placeholder={t("localAiUi.selectModel")}
                        disabled={Boolean(busy) || service.selection_locked || service.models.length === 1}
                        options={service.models.map((model) => ({
                          value: model.id,
                          label: model.name,
                          description: `${model.expected_size}${model.model_present ? ` · ${t("localAiUi.downloaded")}` : ""}`,
                        }))}
                        onChange={(value) => void selectModel(service, value)}
                      />
                    </label>
                  )}
                  {service.supported_devices.length > 0 && (
                    <label>
                      <span>{t("localAiUi.device")}</span>
                      <SelectMenu
                        value={service.selected_device}
                        placeholder={t("localAiUi.selectDevice")}
                        disabled={Boolean(busy) || service.supported_devices.length === 1}
                        options={service.supported_devices
                          .filter((device) => device !== "cuda" || Boolean(system?.gpus.length))
                          .map((device) => ({
                            value: device,
                            label: device === "auto" ? t("localAiUi.auto") : device.toUpperCase(),
                            description: device === "cuda" ? system?.gpus[0]?.name : "",
                          }))}
                        onChange={(value) => void selectDevice(service, value)}
                      />
                    </label>
                  )}
                  {serviceBusy && <span className="bootstrap-mini-status">{t("bootstrap.preparing")}</span>}
                  {service.selection_locked && <p>{t("localAiUi.locked", { reason: service.selection_lock_reason })}</p>}
                </div>
              )}
            </article>
          );
        })}
      </div>
      {loading && <div className="bootstrap-inline-loading compact"><span className="bootstrap-spinner" /><p>{t("localAiUi.checking")}</p></div>}
      {installing && (
        <div className="setup-progress">
          <div><span className={progress ? "" : "is-indeterminate"} style={progress ? { width: `${progress.percent}%` } : undefined} /></div>
          <p>{progress?.state === "retrying"
            ? t("firstRunSetup.autoRetry", { attempt: progress.attempt, max: progress.maxAttempts })
            : progress?.message || t("bootstrap.optionalInstalling")}</p>
        </div>
      )}
      {error && <div className="setup-error"><span>{error}</span><button type="button" className="setup-log-link" onClick={() => void window.desktop.openLogDirectory()}>{t("bootstrap.openLogs")}</button></div>}
    </BootstrapWizard>
  );
}
