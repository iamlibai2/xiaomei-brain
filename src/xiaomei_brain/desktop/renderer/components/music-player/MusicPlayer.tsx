import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import {
  controlMediaPlayback,
  clearMediaQueue,
  getMediaPlaybackSnapshot,
  playNextMediaTrack,
  playPreviousMediaTrack,
  playMediaTrack,
  removeMediaTrack,
  seekMediaPlayback,
  setInlineMediaPlayerVisible,
  setMediaPlaybackVolume,
  subscribeMediaPlayback,
} from "../../media-playback";
import { Icon } from "../ui";
import {
  MEDIA_QUEUE_VISIBILITY_EVENT,
  openMediaLibrary,
} from "../../media-library";
import {
  isMusicPlayerSkin,
  MUSIC_PLAYER_SKINS,
  type MusicPlayerSkinId,
} from "./music-player-skins";
import "./music-player.css";

function formatDuration(value: number): string {
  const seconds = Math.max(0, Math.floor(value / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function MusicPlayer({
  variant = "floating",
  toolCallId = "",
}: {
  variant?: "floating" | "inline";
  toolCallId?: string;
}) {
  const { t } = useTranslation();
  const [queueOpen, setQueueOpen] = useState(false);
  const [skinOpen, setSkinOpen] = useState(false);
  const [volumeOpen, setVolumeOpen] = useState(false);
  const [skin, setSkin] = useState<MusicPlayerSkinId>("default");
  const playerRef = useRef<HTMLElement | null>(null);
  const state = useSyncExternalStore(
    subscribeMediaPlayback,
    getMediaPlaybackSnapshot,
    getMediaPlaybackSnapshot,
  );
  const paused = state.status === "paused";
  const active = state.status === "playing";
  const replayable = ["completed", "stopped", "failed"].includes(state.status)
    && (state.seekable || state.queue.length > 0);
  const progress = state.durationMs > 0
    ? Math.min(100, Math.max(0, state.positionMs / state.durationMs * 100))
    : 0;
  const hasPrevious = state.currentIndex > 0;
  const hasNext = state.currentIndex >= 0 && state.currentIndex < state.queue.length - 1;
  const inlineMatches = variant === "inline"
    && Boolean(toolCallId)
    && state.toolCallId === toolCallId;

  useEffect(() => {
    if (state.queue.length === 0) setQueueOpen(false);
  }, [state.queue.length]);

  useEffect(() => {
    let active = true;
    void window.desktop.getSettings().then((settings) => {
      if (active && isMusicPlayerSkin(settings.musicPlayerSkin)) {
        setSkin(settings.musicPlayerSkin);
      }
    });
    const receive = (event: Event) => {
      const settings = (event as CustomEvent<import("../../types").DesktopSettings>).detail;
      if (isMusicPlayerSkin(settings?.musicPlayerSkin)) setSkin(settings.musicPlayerSkin);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", receive);
    return () => {
      active = false;
      window.removeEventListener("xiaomei:desktop-settings-changed", receive);
    };
  }, []);

  useEffect(() => {
    if (!skinOpen && !queueOpen && !volumeOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!playerRef.current?.contains(event.target as Node)) {
        setSkinOpen(false);
        setQueueOpen(false);
        setVolumeOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSkinOpen(false);
      setQueueOpen(false);
      setVolumeOpen(false);
    };
    window.addEventListener("pointerdown", closeOnOutsideClick);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsideClick);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [queueOpen, skinOpen, volumeOpen]);

  useEffect(() => {
    const receive = (event: Event) => {
      const detail = (event as CustomEvent<{ visible?: boolean }>).detail;
      setQueueOpen(detail?.visible !== false);
    };
    window.addEventListener(MEDIA_QUEUE_VISIBILITY_EVENT, receive);
    return () => window.removeEventListener(MEDIA_QUEUE_VISIBILITY_EVENT, receive);
  }, []);

  async function selectSkin(nextSkin: MusicPlayerSkinId) {
    setSkin(nextSkin);
    setSkinOpen(false);
    const result = await window.desktop.updateSettings({ musicPlayerSkin: nextSkin });
    if (!result.ok || !result.settings) {
      const current = await window.desktop.getSettings();
      setSkin(isMusicPlayerSkin(current.musicPlayerSkin) ? current.musicPlayerSkin : "default");
      return;
    }
    window.dispatchEvent(new CustomEvent(
      "xiaomei:desktop-settings-changed",
      { detail: result.settings },
    ));
  }

  useEffect(() => {
    if (!inlineMatches || !state.playbackId) return;
    const node = playerRef.current;
    if (!node) return;
    const playbackId = state.playbackId;
    const publishVisibility = (visible: boolean) => {
      setInlineMediaPlayerVisible(playbackId, visible);
    };
    if (typeof IntersectionObserver === "undefined") {
      publishVisibility(true);
      return () => publishVisibility(false);
    }
    const observer = new IntersectionObserver(([entry]) => {
      publishVisibility(Boolean(entry?.isIntersecting));
    }, { threshold: [0, 0.01] });
    observer.observe(node);
    return () => {
      observer.disconnect();
      publishVisibility(false);
    };
  }, [inlineMatches, state.playbackId]);

  if (state.mediaKind !== "music" || !state.playbackId || state.status === "idle") return null;
  if (variant === "inline" && !inlineMatches) return null;
  if (variant === "floating" && state.inlinePlayerVisible) return null;

  return (
    <aside
      ref={playerRef}
      className={`desktop-music-player ${variant} status-${state.status} skin-${skin}`}
      aria-label={t("mediaPlayer.title")}
    >
      {skinOpen && (
        <div className="desktop-music-skin-menu" role="dialog" aria-label={t("mediaPlayer.skin")}>
          <header>{t("mediaPlayer.chooseSkin")}</header>
          {MUSIC_PLAYER_SKINS.map((definition) => (
            <button
              key={definition.id}
              type="button"
              className={skin === definition.id ? "active" : ""}
              onClick={() => { void selectSkin(definition.id); }}
            >
              <span className={`desktop-music-skin-preview skin-${definition.id}`} aria-hidden="true">
                <i />
              </span>
              <span>
                <strong>{t(definition.labelKey)}</strong>
                <small>{t(definition.descriptionKey)}</small>
              </span>
            </button>
          ))}
        </div>
      )}
      {queueOpen && state.queue.length > 0 && (
        <div className="desktop-music-queue" role="dialog" aria-label={t("mediaPlayer.queue")}>
          <header>
            <strong>{t("mediaPlayer.queue")}</strong>
            <button type="button" onClick={() => { void clearMediaQueue(); }}>
              {t("mediaPlayer.clear")}
            </button>
          </header>
          <div className="desktop-music-queue-list">
            {state.queue.map((track, index) => (
              <div
                key={track.id}
                className={`desktop-music-queue-item ${index === state.currentIndex ? "current" : ""}`}
              >
                <button type="button" className="desktop-music-queue-play" onClick={() => { void playMediaTrack(track.id); }}>
                  <span>{index === state.currentIndex && active ? "♫" : index + 1}</span>
                  <strong title={track.title}>{track.title}</strong>
                </button>
                <button
                  type="button"
                  className="desktop-music-queue-remove"
                  onClick={() => { void removeMediaTrack(track.id); }}
                  title={t("mediaPlayer.remove")}
                  aria-label={t("mediaPlayer.remove")}
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
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
        className="desktop-music-control library"
        onClick={() => openMediaLibrary("replace")}
        title={t("mediaLibrary.open")}
        aria-label={t("mediaLibrary.open")}
      >
        <Icon name="folder" size={16} />
      </button>
      <button
        type="button"
        className={`desktop-music-skin-trigger ${skinOpen ? "active" : ""}`}
        onClick={() => {
          setQueueOpen(false);
          setVolumeOpen(false);
          setSkinOpen((value) => !value);
        }}
        title={t("mediaPlayer.skin")}
        aria-label={t("mediaPlayer.skin")}
      >
        <Icon name="sparkles" size={15} />
      </button>
      <button
        type="button"
        className="desktop-music-control"
        onClick={() => { void playPreviousMediaTrack(); }}
        disabled={!hasPrevious}
        title={t("mediaPlayer.previous")}
        aria-label={t("mediaPlayer.previous")}
      >
        <Icon name={skin === "visualization" ? "skip-back" : "chevron-left"} size={17} />
      </button>
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
        onClick={() => { void playNextMediaTrack(); }}
        disabled={!hasNext}
        title={t("mediaPlayer.next")}
        aria-label={t("mediaPlayer.next")}
      >
        <Icon name={skin === "visualization" ? "skip-forward" : "chevron-right"} size={17} />
      </button>
      <div className="desktop-music-volume">
        <button
          type="button"
          className={volumeOpen ? "active" : ""}
          onClick={() => {
            setQueueOpen(false);
            setSkinOpen(false);
            setVolumeOpen((value) => !value);
          }}
          disabled={!state.seekable}
          title={t("mediaPlayer.volume")}
          aria-label={t("mediaPlayer.volume")}
        >
        <span aria-hidden="true">♪</span>
          <Icon name={state.volume <= 0 ? "volume-muted" : "volume"} size={16} />
        </button>
        {volumeOpen && (
          <div className="desktop-music-volume-popover">
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
            <span>{Math.round(state.volume * 100)}%</span>
          </div>
        )}
      </div>
      {state.queue.length > 0 && (
        <button
          type="button"
          className={`desktop-music-queue-count ${queueOpen ? "active" : ""}`}
          onClick={() => {
            setSkinOpen(false);
            setVolumeOpen(false);
            setQueueOpen((value) => !value);
          }}
          title={t("mediaPlayer.queue")}
          aria-label={t("mediaPlayer.queue")}
        >
          {state.currentIndex + 1}/{state.queue.length}
        </button>
      )}
      <button
        type="button"
        className="desktop-music-close"
        onClick={() => { void clearMediaQueue(); }}
        title={t("common.close")}
        aria-label={t("common.close")}
      >
        <Icon name="x" size={15} />
      </button>
    </aside>
  );
}
