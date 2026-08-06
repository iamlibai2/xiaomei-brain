import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { IdentityStatus, PersonBiometricStatus } from "../types";
import { Icon } from "./ui";

interface DesktopLockScreenProps {
  identity: IdentityStatus;
  onUnlock: () => void;
}

export function DesktopLockScreen({ identity, onUnlock }: DesktopLockScreenProps) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [faceAvailable, setFaceAvailable] = useState(false);
  const [voiceAvailable, setVoiceAvailable] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const cameraLeaseRef = useRef(false);

  const stopCamera = useCallback(async () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraActive(false);
    if (cameraLeaseRef.current && activeAgentId) {
      cameraLeaseRef.current = false;
      await window.gateway.setCameraCapture({ agentId: activeAgentId, enabled: false }).catch(() => undefined);
    }
  }, [activeAgentId]);

  const unlock = useCallback(() => {
    void stopCamera();
    onUnlock();
  }, [onUnlock, stopCamera]);

  const verifyFace = useCallback(async () => {
    if (!activeAgentId || checking) return;
    setChecking(true);
    setError("");
    try {
      const lease = await window.gateway.setCameraCapture({ agentId: activeAgentId, enabled: true });
      if (lease.error) throw new Error(lease.error.message);
      cameraLeaseRef.current = true;
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 540 } },
      });
      streamRef.current = stream;
      setCameraActive(true);
      const video = videoRef.current;
      if (!video) throw new Error(t("lockUi.cameraUnavailable"));
      video.srcObject = stream;
      await video.play();
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      if (!video.videoWidth || !video.videoHeight) throw new Error(t("lockUi.cameraUnavailable"));
      const canvas = document.createElement("canvas");
      const scale = Math.min(1, 960 / video.videoWidth);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await canvasToBlob(canvas);
      const response = await window.gateway.verifyPersonBiometric({
        agentId: activeAgentId,
        kind: "face",
        dataBase64: await blobToBase64(blob),
        mimeType: "image/jpeg",
        size: blob.size,
      });
      if (response.error) throw new Error(response.error.message);
      const result = response.result as { matched?: boolean } | undefined;
      if (result?.matched) {
        unlock();
        return;
      }
      setError(t("lockUi.faceMismatch"));
    } catch (captureError) {
      setError(captureError instanceof Error ? captureError.message : String(captureError));
    } finally {
      await stopCamera();
      setChecking(false);
    }
  }, [activeAgentId, checking, stopCamera, t, unlock]);

  useEffect(() => {
    if (!activeAgentId) return;
    let cancelled = false;
    void window.gateway.getPersonBiometrics({ agentId: activeAgentId }).then((response) => {
      if (cancelled || response.error) return;
      const status = response.result as unknown as PersonBiometricStatus;
      setFaceAvailable(Boolean(status.face_enrolled));
      setVoiceAvailable(Boolean(status.voiceprint_enrolled));
    });
    return () => { cancelled = true; };
  }, [activeAgentId]);

  useEffect(() => () => { void stopCamera(); }, [stopCamera]);

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || checking) return;
    setChecking(true);
    setError("");
    try {
      const result = await window.identity.verifyPassword({
        password,
        subject: identity.subject,
      });
      if (!result.ok) {
        setError(t("lockUi.passwordIncorrect"));
        setPassword("");
        return;
      }
      unlock();
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="desktop-lock-screen" role="dialog" aria-modal="true" aria-label={t("lockUi.title")}>
      <div className="desktop-lock-card">
        <div className="desktop-lock-avatar">{identity.displayName?.[0] || "?"}</div>
        <h1>{identity.displayName}</h1>
        <p className="desktop-lock-title">{t("lockUi.title")}</p>

        <div className={`desktop-lock-camera ${cameraActive ? "is-active" : ""}`} aria-hidden={!cameraActive}>
          <video ref={videoRef} muted playsInline />
          <span><Icon name="camera" size={22} /></span>
        </div>

        <form onSubmit={submitPassword}>
          <label htmlFor="desktop-lock-password">{t("lockUi.password")}</label>
          <div className="desktop-lock-password-row">
            <input
              id="desktop-lock-password"
              autoFocus
              type="password"
              value={password}
              disabled={checking}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("lockUi.passwordPlaceholder")}
            />
            <button type="submit" disabled={!password || checking} aria-label={t("lockUi.unlock")}>
              <Icon name="chevron-right" size={18} />
            </button>
          </div>
        </form>

        {error && <p className="desktop-lock-error">{error}</p>}
        <div className="desktop-lock-biometric-actions">
          {faceAvailable && (
            <button type="button" disabled={checking} onClick={() => void verifyFace()}>
              <Icon name="camera" size={16} /> {t("lockUi.faceUnlock")}
            </button>
          )}
          {voiceAvailable && (
            <span><Icon name="microphone" size={15} /> {t("lockUi.voiceHint")}</span>
          )}
        </div>
        <p className="desktop-lock-background-hint">{t("lockUi.backgroundHint")}</p>
      </div>
    </div>
  );
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error || new Error("blob read failed"));
    reader.readAsDataURL(blob);
  });
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("image capture failed")), "image/jpeg", 0.9);
  });
}
