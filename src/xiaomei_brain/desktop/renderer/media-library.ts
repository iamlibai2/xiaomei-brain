import { enqueueMediaFilePlayback } from "./embodiment";
import {
  clearMediaQueue,
  getMediaPlaybackSnapshot,
  playMediaTrack,
  removeMediaTrack,
} from "./media-playback";

export type MediaTrackReference = {
  sourceType: "artifact";
  sourceId: string;
  sessionId: string;
};

export type MediaLibraryTrack = MediaTrackReference & {
  title: string;
  mimeType: string;
  size: number;
  updatedAt: number;
};

export const MEDIA_LIBRARY_OPEN_EVENT = "xiaomei:media-library-open";
export const MEDIA_PLAYER_OPEN_EVENT = "xiaomei:media-player-open";
export const MEDIA_QUEUE_VISIBILITY_EVENT = "xiaomei:media-queue-visibility";

export function openMusicPlayer(): void {
  window.dispatchEvent(new Event(MEDIA_PLAYER_OPEN_EVENT));
}

export function openMediaLibrary(mode: "replace" | "append" = "replace"): void {
  window.dispatchEvent(new CustomEvent(MEDIA_LIBRARY_OPEN_EVENT, { detail: { mode } }));
}

export function setMediaQueueVisibility(visible: boolean): void {
  window.dispatchEvent(new CustomEvent(MEDIA_QUEUE_VISIBILITY_EVENT, { detail: { visible } }));
}

export async function listMediaLibrary(agentId: string): Promise<MediaLibraryTrack[]> {
  if (!agentId) return [];
  const response = await window.gateway.listMediaLibrary({ agentId, limit: 200, offset: 0 });
  if (response.error) throw new Error(response.error.message);
  const rows = Array.isArray(response.result?.tracks) ? response.result.tracks : [];
  return rows.flatMap((value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const item = value as Record<string, unknown>;
    if (item.source_type !== "artifact") return [];
    const sourceId = String(item.source_id || "");
    const sessionId = String(item.session_id || "");
    if (!sourceId || !sessionId) return [];
    return [{
      sourceType: "artifact" as const,
      sourceId,
      sessionId,
      title: String(item.title || ""),
      mimeType: String(item.mime_type || ""),
      size: Math.max(0, Number(item.size) || 0),
      updatedAt: Math.max(0, Number(item.updated_at) || 0),
    }];
  });
}

export async function loadMediaTracks(
  agentId: string,
  references: MediaTrackReference[],
  options: { mode?: "replace" | "append"; autoplay?: boolean } = {},
): Promise<number> {
  const unique = [...new Map(references
    .filter((item) => item.sourceType === "artifact" && item.sourceId && item.sessionId)
    .map((item) => [`${item.sourceType}\u0000${item.sessionId}\u0000${item.sourceId}`, item])).values()]
    .slice(0, 30);
  if (!agentId || !unique.length) return 0;
  if ((options.mode || "replace") === "replace") await clearMediaQueue();
  const append = (options.mode || "replace") === "append";
  const queueOffset = append ? getMediaPlaybackSnapshot().queue.length : 0;
  const playlistId = crypto.randomUUID();
  let loaded = 0;
  for (const [index, reference] of unique.entries()) {
    const response = await window.gateway.authorizeMediaTrack({ agentId, ...reference });
    if (response.error || !response.result) continue;
    enqueueMediaFilePlayback(agentId, {
      ...response.result,
      source_ref: `${reference.sourceType}:${reference.sourceId}`,
      playlist_id: playlistId,
      playlist_index: queueOffset + index,
      playlist_size: unique.length,
      autoplay: Boolean(options.autoplay !== false && index === 0),
      append_to_queue: append,
      tool_call_id: "",
    });
    loaded += 1;
  }
  return loaded;
}

export async function selectMediaTrack(trackId: string): Promise<boolean> {
  return playMediaTrack(trackId);
}

export async function removeMediaQueueTrack(trackId: string): Promise<boolean> {
  return removeMediaTrack(trackId);
}
