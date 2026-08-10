import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FirstRunSetupStatus, SetupProgress } from "../types";

export function FirstRunSetup({ initial, onComplete }: {
  initial: FirstRunSetupStatus;
  onComplete: () => void;
}) {
  const { t } = useTranslation();
  const [variant, setVariant] = useState<"cpu" | "cuda">(initial.gpu.detected ? "cuda" : "cpu");
  const [withFfmpeg, setWithFfmpeg] = useState(true);
  const [progress, setProgress] = useState<SetupProgress | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => window.setup.onProgress(setProgress), []);

  const start = async () => {
    setWorking(true);
    setError("");
    try {
      if (!initial.inference.ready || initial.inference.variant !== variant) {
        const installed = await window.setup.installInference({ variant });
        if (!installed.ok) throw new Error(installed.error || t("firstRunSetup.failed"));
      }
      setProgress({ component: "inference", state: "installing", percent: 98, message: t("firstRunSetup.modelPreparing") });
      const selected = await window.localAI.selectDevice({ serviceId: "embedding", device: variant });
      if (!selected.ok) throw new Error(selected.error || t("firstRunSetup.failed"));
      let embedding = selected.service;
      if (!embedding?.model_present) {
        const download = await window.localAI.control({ serviceId: "embedding", action: "download", device: variant });
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
      const started = await window.localAI.control({ serviceId: "embedding", action: "start", device: variant });
      if (!started.ok) throw new Error(started.error || t("firstRunSetup.failed"));
      if (withFfmpeg && !initial.ffmpeg.ready) {
        const installed = await window.setup.installFfmpeg();
        if (!installed.ok) throw new Error(installed.error || t("firstRunSetup.failed"));
      }
      onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setWorking(false);
    }
  };

  return (
    <div className="first-run-page">
      <section className="first-run-card">
        <header><h1>{t("firstRunSetup.title")}</h1><p>{t("firstRunSetup.description")}</p></header>
        <div className="setup-section-title"><span>{t("firstRunSetup.inference")}</span><em>{t("firstRunSetup.required")}</em></div>
        <label className={`setup-choice ${variant === "cpu" ? "selected" : ""}`}>
          <input type="radio" checked={variant === "cpu"} onChange={() => setVariant("cpu")} disabled={working} />
          <span><strong>{t("firstRunSetup.cpu")}</strong><small>{t("firstRunSetup.cpuHint")}</small></span>
        </label>
        <label className={`setup-choice ${variant === "cuda" ? "selected" : ""} ${!initial.gpu.detected ? "disabled" : ""}`}>
          <input type="radio" checked={variant === "cuda"} onChange={() => setVariant("cuda")} disabled={working || !initial.gpu.detected} />
          <span><strong>{t("firstRunSetup.cuda")}</strong><small>{initial.gpu.detected ? t("firstRunSetup.detected", { name: initial.gpu.name }) : t("firstRunSetup.cudaHint")}</small></span>
        </label>
        <div className="setup-section-title"><span>{t("firstRunSetup.media")}</span><em>{t("firstRunSetup.recommended")}</em></div>
        <label className={`setup-choice ${withFfmpeg ? "selected" : ""}`}>
          <input type="checkbox" checked={withFfmpeg} onChange={(event) => setWithFfmpeg(event.target.checked)} disabled={working || initial.ffmpeg.ready} />
          <span><strong>{t("firstRunSetup.ffmpeg")}</strong><small>{t("firstRunSetup.ffmpegHint")}</small></span>
        </label>
        {working && <div className="setup-progress"><div><span style={{ width: `${progress?.percent || 2}%` }} /></div><p>{progress?.message || t("firstRunSetup.progressFallback")}</p></div>}
        {error && <div className="setup-error">{error}</div>}
        <button className="ui-button primary setup-start" onClick={() => void start()} disabled={working}>{working ? t("firstRunSetup.working") : error ? t("firstRunSetup.retry") : t("firstRunSetup.start")}</button>
      </section>
    </div>
  );
}
