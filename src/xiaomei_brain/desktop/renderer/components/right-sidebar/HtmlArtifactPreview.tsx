import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ArtifactHtmlSelection } from "../../types";
import { ArtifactAnnotationComposer } from "./ArtifactAnnotationComposer";
import { Icon } from "../ui";

const BRIDGE_SOURCE = "xiaomei-html-preview";
const MAX_SELECTION_LENGTH = 20_000;

function decodeHtml(dataBase64: string): string {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/^\uFEFF/, "");
}

function bridgeScript(token: string): string {
  return `(() => {
    const source = ${JSON.stringify(BRIDGE_SOURCE)};
    const token = ${JSON.stringify(token)};
    let elementMode = false;
    let hovered = null;
    const clip = (value, size = ${MAX_SELECTION_LENGTH}) => String(value || '').slice(0, size);
    const escapeCss = (value) => window.CSS && CSS.escape
      ? CSS.escape(value)
      : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
    const selectorFor = (element) => {
      if (!element || element.nodeType !== 1) return 'body';
      if (element.id) return '#' + escapeCss(element.id);
      const parts = [];
      let current = element;
      while (current && current.nodeType === 1 && current !== document.documentElement && parts.length < 8) {
        let part = current.tagName.toLowerCase();
        const stableClasses = Array.from(current.classList || []).filter((name) => !name.startsWith('xiaomei-')).slice(0, 2);
        if (stableClasses.length) part += '.' + stableClasses.map(escapeCss).join('.');
        const siblings = current.parentElement
          ? Array.from(current.parentElement.children).filter((item) => item.tagName === current.tagName)
          : [];
        if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(current) + 1) + ')';
        parts.unshift(part);
        current = current.parentElement;
      }
      return parts.join(' > ') || element.tagName.toLowerCase();
    };
    const rectOf = (rangeOrElement) => {
      const rect = rangeOrElement.getBoundingClientRect();
      return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
    };
    const send = (selection, rect) => window.parent.postMessage({
      source, token, type: 'selection', selection, rect,
    }, '*');
    const selectElement = (element) => {
      const text = clip((element.innerText || element.textContent || '').trim());
      const outerHtml = clip(element.outerHTML || '<' + element.tagName.toLowerCase() + '>');
      send({
        kind: 'html', selector: selectorFor(element), tag: element.tagName.toLowerCase(),
        selectedText: text || outerHtml, outerHtml, contextBefore: '', contextAfter: '',
      }, rectOf(element));
    };
    const selectText = () => {
      const active = window.getSelection();
      if (!active || active.isCollapsed || active.rangeCount === 0) return;
      const range = active.getRangeAt(0);
      const selectedText = clip(range.toString().trim());
      if (!selectedText) return;
      const node = range.commonAncestorContainer.nodeType === 1
        ? range.commonAncestorContainer
        : range.commonAncestorContainer.parentElement;
      const element = node && node.closest
        ? (node.closest('p,li,td,th,h1,h2,h3,h4,h5,h6,button,a,section,article,div') || node)
        : document.body;
      const blockText = String(element.innerText || element.textContent || '');
      const index = blockText.indexOf(selectedText);
      send({
        kind: 'html', selector: selectorFor(element), tag: element.tagName.toLowerCase(),
        selectedText, outerHtml: clip(element.outerHTML || ''),
        contextBefore: index >= 0 ? blockText.slice(Math.max(0, index - 400), index) : '',
        contextAfter: index >= 0 ? blockText.slice(index + selectedText.length, index + selectedText.length + 400) : '',
      }, rectOf(range));
    };
    const clearHover = () => {
      if (hovered) hovered.classList.remove('xiaomei-html-hover');
      hovered = null;
    };
    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (data.source !== source || data.token !== token || data.type !== 'element-mode') return;
      elementMode = data.enabled === true;
      document.documentElement.classList.toggle('xiaomei-html-selecting', elementMode);
      if (!elementMode) clearHover();
    });
    document.addEventListener('mouseover', (event) => {
      if (!elementMode) return;
      clearHover();
      hovered = event.target instanceof Element ? event.target : null;
      if (hovered) hovered.classList.add('xiaomei-html-hover');
    }, true);
    document.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target && target.closest('a,button,form')) event.preventDefault();
      if (!elementMode || !target) return;
      event.preventDefault();
      event.stopPropagation();
      selectElement(target);
      clearHover();
    }, true);
    document.addEventListener('submit', (event) => event.preventDefault(), true);
    document.addEventListener('mouseup', () => {
      if (!elementMode) selectText();
    });
  })();`;
}

function safePreviewDocument(source: string, token: string): string {
  const documentValue = new DOMParser().parseFromString(source, "text/html");
  documentValue.querySelectorAll("script,iframe,object,embed,link,base").forEach((node) => node.remove());
  documentValue.querySelectorAll("meta[http-equiv]").forEach((node) => node.remove());
  documentValue.querySelectorAll<HTMLElement>("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || name === "srcdoc" || name === "formaction" || name === "action") {
        element.removeAttribute(attribute.name);
      }
      if ((name === "src" || name === "href") && !/^(#|data:|blob:)/i.test(attribute.value.trim())) {
        element.removeAttribute(attribute.name);
      }
    }
  });
  const csp = documentValue.createElement("meta");
  csp.httpEquiv = "Content-Security-Policy";
  csp.content = "default-src 'none'; img-src data: blob:; media-src data: blob:; style-src 'unsafe-inline'; font-src data:; script-src 'unsafe-inline'; form-action 'none'; navigate-to 'none'";
  documentValue.head.prepend(csp);
  const style = documentValue.createElement("style");
  style.textContent = `
    html.xiaomei-html-selecting, html.xiaomei-html-selecting * { cursor: crosshair !important; }
    .xiaomei-html-hover { outline: 2px solid #2f6fed !important; outline-offset: 2px !important; }
  `;
  documentValue.head.append(style);
  const bridge = documentValue.createElement("script");
  bridge.textContent = bridgeScript(token);
  documentValue.body.append(bridge);
  return `<!doctype html>\n${documentValue.documentElement.outerHTML}`;
}

function validSelection(value: unknown): ArtifactHtmlSelection | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (item.kind !== "html" || typeof item.selector !== "string" || typeof item.outerHtml !== "string") return null;
  return {
    kind: "html",
    selector: item.selector.slice(0, 2_000),
    tag: typeof item.tag === "string" ? item.tag.slice(0, 64) : "element",
    selectedText: typeof item.selectedText === "string" ? item.selectedText.slice(0, MAX_SELECTION_LENGTH) : "",
    outerHtml: item.outerHtml.slice(0, MAX_SELECTION_LENGTH),
    contextBefore: typeof item.contextBefore === "string" ? item.contextBefore.slice(0, 2_000) : "",
    contextAfter: typeof item.contextAfter === "string" ? item.contextAfter.slice(0, 2_000) : "",
  };
}

export function HtmlArtifactPreview({
  dataBase64,
  fileName,
  onAnnotate,
  onOpenOriginal,
  onBack,
  opening = false,
}: {
  dataBase64: string;
  fileName: string;
  onAnnotate: (selection: ArtifactHtmlSelection, instruction: string) => void;
  onOpenOriginal: () => void;
  onBack: () => void;
  opening?: boolean;
}) {
  const { t } = useTranslation();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const anchorRectRef = useRef<DOMRect | null>(null);
  const [elementMode, setElementMode] = useState(false);
  const [selection, setSelection] = useState<ArtifactHtmlSelection | null>(null);
  const [reloadRevision, setReloadRevision] = useState(0);
  const token = useMemo(() => crypto.randomUUID(), [dataBase64, fileName, reloadRevision]);
  const sourceDocument = useMemo(
    () => safePreviewDocument(decodeHtml(dataBase64), token),
    [dataBase64, token],
  );

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const data = event.data;
      if (!data || data.source !== BRIDGE_SOURCE || data.token !== token || data.type !== "selection") return;
      const next = validSelection(data.selection);
      const rawRect = data.rect as Record<string, unknown> | undefined;
      const frameRect = frameRef.current?.getBoundingClientRect();
      if (!next || !rawRect || !frameRect) return;
      anchorRectRef.current = new DOMRect(
        frameRect.left + Number(rawRect.left || 0),
        frameRect.top + Number(rawRect.top || 0),
        Number(rawRect.width || 0),
        Number(rawRect.height || 0),
      );
      setSelection(next);
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [token]);

  useEffect(() => {
    frameRef.current?.contentWindow?.postMessage({
      source: BRIDGE_SOURCE,
      token,
      type: "element-mode",
      enabled: elementMode,
    }, "*");
  }, [elementMode, token]);

  const clearSelection = () => {
    setSelection(null);
    anchorRectRef.current = null;
  };

  return (
    <div className="html-artifact-preview-shell">
      <div className="html-browser-chrome">
        <div className="html-browser-toolbar">
          <button
            type="button"
            className="html-browser-icon-button"
            title={t("artifactUi.back")}
            aria-label={t("artifactUi.back")}
            onClick={onBack}
          >
            <Icon name="chevron-left" size={21} />
          </button>
          <button
            type="button"
            className="html-browser-icon-button"
            title={t("artifactUi.forwardDisabled")}
            aria-label={t("artifactUi.forwardDisabled")}
            disabled
          >
            <Icon name="chevron-right" size={21} />
          </button>
          <div
            className="html-browser-address"
            title={t("artifactUi.safePreview")}
          >
            <Icon name="globe" size={18} />
            <strong>{`file:///${fileName}`}</strong>
          </div>
          <button
            type="button"
            className="html-browser-icon-button"
            title={t("artifactUi.reload")}
            aria-label={t("artifactUi.reload")}
            onClick={() => {
              clearSelection();
              setReloadRevision((value) => value + 1);
            }}
          >
            <Icon name="refresh" size={19} />
          </button>
          <button
            type="button"
            className="html-browser-icon-button"
            title={t("artifactUi.openBrowser")}
            aria-label={t("artifactUi.openBrowser")}
            disabled={opening}
            onClick={onOpenOriginal}
          >
            <Icon name="external-link" size={19} />
          </button>
          <button
            type="button"
            className={`html-browser-action ${elementMode ? "active" : ""}`}
            onClick={() => setElementMode((value) => !value)}
          >
            {elementMode ? t("artifactUi.exitSelect") : t("artifactUi.selectElement")}
          </button>
        </div>
      </div>
      <iframe
        key={reloadRevision}
        ref={frameRef}
        className="html-artifact-preview-frame"
        sandbox="allow-scripts"
        srcDoc={sourceDocument}
        title={t("artifactUi.safePreviewTitle", { name: fileName })}
        onLoad={() => {
          frameRef.current?.contentWindow?.postMessage({
            source: BRIDGE_SOURCE,
            token,
            type: "element-mode",
            enabled: elementMode,
          }, "*");
        }}
      />
      {selection && (
        <ArtifactAnnotationComposer
          excerpt={selection.selectedText || selection.outerHtml}
          location={`${selection.tag} · ${selection.selector}`}
          placeholder={t("artifactUi.editAreaExample")}
          getAnchorRect={() => anchorRectRef.current}
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
