let playbackQueue = Promise.resolve();

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
    playbackQueue = playbackQueue
      .catch(() => undefined)
      .then(() => playBase64Audio(dataBase64, mimeType));
  });
}

async function playBase64Audio(dataBase64: string, mimeType: string): Promise<void> {
  const binary = atob(dataBase64);
  const data = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    data[index] = binary.charCodeAt(index);
  }
  const url = URL.createObjectURL(new Blob([data], { type: mimeType }));
  try {
    const audio = new Audio(url);
    await audio.play();
    await new Promise<void>((resolve, reject) => {
      audio.addEventListener("ended", () => resolve(), { once: true });
      audio.addEventListener(
        "error",
        () => reject(new Error("Desktop 无法播放 Agent 语音")),
        { once: true },
      );
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
