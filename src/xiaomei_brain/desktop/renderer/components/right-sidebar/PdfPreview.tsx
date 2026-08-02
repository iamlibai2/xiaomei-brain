import { useEffect, useRef, useState } from "react";
import { GlobalWorkerOptions, TextLayer, getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import type { ArtifactTextSelection } from "../../types";
import { ArtifactAnnotationComposer } from "./ArtifactAnnotationComposer";

GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const CONTEXT_LENGTH = 400;
const MAX_SELECTION_LENGTH = 20_000;
const MAX_PREVIEW_PAGES = 500;

function decodeBase64(dataBase64: string): Uint8Array {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function selectedPdfText(root: HTMLElement): ArtifactTextSelection | null {
  const browserSelection = window.getSelection();
  if (!browserSelection || browserSelection.isCollapsed || browserSelection.rangeCount === 0) return null;
  const range = browserSelection.getRangeAt(0);
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer as Element
    : range.startContainer.parentElement;
  const end = range.endContainer.nodeType === Node.ELEMENT_NODE
    ? range.endContainer as Element
    : range.endContainer.parentElement;
  if (!start || !end || !root.contains(start) || !root.contains(end)) return null;
  const pageElement = start.closest<HTMLElement>("[data-pdf-page]");
  if (!pageElement) return null;
  const selectedText = range.toString().replace(/\s+/g, " ").trim().slice(0, MAX_SELECTION_LENGTH);
  if (!selectedText) return null;
  const pageText = (pageElement.querySelector<HTMLElement>(".textLayer")?.innerText || "")
    .replace(/\s+/g, " ")
    .trim();
  const index = pageText.indexOf(selectedText);
  return {
    kind: "text",
    page: Number(pageElement.dataset.pdfPage) || undefined,
    selectedText,
    contextBefore: index >= 0 ? pageText.slice(Math.max(0, index - CONTEXT_LENGTH), index) : "",
    contextAfter: index >= 0
      ? pageText.slice(index + selectedText.length, index + selectedText.length + CONTEXT_LENGTH)
      : "",
  };
}

function PdfPage({
  document,
  pageNumber,
  scale,
}: {
  document: PDFDocumentProxy;
  pageNumber: number;
  scale: number;
}) {
  const pageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(pageNumber <= 2);
  const [error, setError] = useState("");

  useEffect(() => {
    const element = pageRef.current;
    if (!element || visible) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "800px 0px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const canvas = canvasRef.current;
    const textContainer = textRef.current;
    if (!canvas || !textContainer) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;
    let textLayer: TextLayer | null = null;
    setError("");
    textContainer.replaceChildren();

    void document.getPage(pageNumber).then(async (page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const outputScale = window.devicePixelRatio || 1;
      const context = canvas.getContext("2d", { alpha: false });
      if (!context) throw new Error("无法创建 PDF 画布");
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      pageRef.current?.style.setProperty("width", `${Math.floor(viewport.width)}px`);
      pageRef.current?.style.setProperty("min-height", `${Math.floor(viewport.height)}px`);
      textContainer.style.setProperty("--scale-factor", String(viewport.scale));
      textContainer.style.setProperty("--user-unit", "1");
      textContainer.style.setProperty("--total-scale-factor", String(viewport.scale));
      renderTask = page.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      });
      const textContent = await page.getTextContent();
      textLayer = new TextLayer({ textContentSource: textContent, container: textContainer, viewport });
      await Promise.all([renderTask.promise, textLayer.render()]);
    }).catch((reason) => {
      if (!cancelled && reason?.name !== "RenderingCancelledException") {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    });

    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
      textContainer.replaceChildren();
    };
  }, [document, pageNumber, scale, visible]);

  return (
    <article ref={pageRef} className="pdf-preview-page" data-pdf-page={pageNumber}>
      {!visible && <div className="pdf-preview-page-placeholder">第 {pageNumber} 页</div>}
      <canvas ref={canvasRef} />
      <div ref={textRef} className="textLayer" />
      {error && <div className="pdf-preview-page-error">第 {pageNumber} 页渲染失败：{error}</div>}
      <span className="pdf-preview-page-number">{pageNumber}</span>
    </article>
  );
}

export function PdfPreview({
  dataBase64,
  fileName,
  onAnnotate,
}: {
  dataBase64: string;
  fileName: string;
  onAnnotate: (selection: ArtifactTextSelection, instruction: string) => void;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scale, setScale] = useState(1);
  const [selection, setSelection] = useState<ArtifactTextSelection | null>(null);

  useEffect(() => {
    let cancelled = false;
    const assetBase = new URL(__PDFJS_ASSET_BASE__, window.location.href);
    const task = getDocument({
      data: decodeBase64(dataBase64),
      cMapUrl: new URL("cmaps/", assetBase).href,
      cMapPacked: true,
      standardFontDataUrl: new URL("standard_fonts/", assetBase).href,
      wasmUrl: new URL("wasm/", assetBase).href,
      iccUrl: new URL("iccs/", assetBase).href,
      useSystemFonts: true,
    });
    setLoading(true);
    setError("");
    setDocument(null);
    setSelection(null);
    selectionRangeRef.current = null;
    void task.promise.then((value) => {
      if (!cancelled) {
        setDocument(value);
        setLoading(false);
      }
    }).catch((reason) => {
      if (!cancelled) {
        setLoading(false);
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    });
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [dataBase64, fileName]);

  const pageCount = Math.min(document?.numPages || 0, MAX_PREVIEW_PAGES);

  return (
    <div className="pdf-preview-shell">
      <div className="artifact-preview-toolbar">
        <div>
          <strong>PDF 预览</strong>
          <span>{document ? `${document.numPages} 页` : fileName}</span>
        </div>
        <div className="pdf-preview-zoom">
          <button type="button" onClick={() => setScale((value) => Math.max(.6, value - .15))}>−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" onClick={() => setScale((value) => Math.min(2, value + .15))}>＋</button>
        </div>
      </div>
      <div
        ref={viewportRef}
        className="pdf-preview-viewport"
        onMouseUp={() => {
          const root = viewportRef.current;
          if (!root) return;
          const browserSelection = window.getSelection();
          const value = selectedPdfText(root);
          if (value && browserSelection?.rangeCount) selectionRangeRef.current = browserSelection.getRangeAt(0).cloneRange();
          setSelection(value);
        }}
      >
        {loading && <div className="artifact-preview-state">正在读取 PDF…</div>}
        {error && <div className="artifact-preview-state error">预览失败：{error}</div>}
        {document && Array.from({ length: pageCount }, (_, index) => (
          <PdfPage key={index + 1} document={document} pageNumber={index + 1} scale={scale} />
        ))}
        {document && document.numPages > MAX_PREVIEW_PAGES && (
          <div className="artifact-preview-limit">文档超过 {MAX_PREVIEW_PAGES} 页，仅预览前 {MAX_PREVIEW_PAGES} 页。</div>
        )}
      </div>
      {selection && (
        <ArtifactAnnotationComposer
          excerpt={selection.selectedText}
          location={selection.page ? `第 ${selection.page} 页` : "已选择文字"}
          placeholder="例如：把这一段改得更简洁"
          getAnchorRect={() => selectionRangeRef.current?.getBoundingClientRect() || null}
          onCancel={() => {
            setSelection(null);
            selectionRangeRef.current = null;
          }}
          onSubmit={(instruction) => {
            onAnnotate(selection, instruction);
            setSelection(null);
            selectionRangeRef.current = null;
            window.getSelection()?.removeAllRanges();
          }}
        />
      )}
    </div>
  );
}
