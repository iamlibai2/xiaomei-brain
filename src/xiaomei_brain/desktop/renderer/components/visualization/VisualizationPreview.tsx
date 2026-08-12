import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "../ui";
import {
  BRIDGE_SOURCE,
  buildVisualizationDocument,
  type VisualizationTheme,
} from "./visualization-shell";
import "./visualization.css";
import {
  clearMediaQueue,
  controlMediaPlayback,
  getMediaPlaybackSnapshot,
  playNextMediaTrack,
  playPreviousMediaTrack,
  playMediaTrack,
  removeMediaTrack,
  seekMediaPlayback,
  setMediaPlaybackVolume,
  subscribeMediaPlayback,
} from "../../media-playback";
import { useCoreStore } from "../../store";
import {
  loadMediaTracks,
  openMediaLibrary,
  setMediaQueueVisibility,
  type MediaTrackReference,
} from "../../media-library";

const MAX_VISUALIZATION_BYTES = 1024 * 1024;
// Keep the wider conversation mode available without exposing two similar
// actions in the preview header. Fullscreen is the clearer primary action.
const SHOW_EXPAND_ACTION = false;

function decodeHtml(dataBase64: string): string {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/^\uFEFF/, "");
}

function currentTheme(): VisualizationTheme {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "dark" || explicit === "light") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function useVisualizationTheme(): VisualizationTheme {
  const [theme, setTheme] = useState<VisualizationTheme>(currentTheme);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setTheme(currentTheme());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);
  return theme;
}

function mediaTrackReferences(value: unknown): MediaTrackReference[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 30).flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
    const item = entry as Record<string, unknown>;
    const sourceType = String(item.sourceType || item.source_type || "");
    const sourceId = String(item.sourceId || item.source_id || "");
    const sessionId = String(item.sessionId || item.session_id || "");
    if (sourceType !== "artifact" || !sourceId || !sessionId) return [];
    return [{ sourceType: "artifact" as const, sourceId, sessionId }];
  });
}

export function VisualizationPreview({
  dataBase64,
  fileName,
  inline = false,
  onExpand,
  onFullscreen,
  onFollowUp,
}: {
  dataBase64: string;
  fileName: string;
  inline?: boolean;
  onExpand?: () => void;
  onFullscreen?: () => void;
  onFollowUp?: (prompt: string) => void;
}) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(inline ? 320 : 640);
  const [error, setError] = useState("");
  const theme = useVisualizationTheme();
  const token = useMemo(() => crypto.randomUUID(), [dataBase64, fileName, theme]);
  const mediaState = useSyncExternalStore(
    subscribeMediaPlayback,
    getMediaPlaybackSnapshot,
    getMediaPlaybackSnapshot,
  );
  const sourceDocument = useMemo(() => {
    if (!dataBase64) return "";
    if (Math.ceil(dataBase64.length * 0.75) > MAX_VISUALIZATION_BYTES) return "";
    return buildVisualizationDocument(decodeHtml(dataBase64), token, theme);
  }, [dataBase64, theme, token]);

  useEffect(() => {
    if (dataBase64 && !sourceDocument) setError(t("visualize.tooLarge"));
    else setError("");
  }, [dataBase64, sourceDocument, t]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (!data || data.source !== BRIDGE_SOURCE || data.token !== token) return;
      if (data.type === "height") {
        const next = Number(data.height);
        if (Number.isFinite(next) && next > 0) {
          setHeight(Math.min(inline ? 680 : 1400, Math.max(inline ? 220 : 480, Math.ceil(next))));
        }
      } else if (data.type === "runtime-error") {
        setError(typeof data.message === "string" ? data.message : t("visualize.runtimeError"));
      } else if (data.type === "follow-up" && typeof data.prompt === "string") {
        onFollowUp?.(data.prompt);
      } else if (data.type === "media-command" && ["play", "pause", "stop"].includes(String(data.action))) {
        void controlMediaPlayback(String(data.action) as "play" | "pause" | "stop");
      } else if (data.type === "media-command" && data.action === "previous") {
        void playPreviousMediaTrack();
      } else if (data.type === "media-command" && data.action === "next") {
        void playNextMediaTrack();
      } else if (data.type === "media-command" && data.action === "library-open") {
        openMediaLibrary("replace");
      } else if (data.type === "media-command" && data.action === "queue-show") {
        setMediaQueueVisibility(true);
      } else if (data.type === "media-command" && data.action === "queue-hide") {
        setMediaQueueVisibility(false);
      } else if (data.type === "media-command" && data.action === "queue-replace") {
        void loadMediaTracks(activeAgentId, mediaTrackReferences(data.tracks), {
          mode: "replace",
          autoplay: data.autoplay !== false,
        });
      } else if (data.type === "media-command" && data.action === "queue-append") {
        void loadMediaTracks(activeAgentId, mediaTrackReferences(data.tracks), {
          mode: "append",
          autoplay: false,
        });
      } else if (data.type === "media-command" && data.action === "queue-select") {
        void playMediaTrack(String(data.trackId || ""));
      } else if (data.type === "media-command" && data.action === "queue-remove") {
        void removeMediaTrack(String(data.trackId || ""));
      } else if (data.type === "media-command" && data.action === "queue-clear") {
        void clearMediaQueue();
      } else if (data.type === "media-command" && data.action === "seek") {
        void seekMediaPlayback(Number(data.positionMs));
      } else if (data.type === "media-command" && data.action === "volume") {
        void setMediaPlaybackVolume(Number(data.volume));
      } else if (data.type === "media-ready") {
        frameRef.current?.contentWindow?.postMessage({
          source: BRIDGE_SOURCE,
          token,
          type: "media-state",
          state: mediaState,
        }, "*");
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [activeAgentId, inline, mediaState, onFollowUp, t, token]);

  useEffect(() => {
    frameRef.current?.contentWindow?.postMessage({
      source: BRIDGE_SOURCE,
      token,
      type: "media-state",
      state: mediaState,
    }, "*");
  }, [mediaState, token]);

  const preview = (
    <section className={`visualization-preview ${inline ? "inline" : "workspace"}`}>
      {inline && (
        <header className="visualization-preview-header">
          <span><Icon name="chart-bar" size={16} />{fileName.replace(/\.visualization\.html$/i, "")}</span>
          <div className="visualization-preview-actions">
            {SHOW_EXPAND_ACTION && onExpand && (
              <button type="button" onClick={onExpand} title={t("visualize.expand")} aria-label={t("visualize.expand")}>
                <Icon name="sidebar-panel-left" size={15} />
              </button>
            )}
            {onFullscreen && (
              <button
                type="button"
                onClick={onFullscreen}
                title={t("visualize.fullscreen")}
                aria-label={t("visualize.fullscreen")}
              >
                <Icon name="maximize" size={15} />
              </button>
            )}
          </div>
        </header>
      )}
      {error && <div className="visualization-preview-error">{error}</div>}
      {sourceDocument && (
        <iframe
          ref={frameRef}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          srcDoc={sourceDocument}
          style={{ height }}
          title={t("visualize.previewTitle", { name: fileName })}
        />
      )}
    </section>
  );

  return preview;
}
