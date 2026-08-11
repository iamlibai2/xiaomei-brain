import { useSyncExternalStore } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import {
  controlMediaPlayback,
  getMediaPlaybackSnapshot,
  seekMediaPlayback,
  setMediaPlaybackVolume,
  subscribeMediaPlayback,
} from "../../media-playback";
import { Icon } from "../ui";
import "./music-player.css";

function formatDuration(value: number): string {
  const seconds = Math.max(0, Math.floor(value / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function MusicPlayer() {
  const { t } = useTranslation();
  const state = useSyncExternalStore(
    subscribeMediaPlayback,
    getMediaPlaybackSnapshot,
    getMediaPlaybackSnapshot,
  );
  if (state.mediaKind !== "music" || !state.playbackId || state.status === "idle") return null;

  const paused = state.status === "paused";
  const active = state.status === "playing";
  const replayable = state.seekable && ["completed", "stopped", "failed"].includes(state.status);
  const controllable = active || paused || state.status === "buffering";
  const progress = state.durationMs > 0
    ? Math.min(100, Math.max(0, state.positionMs / state.durationMs * 100))
    : 0;

  return (
    <aside className={`desktop-music-player status-${state.status}`} aria-label={t("mediaPlayer.title")}>
      <div className="desktop-music-art" aria-hidden="true">
        <span className={active ? "is-playing" : ""}>♫</span>
      </div>
      <div className="desktop-music-main">
        <div className="desktop-music-heading">
          <strong title={state.title}>{state.title || t("mediaPlayer.untitled")}</strong>
          <span>{t(`mediaPlayer.status.${state.status}`)}</span>
        </div>
        <input
          className="desktop-music-progress"
          type="range"
          min={0}
          max={Math.max(1, state.durationMs)}
          step={250}
          value={Math.min(state.positionMs, Math.max(1, state.durationMs))}
          disabled={!state.seekable}
          onChange={(event) => { void seekMediaPlayback(Number(event.currentTarget.value)); }}
          style={{ "--media-progress": `${progress}%` } as CSSProperties}
          aria-label={t("mediaPlayer.seek")}
        />
        <div className="desktop-music-time">
          <span>{formatDuration(state.positionMs)}</span>
          <span>{state.durationMs > 0 ? formatDuration(state.durationMs) : "--:--"}</span>
        </div>
      </div>
      <button
        type="button"
        className="desktop-music-control primary"
        onClick={() => { void controlMediaPlayback(active ? "pause" : "play"); }}
        disabled={!active && !paused && !replayable}
        title={active ? t("mediaPlayer.pause") : t("mediaPlayer.resume")}
        aria-label={active ? t("mediaPlayer.pause") : t("mediaPlayer.resume")}
      >
        <Icon name={active ? "pause" : "play"} size={17} />
      </button>
      <button
        type="button"
        className="desktop-music-control"
        onClick={() => { void controlMediaPlayback("stop"); }}
        disabled={!controllable}
        title={t("mediaPlayer.stop")}
        aria-label={t("mediaPlayer.stop")}
      >
        <Icon name="x" size={16} />
      </button>
      <label className="desktop-music-volume" title={t("mediaPlayer.volume")}>
        <span aria-hidden="true">♪</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={state.volume}
          onChange={(event) => { void setMediaPlaybackVolume(Number(event.currentTarget.value)); }}
          disabled={!state.seekable}
          aria-label={t("mediaPlayer.volume")}
        />
      </label>
    </aside>
  );
}
