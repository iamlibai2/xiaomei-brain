import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { bindVideoPlaybackElement } from "../../embodiment";
import {
  clearMediaQueue,
  getMediaPlaybackSnapshot,
  setInlineMediaPlayerVisible,
  subscribeMediaPlayback,
} from "../../media-playback";
import { Icon } from "../ui";
import "./video-player.css";

export function VideoPlayer({
  variant = "floating",
  artifactId = "",
}: {
  variant?: "inline" | "floating";
  artifactId?: string;
}) {
  const { t } = useTranslation();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [inlineInView, setInlineInView] = useState(true);
  const state = useSyncExternalStore(
    subscribeMediaPlayback,
    getMediaPlaybackSnapshot,
    getMediaPlaybackSnapshot,
  );
  const inlineMatches = variant === "inline"
    && Boolean(artifactId)
    && state.artifactId === artifactId;

  useEffect(() => {
    if (!inlineMatches || !state.playbackId) return;
    const node = shellRef.current;
    if (!node) return;
    const playbackId = state.playbackId;
    const observer = new IntersectionObserver(([entry]) => {
      const visible = Boolean(entry?.isIntersecting);
      setInlineInView(visible);
      setInlineMediaPlayerVisible(playbackId, visible);
    }, { threshold: [0, 0.01] });
    observer.observe(node);
    return () => {
      observer.disconnect();
      setInlineMediaPlayerVisible(playbackId, false);
    };
  }, [inlineMatches, state.playbackId]);

  useEffect(() => {
    const video = videoRef.current;
    if (
      !video
      || state.mediaKind !== "video"
      || !state.playbackId
      || !state.mediaUrl
      || (variant === "inline" && !inlineInView)
    ) return;
    const resumeAt = Math.max(0, state.positionMs / 1000);
    const restore = () => {
      if (resumeAt > 0 && Number.isFinite(video.duration)) {
        video.currentTime = Math.min(resumeAt, video.duration);
      }
    };
    video.addEventListener("loadedmetadata", restore, { once: true });
    const dispose = bindVideoPlaybackElement(state.playbackId, video);
    return () => {
      video.removeEventListener("loadedmetadata", restore);
      dispose();
    };
  }, [inlineInView, state.mediaKind, state.mediaUrl, state.playbackId, variant]);

  if (state.mediaKind !== "video" || !state.playbackId || !state.mediaUrl) return null;
  if (variant === "inline" && !inlineMatches) return null;
  if (variant === "floating" && state.inlinePlayerVisible) return null;

  const fullscreen = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await video.requestFullscreen();
  };

  const player = (
    <>
      <video ref={videoRef} src={state.mediaUrl} controls playsInline preload="metadata" />
      <div className="desktop-video-toolbar">
        <strong title={state.title}>{state.title}</strong>
        <button type="button" onClick={() => { void fullscreen(); }} title={t("videoPlayer.fullscreen")}>
          <Icon name="maximize" size={16} />
        </button>
        <button type="button" onClick={() => { void clearMediaQueue(); }} title={t("common.close")}>
          <Icon name="x" size={16} />
        </button>
      </div>
    </>
  );

  if (variant === "inline") {
    return (
      <div ref={shellRef} className="desktop-video-player-slot">
        {inlineInView ? <div className="desktop-video-player inline">{player}</div> : null}
      </div>
    );
  }

  return (
    <div ref={shellRef} className="desktop-video-player floating">
      {player}
    </div>
  );
}
