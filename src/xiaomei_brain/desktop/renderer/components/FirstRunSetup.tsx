import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BootstrapStep, FirstRunSetupStatus, LocalAIServiceStatus, SetupProgress } from "../types";
import { Button, SelectMenu } from "./ui";
import { BootstrapWizard } from "./bootstrap/BootstrapWizard";
import { PREVIEW_EMBEDDING_SERVICE } from "./bootstrap/preview-data";

export function FirstRunSetup({ initial, embedding, stage, mode = "custom", onComplete, preview = false }: {
  initial: FirstRunSetupStatus;
  embedding?: LocalAIServiceStatus;
  stage: Extract<BootstrapStep, "inference" | "embedding">;
  mode?: "quick" | "custom" | "";
  onComplete: () => void | Promise<void>;
  preview?: boolean;
}) {
  const { t } = useTranslation();
  const installedVariant = initial.inference.variant === "cuda" ? "cuda" : "cpu";
  const [variant, setVariant] = useState<"cpu" | "cuda">(
    initial.inference.ready ? installedVariant : "cpu",
  );
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [embeddingService, setEmbeddingService] = useState<LocalAIServiceStatus | undefined>(embedding);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => window.setup.onProgress(setProgress), []);

  useEffect(() => {
    if (stage !== "embedding" || embeddingService) return;
    if (preview) {
      setEmbeddingService(PREVIEW_EMBEDDING_SERVICE);
      return;
    }
    let cancelled = false;
    void window.localAI.list().then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setError(result.error || t("firstRunSetup.embeddingUnavailable"));
        return;
      }
      const service = result.services.find((item) => item.id === "embedding");
      if (service) setEmbeddingService(service);
      else setError(t("firstRunSetup.embeddingUnavailable"));
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { cancelled = true; };
  }, [embeddingService, preview, stage, t]);

  const start = async () => {
    setWorking(true);
    setError("");
    try {
      if (preview) {
        const advanced = await window.bootstrap.advancePreview();
        if (!advanced.ok) throw new Error(advanced.error || t("firstRunSetup.failed"));
        await onComplete();
        return;
      }
      if (stage === "inference") {
        const remembered = await window.bootstrap.rememberOptions({ variant });
        if (!remembered.ok) throw new Error(remembered.error || t("firstRunSetup.failed"));
        if (!initial.inference.ready || initial.inference.variant !== variant) {
          const installed = await window.setup.installInference({ variant });
          if (!installed.ok) throw new Error(installed.error || t("firstRunSetup.failed"));
        }
        await onComplete();
        return;
      }
      setProgress({ component: "inference", state: "installing", percent: 98, message: t("firstRunSetup.modelPreparing") });
      let embedding = embeddingService;
      if (!embedding) throw new Error(t("firstRunSetup.embeddingUnavailable"));
      const selectedModel = await window.localAI.selectModel({
        serviceId: "embedding",
        modelId: embedding.selected_model_id,
      });
      if (!selectedModel.ok) throw new Error(selectedModel.error || t("firstRunSetup.failed"));
      embedding = selectedModel.service || embedding;
      const selectedDevice = await window.localAI.selectDevice({
        serviceId: "embedding",
        device: embedding.selected_device,
      });
      if (!selectedDevice.ok) throw new Error(selectedDevice.error || t("firstRunSetup.failed"));
      embedding = selectedDevice.service || embedding;
      if (!embedding?.model_present) {
        const download = await window.localAI.control({ serviceId: "embedding", action: "download", device: embedding.selected_device });
        if (!download.ok) throw new Error(download.error || t("firstRunSetup.failed"));
        while (!embedding?.model_present) {
          await new Promise((resolve) => window.setTimeout(resolve, 3_000));
          const snapshot = await window.localAI.list();
          if (!snapshot.ok) throw new Error(snapshot.error || t("firstRunSetup.failed"));
          embedding = snapshot.services.find((item) => item.id === "embedding");
          if (embedding?.state === "download_error") throw new Error(embedding.error || t("firstRunSetup.failed"));
          setProgress({ component: "inference", state: "downloading", percent: embedding?.download_progress || 0, message: t("firstRunSetup.modelPreparing") });
        }
      }
      const started = await window.localAI.control({ serviceId: "embedding", action: "start", device: embedding.selected_device });
      if (!started.ok) throw new Error(started.error || t("firstRunSetup.failed"));
      await onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setWorking(false);
    }
  };

  return (
    <BootstrapWizard
      mode={mode}
      current={stage}
      preview={preview}
      title={t(stage === "embedding" ? "firstRunSetup.embeddingTitle" : "firstRunSetup.title")}
      description={t(stage === "embedding" ? "firstRunSetup.embeddingDescription" : "firstRunSetup.description")}
      actions={(
        <Button variant="primary" size="lg" className="bootstrap-primary-action" onClick={() => void start()} disabled={working}>
          {working ? t("firstRunSetup.working") : error ? t("firstRunSetup.retry") : t(stage === "embedding" ? "firstRunSetup.installEmbedding" : "firstRunSetup.start")}
        </Button>
      )}
    >
        {stage === "inference" ? (
          <>
            <div className="setup-choice-grid">
            <label className={`setup-choice ${variant === "cpu" ? "selected" : ""}`}>
              <input type="radio" checked={variant === "cpu"} onChange={() => setVariant("cpu")} disabled={working} />
              <span><strong>{t("firstRunSetup.cpu")}</strong><small>{t("firstRunSetup.cpuHint")}</small></span>
            </label>
            <label className={`setup-choice ${variant === "cuda" ? "selected" : ""} ${!initial.gpu.detected ? "disabled" : ""}`}>
              <input type="radio" checked={variant === "cuda"} onChange={() => setVariant("cuda")} disabled={working || !initial.gpu.detected} />
              <span><strong>{t("firstRunSetup.cuda")}</strong><small>{initial.gpu.detected ? t("firstRunSetup.detected", { name: initial.gpu.name }) : t("firstRunSetup.cudaHint")}</small></span>
            </label>
            </div>
          </>
        ) : (
          embeddingService ? (
            <div className="bootstrap-service-config">
              <label>
                <span>{t("firstRunSetup.embeddingModel")}</span>
                <SelectMenu
                  value={embeddingService.selected_model_id}
                  placeholder={t("localAiUi.selectModel")}
                  disabled={working || embeddingService.selection_locked}
                  options={embeddingService.models.map((model) => ({
                    value: model.id,
                    label: model.name,
                    description: `${model.expected_size}${model.model_present ? ` · ${t("localAiUi.downloaded")}` : ""}`,
                  }))}
                  onChange={(modelId) => {
                    const model = embeddingService.models.find((item) => item.id === modelId);
                    setEmbeddingService({
                      ...embeddingService,
                      selected_model_id: modelId,
                      model: model?.name || embeddingService.model,
                      expected_size: model?.expected_size || embeddingService.expected_size,
                      expected_size_bytes: model?.expected_size_bytes || embeddingService.expected_size_bytes,
                      model_present: Boolean(model?.model_present),
                      supported_devices: (model?.supported_devices || embeddingService.supported_devices) as LocalAIServiceStatus["supported_devices"],
                    });
                  }}
                />
              </label>
              <label>
                <span>{t("firstRunSetup.embeddingDevice")}</span>
                <SelectMenu
                  value={embeddingService.selected_device}
                  placeholder={t("localAiUi.selectDevice")}
                  disabled={working}
                  options={embeddingService.supported_devices
                    .filter((device) => device !== "cuda" || initial.gpu.detected)
                    .map((device) => ({
                      value: device,
                      label: device === "auto" ? t("localAiUi.auto") : device.toUpperCase(),
                      description: device === "cuda" ? initial.gpu.name : "",
                    }))}
                  onChange={(device) => setEmbeddingService({
                    ...embeddingService,
                    selected_device: device as LocalAIServiceStatus["selected_device"],
                  })}
                />
              </label>
              <div className="bootstrap-service-fact">
                <span>{t("firstRunSetup.embeddingSize")}</span>
                <strong>{embeddingService.expected_size || t("firstRunSetup.sizeUnknown")}</strong>
              </div>
              {embeddingService.selection_locked && (
                <p className="bootstrap-field-note">{t("localAiUi.locked", { reason: embeddingService.selection_lock_reason })}</p>
              )}
            </div>
          ) : (
            <div className="bootstrap-inline-loading"><span className="bootstrap-spinner" /><p>{t("localAiUi.checking")}</p></div>
          )
        )}
        {working && <div className="setup-progress"><div><span style={{ width: `${progress?.percent || 2}%` }} /></div><p>{progress?.state === "retrying"
          ? t("firstRunSetup.autoRetry", { attempt: progress.attempt, max: progress.maxAttempts })
          : progress?.message || t("firstRunSetup.progressFallback")}</p></div>}
        {error && (
          <div className="setup-error">
            <span>{error}</span>
            <button type="button" className="setup-log-link" onClick={() => void window.desktop.openLogDirectory()}>
              {t("bootstrap.openLogs")}
            </button>
          </div>
        )}
    </BootstrapWizard>
  );
}
