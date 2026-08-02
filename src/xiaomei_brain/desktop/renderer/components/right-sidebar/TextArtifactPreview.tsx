import { useMemo, useRef, useState } from "react";
import type { ArtifactTextSelection } from "../../types";
import { MarkdownMessage } from "../home/MarkdownMessage";
import { ArtifactAnnotationComposer } from "./ArtifactAnnotationComposer";

const MAX_RENDERED_CHARACTERS = 500_000;
const MAX_SELECTION_LENGTH = 20_000;
const CONTEXT_LENGTH = 400;

function decodeText(dataBase64: string): string {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/^\uFEFF/, "");
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
  const previewText = root.innerText;
  const index = previewText.indexOf(selectedText);
  return {
    kind: "text",
    selectedText,
    contextBefore: index >= 0
      ? previewText.slice(Math.max(0, index - CONTEXT_LENGTH), index)
      : "",
    contextAfter: index >= 0
      ? previewText.slice(index + selectedText.length, index + selectedText.length + CONTEXT_LENGTH)
      : "",
  };
}

export function TextArtifactPreview({
  dataBase64,
  fileName,
  markdown,
  onAnnotate,
}: {
  dataBase64: string;
  fileName: string;
  markdown: boolean;
  onAnnotate: (selection: ArtifactTextSelection, instruction: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);
  const [selection, setSelection] = useState<ArtifactTextSelection | null>(null);
  const decoded = useMemo(() => decodeText(dataBase64), [dataBase64]);
  const truncated = decoded.length > MAX_RENDERED_CHARACTERS;
  const content = truncated ? decoded.slice(0, MAX_RENDERED_CHARACTERS) : decoded;

  const captureSelection = () => {
    const root = rootRef.current;
    if (!root) return;
    const range = selectionInside(root);
    if (!range) return;
    const next = buildSelection(root, range);
    if (!next) return;
    selectionRangeRef.current = range.cloneRange();
    setSelection(next);
  };

  const clearSelection = () => {
    setSelection(null);
    selectionRangeRef.current = null;
    window.getSelection()?.removeAllRanges();
  };

  return (
    <div className="text-artifact-preview-shell">
      <div className="artifact-preview-toolbar">
        <div>
          <strong>{markdown ? "Markdown 预览" : "文本预览"}</strong>
          <span>{fileName}</span>
        </div>
        <small>选中文字后可让 Agent 修改</small>
      </div>
      <div className="text-artifact-preview-viewport">
        <div
          ref={rootRef}
          className={`text-artifact-preview-surface ${markdown ? "markdown" : "plain"}`}
          onMouseUp={captureSelection}
        >
          {markdown ? <MarkdownMessage content={content} /> : <pre>{content}</pre>}
        </div>
        {truncated && (
          <div className="artifact-preview-limit">
            文件较大，当前只预览前 {MAX_RENDERED_CHARACTERS.toLocaleString()} 个字符；完整文件仍可交给 Agent 处理。
          </div>
        )}
      </div>
      {selection && (
        <ArtifactAnnotationComposer
          excerpt={selection.selectedText}
          location="已选择文字"
          placeholder="例如：把这段改得更简洁，并保持原意"
          getAnchorRect={() => selectionRangeRef.current?.getBoundingClientRect() || null}
          onCancel={clearSelection}
          onSubmit={(instruction) => {
            onAnnotate(selection, instruction);
            clearSelection();
          }}
        />
      )}
    </div>
  );
}
