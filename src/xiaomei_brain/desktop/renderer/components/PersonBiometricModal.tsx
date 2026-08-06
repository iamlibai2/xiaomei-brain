import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AgentEntry, PersonBiometricStatus } from "../types";
import { Button, Icon } from "./ui";

interface PersonBiometricModalProps {
  agents: AgentEntry[];
  initialAgentId?: string | null;
  onClose: () => void;
}

type CaptureMode = "idle" | "voice" | "camera" | "saving";

const VOICE_SECONDS = 8;

export function PersonBiometricModal({ agents, initialAgentId, onClose }: PersonBiometricModalProps) {
  const { t } = useTranslation();
  const [agentId, setAgentId] = useState(() => (
    agents.some((agent) => agent.id === initialAgentId) ? initialAgentId! : agents[0]?.id || ""
  ));
  const [status, setStatus] = useState<PersonBiometricStatus | null>(null);
  const [mode, setMode] = useState<CaptureMode>("idle");
  const [voiceRemaining, setVoiceRemaining] = useState(VOICE_SECONDS);
  const [cameraReady, setCameraReady] = useState(false);
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const discardRecordingRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const leaseRef = useRef<{ kind: "voice" | "camera"; agentId: string } | null>(null);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === agentId),
    [agentId, agents],
  );

  const releaseCapture = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (recorderRef.current?.state === "recording") {
      discardRecordingRef.current = true;
      recorderRef.current.stop();
    }
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraReady(false);
    const lease = leaseRef.current;
    leaseRef.current = null;
    if (lease?.kind === "voice") {
      await window.gateway.setContinuousHearing({ agentId: lease.agentId, enabled: false }).catch(() => undefined);
    } else if (lease?.kind === "camera") {
      await window.gateway.setCameraCapture({ agentId: lease.agentId, enabled: false }).catch(() => undefined);
    }
  }, []);

  const loadStatus = useCallback(async (targetAgentId: string) => {
    setStatus(null);
    setError("");
    if (!targetAgentId) return;
    const response = await window.gateway.getPersonBiometrics({ agentId: targetAgentId });
    if (response.error) {
      setError(response.error.message);
      return;
    }
    setStatus(response.result as unknown as PersonBiometricStatus);
  }, []);

  useEffect(() => {
    void loadStatus(agentId);
  }, [agentId, loadStatus]);

  useEffect(() => () => {
    void releaseCapture();
  }, [releaseCapture]);

  const enroll = async (
    kind: "voiceprint" | "face",
    blob: Blob,
    mimeType: "audio/webm" | "audio/ogg" | "audio/wav" | "image/jpeg" | "image/png",
  ) => {
    setMode("saving");
    setError("");
    try {
      const response = await window.gateway.enrollPersonBiometric({
        agentId,
        kind,
        dataBase64: await blobToBase64(blob),
        mimeType,
        size: blob.size,
      });
      if (response.error) throw new Error(response.error.message);
      setStatus((current) => ({
        ...(current || {} as PersonBiometricStatus),
        ...(response.result as unknown as PersonBiometricStatus),
      }));
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : String(captureError));
    } finally {
      await releaseCapture();
      setMode("idle");
    }
  };

  const recordVoice = async () => {
    if (!agentId || mode !== "idle") return;
    setError("");
    setVoiceRemaining(VOICE_SECONDS);
    try {
      const lease = await window.gateway.setContinuousHearing({ agentId, enabled: true });
      if (lease.error) throw new Error(lease.error.message);
      leaseRef.current = { kind: "voice", agentId };
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")
          ? "audio/ogg;codecs=opus"
          : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      discardRecordingRef.current = false;
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => setError(t("identityUi.voiceRecordFailed"));
      recorder.onstop = () => {
        if (discardRecordingRef.current) return;
        const normalizedMime = recorder.mimeType.startsWith("audio/ogg") ? "audio/ogg" : "audio/webm";
        void enroll("voiceprint", new Blob(chunks, { type: normalizedMime }), normalizedMime);
      };
      setMode("voice");
      recorder.start(250);
      const startedAt = Date.now();
      timerRef.current = window.setInterval(() => {
        const remaining = Math.max(0, VOICE_SECONDS - Math.floor((Date.now() - startedAt) / 1000));
        setVoiceRemaining(remaining);
        if (remaining === 0 && recorder.state === "recording") recorder.stop();
      }, 250);
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : String(captureError));
      await releaseCapture();
      setMode("idle");
    }
  };

  const openCamera = async () => {
    if (!agentId || mode !== "idle") return;
    setError("");
    setCameraReady(false);
    try {
      const lease = await window.gateway.setCameraCapture({ agentId, enabled: true });
      if (lease.error) throw new Error(lease.error.message);
      leaseRef.current = { kind: "camera", agentId };
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      streamRef.current = stream;
      setMode("camera");
      window.setTimeout(() => {
        if (videoRef.current) videoRef.current.srcObject = stream;
      }, 0);
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : String(captureError));
      await releaseCapture();
      setMode("idle");
    }
  };

  const captureFace = async () => {
    const video = videoRef.current;
    if (!video?.videoWidth || !video.videoHeight) {
      setError(t("identityUi.cameraNotReady"));
      return;
    }
    const scale = Math.min(1, 1280 / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await canvasToBlob(canvas);
    await enroll("face", blob, "image/jpeg");
  };

  const close = async () => {
    await releaseCapture();
    onClose();
  };

  return (
    <div className="identity-account-modal-backdrop" onMouseDown={() => void close()}>
      <section className="identity-account-modal identity-biometric-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <h3>{t("identityUi.biometricsTitle")}</h3>
            <p>{t("identityUi.biometricsDescription")}</p>
          </div>
          <button type="button" aria-label={t("common.close")} onClick={() => void close()}>
            <Icon name="x" size={18} />
          </button>
        </header>

        {agents.length === 0 ? (
          <div className="identity-biometric-empty">{t("identityUi.biometricsConnectAgent")}</div>
        ) : (
          <>
            <div className="connect-field identity-biometric-agent">
              <label>{t("identityUi.biometricsAgent")}</label>
              <select value={agentId} disabled={mode !== "idle"} onChange={(event) => setAgentId(event.target.value)}>
                {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
              </select>
              {status && <small>{t("identityUi.biometricsPerson", { name: status.display_name })}</small>}
            </div>

            <div className="identity-biometric-grid">
              <article className="identity-biometric-card">
                <div className="identity-biometric-icon"><Icon name="microphone" size={20} /></div>
                <div className="identity-biometric-copy">
                  <div><strong>{t("identityUi.voiceprint")}</strong><span className={status?.voiceprint_enrolled ? "is-enrolled" : ""}>{status?.voiceprint_enrolled ? t("identityUi.enrolled") : t("identityUi.notEnrolled")}</span></div>
                  <p>{mode === "voice" ? t("identityUi.voiceRecording", { seconds: voiceRemaining }) : t("identityUi.voiceprintHint")}</p>
                </div>
                <Button variant="secondary" size="sm" disabled={!status || mode !== "idle"} onClick={() => void recordVoice()}>
                  {status?.voiceprint_enrolled ? t("identityUi.reEnroll") : t("identityUi.startRecording")}
                </Button>
              </article>

              <article className="identity-biometric-card">
                <div className="identity-biometric-icon"><Icon name="camera" size={20} /></div>
                <div className="identity-biometric-copy">
                  <div><strong>{t("identityUi.face")}</strong><span className={status?.face_enrolled ? "is-enrolled" : ""}>{status?.face_enrolled ? t("identityUi.enrolled") : t("identityUi.notEnrolled")}</span></div>
                  <p>{t("identityUi.faceHint")}</p>
                </div>
                <Button variant="secondary" size="sm" disabled={!status || mode !== "idle"} onClick={() => void openCamera()}>
                  {status?.face_enrolled ? t("identityUi.reEnroll") : t("identityUi.openCamera")}
                </Button>
              </article>
            </div>

            {mode === "camera" && (
              <div className="identity-camera-capture">
                <div className="identity-camera-stage">
                  <video
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    onCanPlay={() => setCameraReady(true)}
                  />
                  <div className="identity-camera-guide" aria-hidden="true" />
                </div>
                <div className="identity-camera-actions">
                  <div>
                    <strong>{cameraReady ? t("identityUi.cameraReady") : t("identityUi.cameraPreparing")}</strong>
                    <span>{t("identityUi.cameraConfirmHint")}</span>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void releaseCapture().then(() => setMode("idle"));
                    }}
                  >
                    {t("identityUi.cancel")}
                  </Button>
                  <Button
                    variant="primary"
                    icon="camera"
                    disabled={!cameraReady}
                    onClick={() => void captureFace()}
                  >
                    {t("identityUi.captureFace")}
                  </Button>
                </div>
              </div>
            )}
            {mode === "saving" && <p className="identity-biometric-progress">{t("identityUi.extractingBiometric")}</p>}
            {error && <p className="connect-error">{error}</p>}
          </>
        )}
        <footer><Button variant="secondary" onClick={() => void close()}>{t("identityUi.done")}</Button></footer>
      </section>
    </div>
  );
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Failed to read media"));
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.readAsDataURL(blob);
  });
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Failed to encode image")), "image/jpeg", 0.9);
  });
}
