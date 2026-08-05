import i18n from "./i18n";

let playbackQueue = Promise.resolve();
let playbackEpoch = 0;
let activePlayback: ActivePlayback | null = null;
let activeStream: StreamingPlayback | null = null;

type PlaybackStatus = "completed" | "interrupted" | "failed";
type PcmCodec = "pcm_s16" | "pcm_f32";

interface ActivePlayback {
  agentId: string;
  audio: HTMLAudioElement;
  finish: (status: PlaybackStatus) => void;
}

interface StreamingPlayback {
  agentId: string;
  speechId: string;
  codec: PcmCodec;
  sampleRate: number;
  channels: number;
  initialBufferMs: number;
  expectedSequence: number;
  pending: Uint8Array[];
  pendingBytes: number;
  context: AudioContext;
  sources: Set<AudioBufferSourceNode>;
  nextStartTime: number;
  started: boolean;
  completionTimer: ReturnType<typeof setTimeout> | null;
  finish: (status: PlaybackStatus) => void;
}

export const DESKTOP_SPEECH_STARTED = "xiaomei:desktop-speech-started";
export const DESKTOP_SPEECH_FINISHED = "xiaomei:desktop-speech-finished";

export function isDesktopSpeechActive(): boolean {
  return activePlayback !== null || activeStream !== null;
}

/** Install the Desktop speaker once; every Agent connection remains isolated. */
export function installDesktopEmbodiment(): () => void {
  return window.gateway.onEvent((raw) => {
    const payload = asRecord(raw.data);
    if (raw.event === "embodiment.audio.output.started") {
      startPcmStream(raw.agentId, payload);
      return;
    }
    if (raw.event === "embodiment.audio.output.chunk") {
      appendPcmChunk(raw.agentId, payload);
      return;
    }
    if (raw.event === "embodiment.audio.output.completed") {
      completePcmStream(raw.agentId, payload);
      return;
    }
    if (raw.event === "embodiment.audio.output.failed") {
      failPcmStream(raw.agentId, payload);
      return;
    }
    if (raw.event !== "embodiment.audio.output") return;

    const dataBase64 = stringValue(payload.data_base64);
    const mimeType = stringValue(payload.mime_type) || "audio/ogg";
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
  const legacy = activePlayback;
  const stream = activeStream;
  if (agentId && legacy?.agentId !== agentId && stream?.agentId !== agentId) return false;
  playbackEpoch += 1;
  let stopped = false;
  if (legacy && (!agentId || legacy.agentId === agentId)) {
    legacy.finish("interrupted");
    stopped = true;
  }
  if (stream && (!agentId || stream.agentId === agentId)) {
    stream.finish("interrupted");
    stopped = true;
  }
  return stopped;
}

function startPcmStream(agentId: string, payload: Record<string, unknown>): void {
  const speechId = stringValue(payload.speech_id);
  const codec = stringValue(payload.codec);
  const sampleRate = numberValue(payload.sample_rate);
  const channels = numberValue(payload.channels);
  if (
    !speechId
    || (codec !== "pcm_s16" && codec !== "pcm_f32")
    || sampleRate <= 0
    || channels <= 0
  ) return;

  stopDesktopSpeech();
  const context = new AudioContext({ sampleRate });
  const stream: StreamingPlayback = {
    agentId,
    speechId,
    codec,
    sampleRate,
    channels,
    initialBufferMs: Math.max(0, Math.min(numberValue(payload.initial_buffer_ms, 500), 10_000)),
    expectedSequence: 1,
    pending: [],
    pendingBytes: 0,
    context,
    sources: new Set(),
    nextStartTime: 0,
    started: false,
    completionTimer: null,
    finish: () => undefined,
  };
  stream.finish = (status) => finishPcmStream(stream, status);
  activeStream = stream;
}

function appendPcmChunk(agentId: string, payload: Record<string, unknown>): void {
  const stream = activeStream;
  if (!stream || stream.agentId !== agentId || stream.speechId !== stringValue(payload.speech_id)) return;
  const sequence = numberValue(payload.sequence);
  if (sequence !== stream.expectedSequence) {
    stream.finish("failed");
    return;
  }
  stream.expectedSequence += 1;
  const chunk = decodeBase64(stringValue(payload.data_base64));
  if (!chunk.length) return;
  stream.pending.push(chunk);
  stream.pendingBytes += chunk.byteLength;

  const bytesPerSample = stream.codec === "pcm_f32" ? 4 : 2;
  const initialBytes = Math.max(
    bytesPerSample * stream.channels,
    Math.round(stream.sampleRate * stream.channels * bytesPerSample * stream.initialBufferMs / 1000),
  );
  if (stream.started || stream.pendingBytes >= initialBytes) schedulePendingPcm(stream);
}

function completePcmStream(agentId: string, payload: Record<string, unknown>): void {
  const stream = activeStream;
  if (!stream || stream.agentId !== agentId || stream.speechId !== stringValue(payload.speech_id)) return;
  schedulePendingPcm(stream);
  if (!stream.started) {
    stream.finish("completed");
    return;
  }
  const remainingMs = Math.max(0, (stream.nextStartTime - stream.context.currentTime) * 1000);
  stream.completionTimer = setTimeout(() => stream.finish("completed"), remainingMs + 40);
}

function failPcmStream(agentId: string, payload: Record<string, unknown>): void {
  const stream = activeStream;
  if (!stream || stream.agentId !== agentId || stream.speechId !== stringValue(payload.speech_id)) return;
  stream.finish("failed");
}

function schedulePendingPcm(stream: StreamingPlayback): void {
  if (!stream.pending.length || activeStream !== stream) return;
  if (!stream.started) {
    stream.started = true;
    stream.nextStartTime = stream.context.currentTime + 0.03;
    window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_STARTED, {
      detail: { agentId: stream.agentId },
    }));
    void stream.context.resume().catch(() => stream.finish("failed"));
  }
  if (stream.nextStartTime < stream.context.currentTime + 0.02) {
    stream.nextStartTime = stream.context.currentTime + 0.03;
  }

  for (const bytes of stream.pending.splice(0)) {
    const buffer = pcmAudioBuffer(stream.context, bytes, stream.codec, stream.sampleRate, stream.channels);
    if (!buffer) continue;
    const source = stream.context.createBufferSource();
    source.buffer = buffer;
    source.connect(stream.context.destination);
    stream.sources.add(source);
    source.addEventListener("ended", () => stream.sources.delete(source), { once: true });
    source.start(stream.nextStartTime);
    stream.nextStartTime += buffer.duration;
  }
  stream.pendingBytes = 0;
}

function pcmAudioBuffer(
  context: AudioContext,
  bytes: Uint8Array,
  codec: PcmCodec,
  sampleRate: number,
  channels: number,
): AudioBuffer | null {
  const sampleWidth = codec === "pcm_f32" ? 4 : 2;
  const frames = Math.floor(bytes.byteLength / (sampleWidth * channels));
  if (frames <= 0) return null;
  const buffer = context.createBuffer(channels, frames, sampleRate);
  const view = new DataView(bytes.buffer, bytes.byteOffset, frames * sampleWidth * channels);
  for (let channel = 0; channel < channels; channel += 1) {
    const output = buffer.getChannelData(channel);
    for (let frame = 0; frame < frames; frame += 1) {
      const offset = (frame * channels + channel) * sampleWidth;
      output[frame] = codec === "pcm_f32"
        ? Math.max(-1, Math.min(1, view.getFloat32(offset, true)))
        : view.getInt16(offset, true) / 32768;
    }
  }
  return buffer;
}

function finishPcmStream(stream: StreamingPlayback, status: PlaybackStatus): void {
  if (activeStream !== stream) return;
  activeStream = null;
  if (stream.completionTimer) clearTimeout(stream.completionTimer);
  for (const source of stream.sources) {
    try { source.stop(); } catch { /* already ended */ }
  }
  stream.sources.clear();
  stream.pending = [];
  stream.pendingBytes = 0;
  void stream.context.close().catch(() => undefined);
  if (stream.started || status === "failed") {
    window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_FINISHED, {
      detail: { agentId: stream.agentId, status },
    }));
  }
}

async function playBase64Audio(
  agentId: string,
  dataBase64: string,
  mimeType: string,
  epoch: number,
): Promise<void> {
  const data = decodeBase64(dataBase64);
  const blobData = data.buffer.slice(
    data.byteOffset,
    data.byteOffset + data.byteLength,
  ) as ArrayBuffer;
  const url = URL.createObjectURL(new Blob([blobData], { type: mimeType }));
  const audio = new Audio(url);

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (status: PlaybackStatus) => {
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
      if (status === "failed") reject(new Error(i18n.t("home.unablePlay")));
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

function decodeBase64(value: string): Uint8Array {
  if (!value) return new Uint8Array();
  try {
    const binary = atob(value);
    const data = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) data[index] = binary.charCodeAt(index);
    return data;
  } catch {
    return new Uint8Array();
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
