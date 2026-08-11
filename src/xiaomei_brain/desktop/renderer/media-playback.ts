export type MediaPlaybackStatus =
  | "idle"
  | "buffering"
  | "playing"
  | "paused"
  | "completed"
  | "stopped"
  | "failed";

export type MediaPlaybackState = {
  agentId: string;
  playbackId: string;
  mediaKind: "music" | "speech";
  title: string;
  sourceRef: string;
  status: MediaPlaybackStatus;
  positionMs: number;
  durationMs: number;
  volume: number;
  seekable: boolean;
};

const EMPTY_STATE: MediaPlaybackState = Object.freeze({
  agentId: "",
  playbackId: "",
  mediaKind: "speech",
  title: "",
  sourceRef: "",
  status: "idle",
  positionMs: 0,
  durationMs: 0,
  volume: 1,
  seekable: false,
});

let snapshot: MediaPlaybackState = EMPTY_STATE;
const listeners = new Set<() => void>();
type MediaPlaybackController = {
  control(action: "play" | "pause" | "stop"): boolean | Promise<boolean>;
  seek(positionMs: number): boolean | Promise<boolean>;
  setVolume(volume: number): boolean | Promise<boolean>;
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
    && updated.status === snapshot.status
    && updated.positionMs === snapshot.positionMs
    && updated.durationMs === snapshot.durationMs
    && updated.volume === snapshot.volume
    && updated.seekable === snapshot.seekable
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
