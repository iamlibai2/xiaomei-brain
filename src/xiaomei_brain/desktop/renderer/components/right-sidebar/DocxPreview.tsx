import { useEffect, useRef, useState } from "react";
import type { ArtifactTextSelection } from "../../types";
import { ArtifactAnnotationComposer } from "./ArtifactAnnotationComposer";

const MAX_SELECTION_LENGTH = 20_000;
const CONTEXT_LENGTH = 400;

function decodeBase64(dataBase64: string): ArrayBuffer {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function selectionInside(root: HTMLElement): Range | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer as Element
    : range.startContainer.parentElement;
  const end = range.endContainer.nodeType === Node.ELEMENT_NODE
    ? range.endContainer as Element
    : range.endContainer.parentElement;
  if (!start || !end || !root.contains(start) || !root.contains(end)) return null;
  return range;
}

function buildSelection(root: HTMLElement, range: Range): ArtifactTextSelection | null {
  const selectedText = range.toString().trim().slice(0, MAX_SELECTION_LENGTH);
  if (!selectedText) return null;
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE
    ? range.startContainer as Element
    : range.startContainer.parentElement;
  const block = start?.closest("p, td, th, li, h1, h2, h3, h4, h5, h6") as HTMLElement | null;
  const blockText = (block?.innerText || selectedText).replace(/\s+/g, " ").trim();
  const normalizedSelection = selectedText.replace(/\s+/g, " ").trim();
  const selectionIndex = blockText.indexOf(normalizedSelection);
  const contextBefore = selectionIndex >= 0
    ? blockText.slice(Math.max(0, selectionIndex - CONTEXT_LENGTH), selectionIndex)
    : "";
  const contextAfter = selectionIndex >= 0
    ? blockText.slice(selectionIndex + normalizedSelection.length, selectionIndex + normalizedSelection.length + CONTEXT_LENGTH)
    : "";
  const pageElement = start?.closest("section.docx");
  const pages = Array.from(root.querySelectorAll("section.docx"));
  const pageIndex = pageElement ? pages.indexOf(pageElement) : -1;
  return {
    kind: "text",
    page: pageIndex >= 0 ? pageIndex + 1 : undefined,
    selectedText,
    contextBefore,
    contextAfter,
  };
}

export function DocxPreview({
  dataBase64,
  fileName,
  onAnnotate,
}: {
  dataBase64: string;
  fileName: string;
  onAnnotate: (selection: ArtifactTextSelection, instruction: string) => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const styleRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<ArtifactTextSelection | null>(null);

  useEffect(() => {
    const body = bodyRef.current;
    const styles = styleRef.current;
    if (!body || !styles || !dataBase64) return;
    let cancelled = false;
    body.replaceChildren();
    styles.replaceChildren();
    setLoading(true);
    setError("");
    setSelection(null);
    selectionRangeRef.current = null;
    void import("docx-preview")
      .then(({ renderAsync }) => renderAsync(
        decodeBase64(dataBase64),
        body,
        styles,
        {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          renderChanges: true,
          renderComments: true,
          ignoreLastRenderedPageBreak: false,
        },
      ))
      .then(() => {
        if (!cancelled) setLoading(false);
      })
      .catch((reason) => {
        if (!cancelled) {
          setLoading(false);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
      body.replaceChildren();
      styles.replaceChildren();
    };
  }, [dataBase64, fileName]);

  const captureSelection = () => {
    const root = bodyRef.current;
    if (!root) return;
    const range = selectionInside(root);
    if (!range) return;
    selectionRangeRef.current = range.cloneRange();
    setSelection(buildSelection(root, range));
  };

  return (
    <div className="docx-preview-shell">
      <div ref={styleRef} className="docx-preview-styles" />
      <div className="docx-preview-help">
        <strong>文档预览</strong>
        <span>选中文字后，可以告诉 Agent 如何修改；原文件不会被覆盖。</span>
      </div>
      <div className="docx-preview-viewport" onMouseUp={captureSelection}>
        {loading && <div className="docx-preview-state">正在渲染文档…</div>}
        {error && <div className="docx-preview-state error">预览失败：{error}</div>}
        <div ref={bodyRef} className="docx-preview-surface" aria-label={`${fileName} 预览`} />
      </div>
      {selection && (
        <ArtifactAnnotationComposer
          excerpt={selection.selectedText}
          location={selection.page ? `第 ${selection.page} 页` : "已选择文字"}
          placeholder="例如：改得更正式，并保留原意"
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
