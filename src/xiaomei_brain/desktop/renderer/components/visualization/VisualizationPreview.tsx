import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "../ui";
import {
  BRIDGE_SOURCE,
  buildVisualizationDocument,
  type VisualizationTheme,
} from "./visualization-shell";
import "./visualization.css";

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

export function VisualizationPreview({
  dataBase64,
  fileName,
  inline = false,
  fullscreen = false,
  onExpand,
  onFullscreen,
  onFollowUp,
}: {
  dataBase64: string;
  fileName: string;
  inline?: boolean;
  fullscreen?: boolean;
  onExpand?: () => void;
  onFullscreen?: () => void;
  onFollowUp?: (prompt: string) => void;
}) {
  const { t } = useTranslation();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(inline ? 320 : 640);
  const [error, setError] = useState("");
  const theme = useVisualizationTheme();
  const token = useMemo(() => crypto.randomUUID(), [dataBase64, fileName, theme]);
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
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [inline, onFollowUp, t, token]);

  return (
    <section className={`visualization-preview ${inline ? "inline" : "workspace"} ${fullscreen ? "fullscreen" : ""}`}>
      {inline && (
        <header className="visualization-preview-header">
          <span><Icon name="chart-bar" size={16} />{fileName.replace(/\.visualization\.html$/i, "")}</span>
          <div className="visualization-preview-actions">
            {SHOW_EXPAND_ACTION && onExpand && !fullscreen && (
              <button type="button" onClick={onExpand} title={t("visualize.expand")} aria-label={t("visualize.expand")}>
                <Icon name="sidebar-panel-left" size={15} />
              </button>
            )}
            {onFullscreen && (
              <button
                type="button"
                onClick={onFullscreen}
                title={t(fullscreen ? "visualize.exitFullscreen" : "visualize.fullscreen")}
                aria-label={t(fullscreen ? "visualize.exitFullscreen" : "visualize.fullscreen")}
              >
                <Icon name={fullscreen ? "minimize" : "maximize"} size={15} />
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
}
