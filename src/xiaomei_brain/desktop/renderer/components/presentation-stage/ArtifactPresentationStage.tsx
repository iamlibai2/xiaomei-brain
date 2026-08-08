import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { artifactPreviewKind } from "../../artifacts/preview-capability";
import type { ArtifactSnapshot } from "../../store";
import { DocxPreview } from "../right-sidebar/DocxPreview";
import { HtmlArtifactPreview } from "../right-sidebar/HtmlArtifactPreview";
import { TextArtifactPreview } from "../right-sidebar/TextArtifactPreview";
import { VisualizationPreview } from "../visualization/VisualizationPreview";
import { PresentationStage, type PresentationStageLayout } from "./PresentationStage";

const PdfPreview = lazy(() => import("../right-sidebar/PdfPreview").then((module) => ({ default: module.PdfPreview })));
const SpreadsheetPreview = lazy(() => import("../right-sidebar/SpreadsheetPreview").then((module) => ({ default: module.SpreadsheetPreview })));

export type PresentationMediaCommand = { type: "play" | "pause"; revision: number };

type LoadedArtifact = {
  artifact: ArtifactSnapshot;
  dataBase64: string;
  mimeType: string;
  error: string;
};

function mediaTypeFor(artifact: ArtifactSnapshot, mimeType: string): "audio" | "video" | "" {
  if (artifact.kind === "audio" || mimeType.startsWith("audio/")) return "audio";
  if (artifact.kind === "video" || mimeType.startsWith("video/")) return "video";
  const normalizedName = artifact.name.toLowerCase().replace(/[》〉】）\)\]」』”’]+$/u, "");
  if (/\.(wav|mp3|flac|m4a|aac|ogg|opus|webm)$/i.test(normalizedName)) return "audio";
  if (/\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(normalizedName)) return "video";
  return "";
}

function playableMimeType(artifact: ArtifactSnapshot, mimeType: string, mediaType: "audio" | "video" | ""): string {
  if (mimeType.startsWith(`${mediaType}/`)) return mimeType;
  const normalizedName = artifact.name.toLowerCase().replace(/[》〉】）\)\]」』”’]+$/u, "");
  const extension = normalizedName.match(/\.([a-z0-9]+)$/i)?.[1] || "";
  const known: Record<string, string> = {
    wav: "audio/wav", mp3: "audio/mpeg", flac: "audio/flac", m4a: "audio/mp4",
    aac: "audio/aac", ogg: "audio/ogg", opus: "audio/ogg", mp4: "video/mp4",
    mov: "video/quicktime", m4v: "video/x-m4v", webm: `${mediaType || "video"}/webm`,
  };
  return known[extension] || mimeType || "application/octet-stream";
}

export function ArtifactPresentationStage({
  agentId,
  artifacts,
  layout,
  activeIndex,
  mediaCommand,
  onClose,
  onActiveIndexChange,
  onFollowUp,
}: {
  agentId: string;
  artifacts: ArtifactSnapshot[];
  layout: PresentationStageLayout;
  activeIndex: number;
  mediaCommand?: PresentationMediaCommand;
  onClose: () => void;
  onActiveIndexChange: (index: number) => void;
  onFollowUp: (prompt: string) => void;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState<Record<string, LoadedArtifact>>({});
  const mediaRefs = useRef<Record<string, HTMLMediaElement | null>>({});
  const visibleArtifacts = useMemo(() => {
    if (layout === "single") return artifacts.length ? [artifacts[Math.min(activeIndex, artifacts.length - 1)]] : [];
    if (layout === "split" || layout === "media_with_details") return artifacts.slice(0, 2);
    return artifacts.slice(0, 6);
  }, [activeIndex, artifacts, layout]);
  const visibleArtifactSignature = visibleArtifacts
    .map((item) => `${item.sessionId}:${item.id}:${item.updatedAt}`)
    .join("|");

  useEffect(() => {
    let cancelled = false;
    void Promise.all(visibleArtifacts.map(async (artifact) => {
      const key = `${artifact.sessionId}:${artifact.id}`;
      const response = await window.gateway.getArtifact({
        agentId,
        sessionId: artifact.sessionId,
        artifactId: artifact.id,
      });
      if (response.error) return [key, { artifact, dataBase64: "", mimeType: artifact.mimeType, error: response.error.message }] as const;
      const raw = response.result?.artifact;
      const value = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
      return [key, {
        artifact,
        dataBase64: typeof value.dataBase64 === "string" ? value.dataBase64 : "",
        mimeType: typeof value.mimeType === "string" ? value.mimeType : artifact.mimeType,
        error: "",
      }] as const;
    })).then((entries) => {
      if (!cancelled) setLoaded(Object.fromEntries(entries));
    }).catch((error) => {
      if (!cancelled) {
        setLoaded(Object.fromEntries(visibleArtifacts.map((artifact) => [
          `${artifact.sessionId}:${artifact.id}`,
          { artifact, dataBase64: "", mimeType: artifact.mimeType, error: String(error) },
        ])));
      }
    });
    return () => { cancelled = true; };
  }, [agentId, visibleArtifactSignature]);

  useEffect(() => {
    if (!mediaCommand) return;
    Object.values(mediaRefs.current).forEach((media) => {
      if (!media) return;
      if (mediaCommand.type === "play") void media.play().catch(() => undefined);
      else media.pause();
    });
  }, [mediaCommand]);

  const title = artifacts[Math.min(activeIndex, Math.max(0, artifacts.length - 1))]?.name || t("stageUi.title");
  const move = (delta: number) => {
    if (!artifacts.length) return;
    onActiveIndexChange((activeIndex + delta + artifacts.length) % artifacts.length);
  };

  return (
    <PresentationStage
      title={title}
      layout={layout}
      itemCount={artifacts.length}
      activeIndex={activeIndex}
      onClose={onClose}
      onPrevious={() => move(-1)}
      onNext={() => move(1)}
    >
      {visibleArtifacts.map((artifact) => {
        const key = `${artifact.sessionId}:${artifact.id}`;
        const item = loaded[key];
        return (
          <div className="presentation-stage-slot" key={key} data-artifact-id={artifact.id}>
            <StageArtifact
              agentId={agentId}
              item={item}
              mediaRef={(node) => { mediaRefs.current[key] = node; }}
              onClose={onClose}
              onFollowUp={onFollowUp}
            />
          </div>
        );
      })}
    </PresentationStage>
  );
}

function StageArtifact({
  agentId,
  item,
  mediaRef,
  onClose,
  onFollowUp,
}: {
  agentId: string;
  item?: LoadedArtifact;
  mediaRef: (node: HTMLMediaElement | null) => void;
  onClose: () => void;
  onFollowUp: (prompt: string) => void;
}) {
  const { t } = useTranslation();
  if (!item) return <div className="presentation-stage-loading">{t("stageUi.loading")}</div>;
  if (item.error) return <div className="presentation-stage-error">{item.error}</div>;
  const { artifact, dataBase64, mimeType } = item;
  if (!dataBase64) return <div className="presentation-stage-error">{t("stageUi.emptyArtifact")}</div>;
  const mediaType = mediaTypeFor(artifact, mimeType);
  const source = `data:${playableMimeType(artifact, mimeType, mediaType)};base64,${dataBase64}`;
  const previewKind = artifactPreviewKind(artifact);
  if (previewKind === "visualization") {
    return <VisualizationPreview dataBase64={dataBase64} fileName={artifact.name} onFollowUp={onFollowUp} />;
  }
  if (previewKind === "image") {
    return <figure className="presentation-stage-image"><img src={source} alt={artifact.name} /></figure>;
  }
  if (previewKind === "docx") {
    return <DocxPreview dataBase64={dataBase64} fileName={artifact.name} />;
  }
  if (previewKind === "pdf") {
    return (
      <Suspense fallback={<div className="presentation-stage-loading">{t("preview.loadingPdf")}</div>}>
        <PdfPreview dataBase64={dataBase64} fileName={artifact.name} />
      </Suspense>
    );
  }
  if (previewKind === "spreadsheet") {
    return (
      <Suspense fallback={<div className="presentation-stage-loading">{t("preview.loadingSheet")}</div>}>
        <SpreadsheetPreview dataBase64={dataBase64} fileName={artifact.name} />
      </Suspense>
    );
  }
  if (previewKind === "text" || previewKind === "markdown") {
    return (
      <TextArtifactPreview
        dataBase64={dataBase64}
        fileName={artifact.name}
        markdown={previewKind === "markdown"}
      />
    );
  }
  if (previewKind === "html") {
    return (
      <HtmlArtifactPreview
        dataBase64={dataBase64}
        fileName={artifact.name}
        onOpenOriginal={() => {
          void window.gateway.openArtifact({
            agentId,
            sessionId: artifact.sessionId,
            artifactId: artifact.id,
          });
        }}
        onBack={onClose}
      />
    );
  }
  if (mediaType === "video") {
    return <video ref={(node) => mediaRef(node)} src={source} controls autoPlay playsInline />;
  }
  if (mediaType === "audio") {
    return (
      <div className="presentation-stage-audio">
        <div className="presentation-stage-audio-cover">♫</div>
        <strong>{artifact.name}</strong>
        <audio ref={(node) => mediaRef(node)} src={source} controls autoPlay />
      </div>
    );
  }
  return (
    <div className="presentation-stage-unsupported">
      <strong>{artifact.name}</strong>
      <span>{t("stageUi.unsupported")}</span>
    </div>
  );
}
