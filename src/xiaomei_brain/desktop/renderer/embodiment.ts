import i18n from "./i18n";
import {
  controlMediaPlayback,
  registerMediaPlaybackController,
  playNextMediaTrack,
  playPreviousMediaTrack,
  seekMediaPlayback,
  setMediaPlaybackVolume,
  updateMediaPlayback,
} from "./media-playback";

let playbackQueue = Promise.resolve();
let playbackEpoch = 0;
let activePlayback: ActivePlayback | null = null;
let activeStream: StreamingPlayback | null = null;
let activeMediaFile: MediaFilePlayback | null = null;
let mediaQueue: MediaQueueItem[] = [];
let mediaQueueIndex = -1;
let resumeMediaAfterSpeech = false;

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
  progressTimer: ReturnType<typeof setInterval> | null;
  mediaKind: "music" | "speech";
  title: string;
  sourceRef: string;
  playbackStartTime: number;
  durationMs: number;
  inputCompleted: boolean;
  finish: (status: PlaybackStatus) => void;
}

interface MediaFilePlayback {
  agentId: string;
  playbackId: string;
  audio: HTMLMediaElement;
  title: string;
  sourceRef: string;
  stopped: boolean;
  dispose: () => void;
}

interface MediaQueueItem {
  agentId: string;
  playbackId: string;
  mediaPath: string;
  title: string;
  sourceRef: string;
  personId: string;
  sessionId: string;
  expiresAt: number;
  playlistId: string;
  playlistIndex: number;
  artifactId: string;
  toolCallId: string;
  mediaKind: "music" | "video";
  mimeType: string;
}

export const DESKTOP_SPEECH_STARTED = "xiaomei:desktop-speech-started";
export const DESKTOP_SPEECH_FINISHED = "xiaomei:desktop-speech-finished";

export function isDesktopSpeechActive(): boolean {
  return activePlayback !== null || activeStream !== null || Boolean(
    activeMediaFile && !activeMediaFile.audio.paused && !activeMediaFile.audio.ended,
  );
}

/** Install the Desktop speaker once; every Agent connection remains isolated. */
export function installDesktopEmbodiment(): () => void {
  registerMediaPlaybackController({
    control: controlActiveMedia,
    seek: seekActiveMedia,
    setVolume: setActiveMediaVolume,
    previous: playPreviousQueuedMedia,
    next: playNextQueuedMedia,
    playTrack: playQueuedMediaTrack,
    removeTrack: removeQueuedMediaTrack,
    clearQueue: clearMediaQueue,
  });
  return window.gateway.onEvent((raw) => {
    const payload = asRecord(raw.data);
    if (raw.event === "embodiment.media.output.started") {
      enqueueMediaFilePlayback(raw.agentId, payload);
      return;
    }
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
  const media = activeMediaFile;
  if (
    agentId
    && legacy?.agentId !== agentId
    && stream?.agentId !== agentId
    && media?.agentId !== agentId
  ) return false;
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
  if (media && (!agentId || media.agentId === agentId)) {
    media.audio.pause();
    try { media.audio.currentTime = 0; } catch { /* metadata not loaded yet */ }
    media.stopped = true;
    updateMediaPlayback({ status: "stopped", positionMs: 0 });
    stopped = true;
  }
  return stopped;
}

export function enqueueMediaFilePlayback(agentId: string, payload: Record<string, unknown>): void {
  const playbackId = stringValue(payload.playback_id);
  const mediaPath = stringValue(payload.media_path);
  if (!playbackId || !mediaPath.startsWith("/media/")) return;
  const item: MediaQueueItem = {
    agentId,
    playbackId,
    mediaPath,
    title: stringValue(payload.title) || i18n.t("mediaPlayer.untitled"),
    sourceRef: stringValue(payload.source_ref),
    personId: stringValue(payload.person_id),
    sessionId: stringValue(payload.session_id),
    expiresAt: numberValue(payload.expires_at),
    playlistId: stringValue(payload.playlist_id),
    playlistIndex: Math.max(0, numberValue(payload.playlist_index)),
    artifactId: stringValue(payload.artifact_id) || stringValue(payload.source_id),
    toolCallId: stringValue(payload.tool_call_id),
    mediaKind: stringValue(payload.media_kind) === "video" ? "video" : "music",
    mimeType: stringValue(payload.mime_type),
  };
  const owner = mediaQueue[0];
  if (
    owner
    && (
      owner.agentId !== item.agentId
      || owner.personId !== item.personId
    )
  ) {
    mediaQueue = [];
    mediaQueueIndex = -1;
  }
  const startsNewPlaylist = Boolean(
    payload.append_to_queue !== true
    &&
    item.playlistId
    && (item.playlistIndex === 0 || mediaQueue[0]?.playlistId !== item.playlistId),
  );
  if (startsNewPlaylist) {
    mediaQueue = [];
    mediaQueueIndex = -1;
  }
  mediaQueue = [...mediaQueue.filter((track) => track.playbackId !== item.playbackId), item]
    .sort((left, right) => left.playlistIndex - right.playlistIndex)
    .slice(-30);

  const autoplay = payload.autoplay !== false;
  if (autoplay) {
    mediaQueueIndex = mediaQueue.findIndex((track) => track.playbackId === item.playbackId);
    playMediaQueueItem(item);
  } else {
    publishMediaQueue();
  }
}

function publishMediaQueue(): void {
  const queue = mediaQueue.map((track) => ({
      id: track.playbackId,
      title: track.title,
      agentId: track.agentId,
      personId: track.personId,
      sessionId: track.sessionId,
      sourceRef: track.sourceRef,
      artifactId: track.artifactId || undefined,
      mediaKind: track.mediaKind,
  }));
  if (!activeMediaFile && mediaQueue.length > 0) {
    if (mediaQueueIndex < 0 || mediaQueueIndex >= mediaQueue.length) mediaQueueIndex = 0;
    const current = mediaQueue[mediaQueueIndex];
    updateMediaPlayback({
      agentId: current.agentId,
      playbackId: current.playbackId,
      mediaKind: current.mediaKind,
      title: current.title,
      sourceRef: current.sourceRef,
      sessionId: current.sessionId,
      toolCallId: current.toolCallId,
      status: "stopped",
      positionMs: 0,
      durationMs: 0,
      seekable: false,
      queue,
      currentIndex: mediaQueueIndex,
      inlinePlayerVisible: false,
      mediaUrl: "",
      artifactId: current.artifactId,
    });
    return;
  }
  updateMediaPlayback({ queue, currentIndex: mediaQueueIndex });
}

function playMediaQueueItem(item: MediaQueueItem): void {
  const { agentId, playbackId, mediaPath } = item;
  disposeActiveMediaFile();
  stopDesktopSpeech();

  let mediaUrl = "";
  try {
    mediaUrl = new URL(mediaPath, `http://${agentId}`).toString();
  } catch {
    return;
  }
  if (item.mediaKind === "video") {
    const queue = mediaQueue.map((track) => ({
      id: track.playbackId,
      title: track.title,
      agentId: track.agentId,
      personId: track.personId,
      sessionId: track.sessionId,
      sourceRef: track.sourceRef,
      artifactId: track.artifactId || undefined,
      mediaKind: track.mediaKind,
    }));
    updateMediaPlayback({
      agentId,
      playbackId,
      mediaKind: "video",
      title: item.title,
      sourceRef: item.sourceRef,
      sessionId: item.sessionId,
      toolCallId: item.toolCallId,
      artifactId: item.artifactId,
      mediaUrl,
      inlinePlayerVisible: true,
      status: "buffering",
      positionMs: 0,
      durationMs: 0,
      seekable: false,
      queue,
      currentIndex: mediaQueueIndex,
    });
    return;
  }
  const audio = new Audio(mediaUrl);
  audio.preload = "metadata";
  const playback: MediaFilePlayback = {
    agentId,
    playbackId,
    audio,
    title: item.title,
    sourceRef: item.sourceRef,
    stopped: false,
    dispose: () => undefined,
  };
  const publishProgress = () => {
    if (activeMediaFile !== playback) return;
    updateMediaPlayback({
      positionMs: Math.max(0, Math.round(audio.currentTime * 1000)),
      durationMs: Number.isFinite(audio.duration) ? Math.max(0, Math.round(audio.duration * 1000)) : 0,
      volume: audio.volume,
      seekable: Number.isFinite(audio.duration) && audio.duration > 0,
    });
  };
  const onLoaded = () => publishProgress();
  const onTime = () => publishProgress();
  const onWaiting = () => updateMediaPlayback({ status: "buffering" });
  const onPlaying = () => {
    playback.stopped = false;
    updateMediaPlayback({ status: "playing" });
    publishProgress();
  };
  const onPause = () => {
    if (activeMediaFile === playback && !audio.ended && !playback.stopped) {
      updateMediaPlayback({ status: "paused" });
    }
  };
  const onEnded = () => {
    publishProgress();
    if (!playNextQueuedMedia()) updateMediaPlayback({ status: "completed" });
  };
  const onError = () => updateMediaPlayback({ status: "failed" });
  playback.dispose = () => {
    audio.pause();
    audio.removeEventListener("loadedmetadata", onLoaded);
    audio.removeEventListener("durationchange", onLoaded);
    audio.removeEventListener("timeupdate", onTime);
    audio.removeEventListener("waiting", onWaiting);
    audio.removeEventListener("playing", onPlaying);
    audio.removeEventListener("pause", onPause);
    audio.removeEventListener("ended", onEnded);
    audio.removeEventListener("error", onError);
    audio.removeAttribute("src");
    audio.load();
  };
  audio.addEventListener("loadedmetadata", onLoaded);
  audio.addEventListener("durationchange", onLoaded);
  audio.addEventListener("timeupdate", onTime);
  audio.addEventListener("waiting", onWaiting);
  audio.addEventListener("playing", onPlaying);
  audio.addEventListener("pause", onPause);
  audio.addEventListener("ended", onEnded);
  audio.addEventListener("error", onError);
  activeMediaFile = playback;
  updateMediaPlayback({
    agentId,
    playbackId,
    mediaKind: item.mediaKind,
    title: playback.title,
    sourceRef: playback.sourceRef,
    sessionId: item.sessionId,
    toolCallId: item.toolCallId,
    inlinePlayerVisible: false,
    status: "buffering",
    positionMs: 0,
    durationMs: 0,
    volume: audio.volume,
    seekable: false,
    mediaUrl,
    artifactId: item.artifactId,
  });
  publishMediaQueue();
  void audio.play().catch(() => updateMediaPlayback({ status: "failed" }));
}

function playPreviousQueuedMedia(): boolean {
  if (mediaQueueIndex <= 0) return false;
  mediaQueueIndex -= 1;
  playMediaQueueItem(mediaQueue[mediaQueueIndex]);
  return true;
}

function playNextQueuedMedia(): boolean {
  if (mediaQueueIndex < 0 || mediaQueueIndex >= mediaQueue.length - 1) return false;
  mediaQueueIndex += 1;
  playMediaQueueItem(mediaQueue[mediaQueueIndex]);
  return true;
}

function playQueuedMediaTrack(trackId: string): boolean {
  const index = mediaQueue.findIndex((track) => track.playbackId === trackId);
  if (index < 0) return false;
  mediaQueueIndex = index;
  playMediaQueueItem(mediaQueue[index]);
  return true;
}

function removeQueuedMediaTrack(trackId: string): boolean {
  const index = mediaQueue.findIndex((track) => track.playbackId === trackId);
  if (index < 0) return false;
  const removingCurrent = index === mediaQueueIndex;
  mediaQueue.splice(index, 1);
  if (!mediaQueue.length) return clearMediaQueue();
  if (index < mediaQueueIndex) mediaQueueIndex -= 1;
  if (removingCurrent) {
    mediaQueueIndex = Math.min(index, mediaQueue.length - 1);
    playMediaQueueItem(mediaQueue[mediaQueueIndex]);
  } else {
    publishMediaQueue();
  }
  return true;
}

function clearMediaQueue(): boolean {
  const hadQueue = mediaQueue.length > 0 || activeMediaFile !== null;
  mediaQueue = [];
  mediaQueueIndex = -1;
  resumeMediaAfterSpeech = false;
  disposeActiveMediaFile();
  updateMediaPlayback({
    agentId: "",
    playbackId: "",
    mediaKind: "speech",
    title: "",
    sourceRef: "",
    sessionId: "",
    toolCallId: "",
    status: "idle",
    positionMs: 0,
    durationMs: 0,
    seekable: false,
    queue: [],
    currentIndex: -1,
    inlinePlayerVisible: false,
    mediaUrl: "",
    artifactId: "",
  });
  return hadQueue;
}

/** Bind the visible video element to the same playback controller used by audio. */
export function bindVideoPlaybackElement(playbackId: string, video: HTMLVideoElement): () => void {
  const item = mediaQueue.find((entry) => entry.playbackId === playbackId);
  if (!item || item.mediaKind !== "video") return () => undefined;
  disposeActiveMediaFile();
  const playback: MediaFilePlayback = {
    agentId: item.agentId,
    playbackId,
    audio: video,
    title: item.title,
    sourceRef: item.sourceRef,
    stopped: false,
    dispose: () => undefined,
  };
  const publish = () => updateMediaPlayback({
    positionMs: Math.max(0, Math.round(video.currentTime * 1000)),
    durationMs: Number.isFinite(video.duration) ? Math.max(0, Math.round(video.duration * 1000)) : 0,
    volume: video.volume,
    seekable: Number.isFinite(video.duration) && video.duration > 0,
  });
  const onPlaying = () => { updateMediaPlayback({ status: "playing" }); publish(); };
  const onPause = () => { if (!video.ended) updateMediaPlayback({ status: "paused" }); };
  const onWaiting = () => updateMediaPlayback({ status: "buffering" });
  const onEnded = () => updateMediaPlayback({ status: "completed" });
  const onError = () => updateMediaPlayback({ status: "failed" });
  playback.dispose = () => {
    video.pause();
    video.removeEventListener("loadedmetadata", publish);
    video.removeEventListener("timeupdate", publish);
    video.removeEventListener("playing", onPlaying);
    video.removeEventListener("pause", onPause);
    video.removeEventListener("waiting", onWaiting);
    video.removeEventListener("ended", onEnded);
    video.removeEventListener("error", onError);
  };
  video.addEventListener("loadedmetadata", publish);
  video.addEventListener("timeupdate", publish);
  video.addEventListener("playing", onPlaying);
  video.addEventListener("pause", onPause);
  video.addEventListener("waiting", onWaiting);
  video.addEventListener("ended", onEnded);
  video.addEventListener("error", onError);
  activeMediaFile = playback;
  void video.play().catch(onError);
  return () => {
    if (activeMediaFile === playback) activeMediaFile = null;
    playback.dispose();
  };
}

function disposeActiveMediaFile(): void {
  const playback = activeMediaFile;
  if (!playback) return;
  activeMediaFile = null;
  playback.dispose();
  updateMediaPlayback({ status: "idle", positionMs: 0, durationMs: 0, seekable: false });
}

function startPcmStream(agentId: string, payload: Record<string, unknown>): void {
  const speechId = stringValue(payload.speech_id);
  const codec = stringValue(payload.codec);
  const sampleRate = numberValue(payload.sample_rate);
  const channels = numberValue(payload.channels);
  const mediaKind = stringValue(payload.media_kind) === "music" ? "music" : "speech";
  if (
    !speechId
    || (codec !== "pcm_s16" && codec !== "pcm_f32")
    || sampleRate <= 0
    || channels <= 0
  ) return;

  if (mediaKind === "music") {
    stopDesktopSpeech();
    disposeActiveMediaFile();
  } else {
    stopSpokenAudio();
    pauseMediaForSpeech();
  }
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
    progressTimer: null,
    mediaKind,
    title: stringValue(payload.title),
    sourceRef: stringValue(payload.source_ref),
    playbackStartTime: 0,
    durationMs: 0,
    inputCompleted: false,
    finish: () => undefined,
  };
  stream.finish = (status) => finishPcmStream(stream, status);
  activeStream = stream;
  if (mediaKind === "music") {
    updateMediaPlayback({
      agentId,
      playbackId: speechId,
      mediaKind,
      title: stream.title || i18n.t("mediaPlayer.untitled"),
      sourceRef: stream.sourceRef,
      sessionId: stringValue(payload.session_id),
      toolCallId: "",
      inlinePlayerVisible: false,
      status: "buffering",
      positionMs: 0,
      durationMs: 0,
      volume: 1,
      seekable: false,
    });
  }
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
  stream.inputCompleted = true;
  stream.durationMs = Math.max(0, numberValue(payload.duration_ms));
  if (stream.mediaKind === "music") {
    updateMediaPlayback({ durationMs: stream.durationMs });
  }
  if (!stream.started) {
    stream.finish("completed");
    return;
  }
  scheduleStreamCompletion(stream);
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
    stream.playbackStartTime = stream.nextStartTime;
    if (stream.mediaKind === "music") {
      updateMediaPlayback({ status: "playing" });
      stream.progressTimer = setInterval(() => publishMediaProgress(stream), 500);
    } else {
      window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_STARTED, {
        detail: { agentId: stream.agentId },
      }));
    }
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
  if (stream.progressTimer) clearInterval(stream.progressTimer);
  for (const source of stream.sources) {
    try { source.stop(); } catch { /* already ended */ }
  }
  stream.sources.clear();
  stream.pending = [];
  stream.pendingBytes = 0;
  void stream.context.close().catch(() => undefined);
  if (stream.mediaKind === "music") {
    const mediaStatus = status === "completed"
      ? "completed"
      : status === "failed" ? "failed" : "stopped";
    updateMediaPlayback({
      status: mediaStatus,
      positionMs: status === "completed"
        ? Math.max(stream.durationMs, currentMediaPosition(stream))
        : currentMediaPosition(stream),
    });
  } else {
    if (stream.started || status === "failed") {
      window.dispatchEvent(new CustomEvent(DESKTOP_SPEECH_FINISHED, {
        detail: { agentId: stream.agentId, status },
      }));
    }
    resumeMediaAfterSpeechIfNeeded();
  }
}

function currentMediaPosition(stream: StreamingPlayback): number {
  if (!stream.started || !stream.playbackStartTime) return 0;
  return Math.max(0, Math.round((stream.context.currentTime - stream.playbackStartTime) * 1000));
}

function publishMediaProgress(stream: StreamingPlayback): void {
  if (activeStream !== stream || stream.mediaKind !== "music") return;
  updateMediaPlayback({
    positionMs: Math.min(
      stream.durationMs || Number.MAX_SAFE_INTEGER,
      currentMediaPosition(stream),
    ),
  });
}

function scheduleStreamCompletion(stream: StreamingPlayback): void {
  if (activeStream !== stream || !stream.inputCompleted || stream.context.state === "suspended") return;
  if (stream.completionTimer) clearTimeout(stream.completionTimer);
  const remainingMs = Math.max(0, (stream.nextStartTime - stream.context.currentTime) * 1000);
  stream.completionTimer = setTimeout(() => stream.finish("completed"), remainingMs + 40);
}

async function controlActiveMedia(action: "play" | "pause" | "stop"): Promise<boolean> {
  const media = activeMediaFile;
  if (media) {
    if (action === "stop") {
      media.stopped = true;
      media.audio.pause();
      try { media.audio.currentTime = 0; } catch { /* metadata not loaded yet */ }
      updateMediaPlayback({ status: "stopped", positionMs: 0 });
      return true;
    }
    if (action === "pause") {
      if (media.audio.paused || media.audio.ended) return false;
      media.audio.pause();
      updateMediaPlayback({ status: "paused" });
      return true;
    }
    if (!media.audio.paused && !media.audio.ended) return false;
    if (media.audio.ended) media.audio.currentTime = 0;
    media.stopped = false;
    await media.audio.play();
    return true;
  }
  if (action === "play" && mediaQueue.length > 0) {
    if (mediaQueueIndex < 0 || mediaQueueIndex >= mediaQueue.length) mediaQueueIndex = 0;
    playMediaQueueItem(mediaQueue[mediaQueueIndex]);
    return true;
  }
  const stream = activeStream;
  if (!stream || stream.mediaKind !== "music") return false;
  if (action === "stop") {
    stream.finish("interrupted");
    return true;
  }
  if (action === "pause") {
    if (stream.context.state !== "running") return false;
    if (stream.completionTimer) {
      clearTimeout(stream.completionTimer);
      stream.completionTimer = null;
    }
    await stream.context.suspend();
    publishMediaProgress(stream);
    updateMediaPlayback({ status: "paused" });
    return true;
  }
  if (stream.context.state === "running") return false;
  await stream.context.resume();
  updateMediaPlayback({ status: "playing" });
  scheduleStreamCompletion(stream);
  return true;
}

function seekActiveMedia(positionMs: number): boolean {
  const media = activeMediaFile;
  if (!media || !Number.isFinite(media.audio.duration) || media.audio.duration <= 0) return false;
  media.audio.currentTime = Math.max(0, Math.min(media.audio.duration, positionMs / 1000));
  updateMediaPlayback({ positionMs: Math.round(media.audio.currentTime * 1000) });
  return true;
}

function setActiveMediaVolume(volume: number): boolean {
  const media = activeMediaFile;
  if (!media) return false;
  media.audio.volume = Math.max(0, Math.min(1, volume));
  updateMediaPlayback({ volume: media.audio.volume });
  return true;
}

export {
  controlMediaPlayback,
  playNextMediaTrack,
  playPreviousMediaTrack,
  seekMediaPlayback,
  setMediaPlaybackVolume,
};

async function playBase64Audio(
  agentId: string,
  dataBase64: string,
  mimeType: string,
  epoch: number,
): Promise<void> {
  stopSpokenAudio();
  pauseMediaForSpeech();
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
      resumeMediaAfterSpeechIfNeeded();
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

function stopSpokenAudio(): void {
  const legacy = activePlayback;
  if (legacy) legacy.finish("interrupted");
  const stream = activeStream;
  if (stream && stream.mediaKind === "speech") stream.finish("interrupted");
}

function pauseMediaForSpeech(): void {
  const media = activeMediaFile;
  if (!media || media.audio.paused || media.audio.ended || media.stopped) return;
  resumeMediaAfterSpeech = true;
  media.audio.pause();
}

function resumeMediaAfterSpeechIfNeeded(): void {
  if (!resumeMediaAfterSpeech) return;
  resumeMediaAfterSpeech = false;
  const media = activeMediaFile;
  if (!media || media.stopped || media.audio.ended || !media.audio.paused) return;
  void media.audio.play().catch(() => updateMediaPlayback({ status: "failed" }));
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
