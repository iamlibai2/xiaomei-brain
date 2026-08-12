export type MediaPlaybackStatus =
  | "idle"
  | "buffering"
  | "playing"
  | "paused"
  | "completed"
  | "stopped"
  | "failed";

export type MusicTrackSummary = {
  id: string;
  title: string;
  agentId: string;
  personId: string;
  sessionId: string;
  sourceRef: string;
  artifactId?: string;
};

export type MediaPlaybackState = {
  agentId: string;
  playbackId: string;
  mediaKind: "music" | "speech";
  title: string;
  sourceRef: string;
  sessionId: string;
  toolCallId: string;
  status: MediaPlaybackStatus;
  positionMs: number;
  durationMs: number;
  volume: number;
  seekable: boolean;
  queue: readonly MusicTrackSummary[];
  currentIndex: number;
  inlinePlayerVisible: boolean;
};

const EMPTY_STATE: MediaPlaybackState = Object.freeze({
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
  volume: 1,
  seekable: false,
  queue: Object.freeze([]),
  currentIndex: -1,
  inlinePlayerVisible: false,
});

let snapshot: MediaPlaybackState = EMPTY_STATE;
const listeners = new Set<() => void>();
type MediaPlaybackController = {
  control(action: "play" | "pause" | "stop"): boolean | Promise<boolean>;
  seek(positionMs: number): boolean | Promise<boolean>;
  setVolume(volume: number): boolean | Promise<boolean>;
  previous(): boolean | Promise<boolean>;
  next(): boolean | Promise<boolean>;
  playTrack(trackId: string): boolean | Promise<boolean>;
  removeTrack(trackId: string): boolean | Promise<boolean>;
  clearQueue(): boolean | Promise<boolean>;
};

let controller: MediaPlaybackController | null = null;

export function getMediaPlaybackSnapshot(): MediaPlaybackState {
  return snapshot;
}

export function subscribeMediaPlayback(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function updateMediaPlayback(next: Partial<MediaPlaybackState>): void {
  const updated = { ...snapshot, ...next };
  if (
    updated.agentId === snapshot.agentId
    && updated.playbackId === snapshot.playbackId
    && updated.mediaKind === snapshot.mediaKind
    && updated.title === snapshot.title
    && updated.sourceRef === snapshot.sourceRef
    && updated.sessionId === snapshot.sessionId
    && updated.toolCallId === snapshot.toolCallId
    && updated.status === snapshot.status
    && updated.positionMs === snapshot.positionMs
    && updated.durationMs === snapshot.durationMs
    && updated.volume === snapshot.volume
    && updated.seekable === snapshot.seekable
    && updated.queue === snapshot.queue
    && updated.currentIndex === snapshot.currentIndex
    && updated.inlinePlayerVisible === snapshot.inlinePlayerVisible
  ) return;
  snapshot = Object.freeze(updated);
  listeners.forEach((listener) => listener());
}

export function registerMediaPlaybackController(
  value: MediaPlaybackController | null,
): void {
  controller = value;
}

export async function controlMediaPlayback(action: "play" | "pause" | "stop"): Promise<boolean> {
  return Boolean(await controller?.control(action));
}

export async function seekMediaPlayback(positionMs: number): Promise<boolean> {
  return Boolean(await controller?.seek(positionMs));
}

export async function setMediaPlaybackVolume(volume: number): Promise<boolean> {
  return Boolean(await controller?.setVolume(volume));
}

export async function playPreviousMediaTrack(): Promise<boolean> {
  return Boolean(await controller?.previous());
}

export async function playNextMediaTrack(): Promise<boolean> {
  return Boolean(await controller?.next());
}

export async function playMediaTrack(trackId: string): Promise<boolean> {
  return Boolean(await controller?.playTrack(trackId));
}

export async function removeMediaTrack(trackId: string): Promise<boolean> {
  return Boolean(await controller?.removeTrack(trackId));
}

export async function clearMediaQueue(): Promise<boolean> {
  return Boolean(await controller?.clearQueue());
}

export function setInlineMediaPlayerVisible(
  playbackId: string,
  visible: boolean,
): void {
  if (!playbackId || snapshot.playbackId !== playbackId) return;
  updateMediaPlayback({ inlinePlayerVisible: visible });
}
