import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { ArtifactSnapshot } from "../../store";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import { DocxPreview } from "../right-sidebar/DocxPreview";
import { TextArtifactPreview } from "../right-sidebar/TextArtifactPreview";
import { HtmlArtifactPreview } from "../right-sidebar/HtmlArtifactPreview";
import { artifactPreviewKind } from "../../artifacts/preview-capability";

const PdfPreview = lazy(() => import("../right-sidebar/PdfPreview").then((module) => ({ default: module.PdfPreview })));
const SpreadsheetPreview = lazy(() => import("../right-sidebar/SpreadsheetPreview").then((module) => ({ default: module.SpreadsheetPreview })));

const MAX_INLINE_BYTES = 20 * 1024 * 1024;
const MIN_WIDTH = 440;
const MAX_WIDTH = 1080;

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function ArtifactWorkspace({
  agentId,
  artifactKey,
  onClose,
}: {
  agentId: string;
  artifactKey: string;
  onClose: () => void;
}) {
  // Keep the external-store snapshot referentially stable while this Agent has
  // no artifacts. Returning `[]` from the selector creates a new snapshot on
  // every read and makes React's useSyncExternalStore rerender forever.
  const artifacts = useCoreStore((state) => state.artifactsByAgent[agentId]);
  const sendMessage = useCoreStore((state) => state.sendMessage);
  const artifact = useMemo(() => artifacts?.find((item) => (
    `${item.sessionId}:${item.id}` === artifactKey
  )) || null, [artifactKey, artifacts]);
  const [dataBase64, setDataBase64] = useState("");
  const [mimeType, setMimeType] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [width, setWidth] = useState(() => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(window.innerWidth * .56))));
  const resizeRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const kind = artifact ? artifactPreviewKind(artifact) : null;

  useEffect(() => {
    setDataBase64("");
    setMimeType("");
    setError("");
    if (!artifact) return;
    if (artifact.size > MAX_INLINE_BYTES) {
      setError("文件超过 20 MB，请使用外部应用打开");
      return;
    }
    if (!kind) return;
    let cancelled = false;
    setLoading(true);
    void window.gateway.getArtifact({
      agentId,
      sessionId: artifact.sessionId,
      artifactId: artifact.id,
    }).then((response) => {
      if (cancelled) return;
      if (response.error) throw new Error(response.error.message);
      const raw = response.result?.artifact;
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Agent 没有返回可预览的文件内容");
      const value = raw as Record<string, unknown>;
      setDataBase64(typeof value.dataBase64 === "string" ? value.dataBase64 : "");
      setMimeType(typeof value.mimeType === "string" ? value.mimeType : artifact.mimeType);
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [agentId, artifact?.id, artifact?.mimeType, artifact?.sessionId, artifact?.size, artifact?.updatedAt, kind]);

  useEffect(() => {
    const move = (event: MouseEvent) => {
      const state = resizeRef.current;
      if (!state) return;
      const available = Math.max(MIN_WIDTH, window.innerWidth - 360);
      setWidth(Math.min(MAX_WIDTH, available, Math.max(MIN_WIDTH, state.startWidth + state.startX - event.clientX)));
    };
    const stop = () => {
      resizeRef.current = null;
      document.body.classList.remove("is-resizing-artifact-workspace");
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
      document.body.classList.remove("is-resizing-artifact-workspace");
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const openOriginal = async () => {
    if (!artifact || opening) return;
    setOpening(true);
    setError("");
    try {
      const result = await window.gateway.openArtifact({
        agentId,
        sessionId: artifact.sessionId,
        artifactId: artifact.id,
      });
      if (!result.ok) setError(result.error || "无法打开文件");
    } finally {
      setOpening(false);
    }
  };

  const annotate = artifact ? (selection: import("../../types").ArtifactSelection, instruction: string) => {
    sendMessage(instruction, [{
      artifactId: artifact.id,
      sessionId: artifact.sessionId,
      selection,
      name: artifact.name,
      mimeType: artifact.mimeType,
      size: artifact.size,
    }]);
  } : undefined;

  return (
    <aside
      className={`artifact-workspace ${maximized ? "maximized" : ""}`}
      style={maximized ? undefined : { width }}
      aria-label="产物工作区"
    >
      {!maximized && (
        <button
          type="button"
          className="artifact-workspace-resizer"
          aria-label="调整产物工作区宽度"
          onMouseDown={(event) => {
            event.preventDefault();
            resizeRef.current = { startX: event.clientX, startWidth: width };
            document.body.classList.add("is-resizing-artifact-workspace");
          }}
        />
      )}
      <header className="artifact-workspace-header">
        <div className="artifact-workspace-title">
          <span className={`artifact-kind-icon ${artifact?.kind || "file"}`}>
            <Icon name={artifact?.kind === "image" ? "image" : "file-text"} size={17} />
          </span>
          <div>
            <strong>{artifact?.name || "产物不存在"}</strong>
            {artifact && <small>{formatBytes(artifact.size)} · 更新于 {new Date(artifact.updatedAt * 1000).toLocaleString()}</small>}
          </div>
        </div>
        <div className="artifact-workspace-actions">
          <button type="button" onClick={() => void openOriginal()} disabled={!artifact || opening} title="使用外部应用打开">
            <Icon name="external-link" size={16} />
            <span>{opening ? "打开中…" : "打开原文件"}</span>
          </button>
          <button type="button" onClick={() => setMaximized((value) => !value)} title={maximized ? "退出全屏预览" : "最大化预览"}>
            <Icon name="maximize" size={16} />
          </button>
          <button type="button" onClick={onClose} title="关闭产物工作区" aria-label="关闭产物工作区">
            <Icon name="x" size={17} />
          </button>
        </div>
      </header>
      <div className="artifact-workspace-body">
        {loading && <div className="artifact-preview-state">正在读取文件…</div>}
        {error && <div className="artifact-workspace-error">{error}</div>}
        {!artifact && <div className="artifact-workspace-empty">找不到这个产物，它可能已被移除。</div>}
        {artifact && !kind && (
          <div className="artifact-workspace-empty">
            <Icon name="file-text" size={34} />
            <strong>此文件暂不支持内嵌预览</strong>
            <span>可以使用系统中的默认应用打开。</span>
          </div>
        )}
        {artifact && kind === "image" && dataBase64 && (
          <div className="artifact-workspace-image">
            <img src={`data:${mimeType || artifact.mimeType};base64,${dataBase64}`} alt={artifact.name} />
          </div>
        )}
        {artifact && kind === "docx" && dataBase64 && annotate && (
          <DocxPreview dataBase64={dataBase64} fileName={artifact.name} onAnnotate={annotate} />
        )}
        {artifact && kind === "pdf" && dataBase64 && annotate && (
          <Suspense fallback={<div className="artifact-preview-state">正在加载 PDF 预览器…</div>}>
            <PdfPreview dataBase64={dataBase64} fileName={artifact.name} onAnnotate={annotate} />
          </Suspense>
        )}
        {artifact && kind === "spreadsheet" && dataBase64 && annotate && (
          <Suspense fallback={<div className="artifact-preview-state">正在加载表格预览器…</div>}>
            <SpreadsheetPreview dataBase64={dataBase64} fileName={artifact.name} onAnnotate={annotate} />
          </Suspense>
        )}
        {artifact && (kind === "text" || kind === "markdown") && dataBase64 && annotate && (
          <TextArtifactPreview
            dataBase64={dataBase64}
            fileName={artifact.name}
            markdown={kind === "markdown"}
            onAnnotate={annotate}
          />
        )}
        {artifact && kind === "html" && dataBase64 && annotate && (
          <HtmlArtifactPreview
            dataBase64={dataBase64}
            fileName={artifact.name}
            onAnnotate={annotate}
            onOpenOriginal={() => void openOriginal()}
            onBack={onClose}
            opening={opening}
          />
        )}
      </div>
    </aside>
  );
}
