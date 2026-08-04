let playbackQueue = Promise.resolve();
let playbackEpoch = 0;
let activePlayback: ActivePlayback | null = null;

interface ActivePlayback {
  agentId: string;
  audio: HTMLAudioElement;
  finish: (status: "completed" | "interrupted" | "failed") => void;
}

export const DESKTOP_SPEECH_STARTED = "xiaomei:desktop-speech-started";
export const DESKTOP_SPEECH_FINISHED = "xiaomei:desktop-speech-finished";

/** Install the Desktop speaker once; every Agent connection remains isolated. */
export function installDesktopEmbodiment(): () => void {
  return window.gateway.onEvent((raw) => {
    if (raw.event !== "embodiment.audio.output") return;
    const payload = raw.data as Record<string, unknown>;
    const dataBase64 = typeof payload.data_base64 === "string"
      ? payload.data_base64
      : "";
    const mimeType = typeof payload.mime_type === "string"
      ? payload.mime_type
      : "audio/ogg";
    if (!dataBase64) return;
    const epoch = playbackEpoch;
    playbackQueue = playbackQueue
      .catch(() => undefined)
      .then(() => {
        if (epoch !== playbackEpoch) return;
        return playBase64Audio(raw.agentId, dataBase64, mimeType, epoch);
      });
  });
}

/** Stop current Desktop speech and discard audio that was queued before it. */
export function stopDesktopSpeech(agentId?: string): boolean {
  const playback = activePlayback;
  if (playback && agentId && playback.agentId !== agentId) return false;
  playbackEpoch += 1;
  if (!playback) return false;
  playback.finish("interrupted");
  return true;
}

async function playBase64Audio(
  agentId: string,
  dataBase64: string,
  mimeType: string,
  epoch: number,
): Promise<void> {
  const binary = atob(dataBase64);
  const data = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    data[index] = binary.charCodeAt(index);
  }
  const url = URL.createObjectURL(new Blob([data], { type: mimeType }));
  const audio = new Audio(url);

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (status: "completed" | "interrupted" | "failed") => {
      if (settled) return;
      settled = true;
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      URL.revokeObjectURL(url);
      if (activePlayback?.audio === audio) activePlayback = null;
      window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_FINISHED, {
        detail: { agentId, status },
      }));
      if (status === "failed") reject(new Error("Desktop 无法播放 Agent 语音"));
      else resolve();
    };
    const onEnded = () => finish("completed");
    const onError = () => finish("failed");
    activePlayback = { agentId, audio, finish };
    audio.addEventListener("ended", onEnded, { once: true });
    audio.addEventListener("error", onError, { once: true });
    window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_STARTED, {
      detail: { agentId },
    }));
    if (epoch !== playbackEpoch) {
      finish("interrupted");
      return;
    }
    void audio.play().catch(() => finish("failed"));
  });
}
