import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ArtifactPresentationSelection } from "../../types";
import { ArtifactAnnotationComposer } from "../right-sidebar/ArtifactAnnotationComposer";
import { Icon } from "../ui";

type PresentationMedia = {
  mime_type: string;
  data_base64: string;
};

type PresentationElement = {
  elementId: string;
  elementType: "text" | "shape" | "image" | "table";
  bounds: [number, number, number, number];
  content?: { text?: string; fontSize?: number; fontFamily?: string; color?: string; bold?: boolean; align?: string };
  text?: string;
  textStyle?: { fontSize?: number; fontFamily?: string; color?: string; bold?: boolean; align?: string };
  shapeName?: string;
  fill?: { color?: string };
  line?: { color?: string; width?: number };
  src?: string;
  fit?: { mode?: "cover" | "contain" };
  rows?: number;
  columns?: number;
  cells?: Array<{ row: number; column: number; text: string }>;
};

type PresentationSlide = {
  index: number;
  background?: { color?: string };
  elements: PresentationElement[];
};

export type PresentationProject = {
  schema: string;
  title: string;
  size: [number, number];
  sourceRevision?: string;
  slides: PresentationSlide[];
  media?: Record<string, PresentationMedia>;
};

function elementStyle(element: PresentationElement, project: PresentationProject) {
  const [x, y, width, height] = element.bounds;
  return {
    left: `${x / project.size[0] * 100}%`,
    top: `${y / project.size[1] * 100}%`,
    width: `${width / project.size[0] * 100}%`,
    height: `${height / project.size[1] * 100}%`,
  };
}

function SlideCanvas({ project, slide, thumbnail = false, selectedElementId, selectedCell, onSelectElement, onSelectSlide }: {
  project: PresentationProject;
  slide: PresentationSlide;
  thumbnail?: boolean;
  selectedElementId?: string;
  selectedCell?: string;
  onSelectElement?: (
    element: PresentationElement,
    anchor: HTMLElement,
    cell?: { row: number; column: number; text: string },
  ) => void;
  onSelectSlide?: (anchor: HTMLElement) => void;
}) {
  const media = project.media || {};
  const aspect = project.size[0] / project.size[1];
  return (
    <div
      className={`presentation-slide-canvas${thumbnail ? " thumbnail" : ""}${selectedElementId === `slide-${slide.index}` ? " selected" : ""}`}
      style={{
        aspectRatio: `${project.size[0]} / ${project.size[1]}`,
        width: thumbnail ? "100%" : `min(100%, calc((100vh - 130px) * ${aspect}))`,
        background: slide.background?.color || "#ffffff",
      }}
      onClick={(event) => {
        if (!onSelectSlide || event.target !== event.currentTarget) return;
        event.stopPropagation();
        onSelectSlide(event.currentTarget);
      }}
    >
      {slide.elements.map((element) => {
        const style = elementStyle(element, project);
        const selectableClass = onSelectElement ? " selectable" : "";
        const selectedClass = selectedElementId === element.elementId && !selectedCell ? " selected" : "";
        const select = (event: React.MouseEvent<HTMLElement>) => {
          if (!onSelectElement) return;
          event.stopPropagation();
          onSelectElement(element, event.currentTarget);
        };
        if (element.elementType === "image") {
          const source = element.src ? media[element.src] : undefined;
          if (!source) return null;
          return (
            <img
              key={element.elementId}
              className={`presentation-slide-element image${selectableClass}${selectedClass}`}
              data-element-id={element.elementId}
              style={{ ...style, objectFit: element.fit?.mode || "cover" }}
              src={`data:${source.mime_type};base64,${source.data_base64}`}
              alt=""
              onClick={select}
            />
          );
        }
        if (element.elementType === "table") {
          const columns = Math.max(1, element.columns || 1);
          const rows = Math.max(1, element.rows || 1);
          const cells = new Map((element.cells || []).map((cell) => [`${cell.row}:${cell.column}`, cell.text]));
          return (
            <div
              key={element.elementId}
              className={`presentation-slide-element table${selectableClass}${selectedClass}`}
              data-element-id={element.elementId}
              style={{ ...style, gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
              onClick={select}
            >
              {Array.from({ length: rows * columns }, (_, index) => {
                const row = Math.floor(index / columns);
                const column = index % columns;
                const text = cells.get(`${row}:${column}`) || "";
                const cellKey = `${row + 1}:${column + 1}`;
                return (
                  <div
                    key={`${row}:${column}`}
                    className={selectedCell === cellKey ? "selected" : ""}
                    onClick={(event) => {
                      if (!onSelectElement) return;
                      event.stopPropagation();
                      onSelectElement(
                        element,
                        event.currentTarget,
                        { row: row + 1, column: column + 1, text },
                      );
                    }}
                  >
                    {text}
                  </div>
                );
              })}
            </div>
          );
        }
        const textStyle = element.elementType === "text" ? element.content : element.textStyle;
        const content = element.elementType === "text" ? element.content?.text : element.text;
        const borderRadius = element.shapeName === "ellipse" ? "50%" : element.shapeName === "roundRect" ? "8%" : 0;
        return (
          <div
            key={element.elementId}
            className={`presentation-slide-element ${element.elementType}${selectableClass}${selectedClass}`}
            data-element-id={element.elementId}
            style={{
              ...style,
              background: element.elementType === "shape" ? element.fill?.color : undefined,
              border: element.elementType === "shape" ? `${element.line?.width || 0}px solid ${element.line?.color || "transparent"}` : undefined,
              borderRadius,
              color: textStyle?.color || "#253047",
              fontFamily: textStyle?.fontFamily,
              fontSize: `${(textStyle?.fontSize || 18) / project.size[0] * 100}cqw`,
              fontWeight: textStyle?.bold ? 700 : 400,
              textAlign: textStyle?.align === "center" || textStyle?.align === "right" ? textStyle.align : "left",
            }}
            onClick={select}
          >
            {content}
          </div>
        );
      })}
    </div>
  );
}

export function PresentationPreview({ project, compact = false, onAnnotate }: {
  project: PresentationProject;
  compact?: boolean;
  onAnnotate?: (selection: ArtifactPresentationSelection, instruction: string) => void;
}) {
  const { t } = useTranslation();
  const slides = useMemo(() => Array.isArray(project.slides) ? project.slides : [], [project.slides]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [selection, setSelection] = useState<ArtifactPresentationSelection | null>(null);
  const selectionAnchorRef = useRef<HTMLElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const move = useCallback((delta: number) => {
    setActiveIndex((value) => Math.max(0, Math.min(slides.length - 1, value + delta)));
  }, [slides.length]);

  useEffect(() => {
    setActiveIndex(0);
    setSelection(null);
    selectionAnchorRef.current = null;
    shellRef.current?.focus({ preventScroll: true });
  }, [project]);

  useEffect(() => {
    setSelection(null);
    selectionAnchorRef.current = null;
  }, [activeIndex]);

  useEffect(() => {
    shellRef.current
      ?.querySelector<HTMLButtonElement>(".presentation-preview-pages button.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeIndex]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      const previousKeys = new Set(["ArrowLeft", "ArrowUp", "PageUp"]);
      const nextKeys = new Set(["ArrowRight", "ArrowDown", "PageDown"]);
      if (!previousKeys.has(event.key) && !nextKeys.has(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      move(previousKeys.has(event.key) ? -1 : 1);
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [move]);

  if (!slides.length) return <div className="artifact-preview-state">{t("preview.presentationEmpty")}</div>;
  const active = slides[Math.min(activeIndex, slides.length - 1)];
  const selectElement = onAnnotate ? (
    element: PresentationElement,
    anchor: HTMLElement,
    cell?: { row: number; column: number; text: string },
  ) => {
    const selectedText = cell ? cell.text : element.elementType === "text"
      ? element.content?.text || ""
      : element.elementType === "shape"
        ? element.text || ""
        : element.elementType === "table"
          ? (element.cells || []).map((cell) => cell.text).filter(Boolean).join(" / ")
          : "";
    selectionAnchorRef.current = anchor;
    setSelection({
      kind: "presentation",
      slide: activeIndex + 1,
      elementId: element.elementId,
      elementType: element.elementType,
      selectedText,
      sourceRevision: project.sourceRevision || "",
      ...(cell ? { row: cell.row, column: cell.column } : {}),
    });
  } : undefined;
  const selectSlide = onAnnotate ? (anchor: HTMLElement) => {
    selectionAnchorRef.current = anchor;
    setSelection({
      kind: "presentation",
      slide: activeIndex + 1,
      elementId: `slide-${activeIndex + 1}`,
      elementType: "slide",
      selectedText: "",
      sourceRevision: project.sourceRevision || "",
    });
  } : undefined;
  const selectionLabel = selection
    ? selection.selectedText || t(`preview.presentationElement.${selection.elementType}`)
    : "";
  return (
    <div
      ref={shellRef}
      className={`presentation-preview-shell${compact ? " compact" : ""}`}
      tabIndex={-1}
    >
      {!compact && <nav className="presentation-preview-pages" aria-label={t("preview.presentationPages")}>
        {slides.map((slide, index) => (
          <button
            type="button"
            key={`${slide.index}-${index}`}
            className={index === activeIndex ? "active" : ""}
            onClick={() => setActiveIndex(index)}
            aria-label={t("preview.presentationPage", { page: index + 1 })}
          >
            <span className="presentation-preview-page-number">{index + 1}</span>
            <SlideCanvas project={project} slide={slide} thumbnail />
          </button>
        ))}
      </nav>}
      <main
        className="presentation-preview-stage"
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          setSelection(null);
          selectionAnchorRef.current = null;
        }}
      >
        <SlideCanvas
          project={project}
          slide={active}
          selectedElementId={selection?.elementId}
          selectedCell={selection?.row && selection?.column ? `${selection.row}:${selection.column}` : undefined}
          onSelectElement={selectElement}
          onSelectSlide={selectSlide}
        />
        {slides.length > 1 && (
          <div className="presentation-preview-navigation">
            <button
              type="button"
              onClick={() => move(-1)}
              disabled={activeIndex === 0}
              aria-label={t("stageUi.previous")}
            >
              <Icon name="chevron-left" size={18} />
            </button>
            <button
              type="button"
              onClick={() => move(1)}
              disabled={activeIndex === slides.length - 1}
              aria-label={t("stageUi.next")}
            >
              <Icon name="chevron-right" size={18} />
            </button>
          </div>
        )}
        <div className="presentation-preview-position">{activeIndex + 1} / {slides.length}</div>
      </main>
      {selection && onAnnotate && (
        <ArtifactAnnotationComposer
          excerpt={selectionLabel}
          location={t("preview.presentationSelectionLocation", {
            page: selection.slide,
            type: t(`preview.presentationElement.${selection.elementType}`),
            cell: selection.row && selection.column ? ` · R${selection.row}C${selection.column}` : "",
          })}
          placeholder={t("preview.editPresentationExample")}
          getAnchorRect={() => selectionAnchorRef.current?.getBoundingClientRect() || null}
          onCancel={() => {
            setSelection(null);
            selectionAnchorRef.current = null;
          }}
          onSubmit={(instruction) => {
            onAnnotate(selection, instruction);
            setSelection(null);
            selectionAnchorRef.current = null;
          }}
        />
      )}
    </div>
  );
}
