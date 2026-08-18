import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ArtifactPresentationSelection } from "../../types";
import { ArtifactAnnotationComposer } from "../right-sidebar/ArtifactAnnotationComposer";
import { Icon } from "../ui";

type PresentationMedia = {
  mime_type: string;
  data_base64: string;
};

type PresentationTextStyle = {
  fontSize?: number;
  fontFamily?: string;
  color?: string;
  bold?: boolean;
  italic?: boolean;
  align?: string;
  verticalAlign?: "top" | "middle" | "bottom";
  margins?: [number, number, number, number];
};

type PresentationTextRun = PresentationTextStyle & { text: string };

type PresentationTextParagraph = {
  align?: string;
  level?: number;
  bullet?: boolean;
  spaceBefore?: number;
  spaceAfter?: number;
  lineHeight?: { points?: number; multiple?: number };
  runs?: PresentationTextRun[];
};

type PresentationElement = {
  elementId: string;
  elementType: "text" | "shape" | "image" | "table" | "chart";
  bounds: [number, number, number, number];
  rotation?: number;
  content?: PresentationTextStyle & { text?: string };
  text?: string;
  textStyle?: PresentationTextStyle;
  richText?: { paragraphs?: PresentationTextParagraph[] };
  shapeName?: string;
  fill?: { type?: "none" | "solid" | "unknown"; color?: string };
  line?: { type?: "none" | "solid" | "unknown"; color?: string; width?: number };
  src?: string;
  fit?: { mode?: "cover" | "contain" };
  rows?: number;
  columns?: number;
  cells?: Array<{
    row: number;
    column: number;
    text: string;
    fill?: { type?: "none" | "solid" | "unknown"; color?: string };
    textStyle?: PresentationTextStyle;
    columnSpan?: number;
    rowSpan?: number;
    hidden?: boolean;
  }>;
  chartType?: string;
  title?: string;
  titleStyle?: { fontSize?: number; fontFamily?: string; color?: string; bold?: boolean; align?: string };
  categories?: string[];
  series?: Array<{ name: string; values: Array<number | string | null>; color?: string }>;
  hasLegend?: boolean;
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
    transform: element.rotation ? `rotate(${element.rotation}deg)` : undefined,
  };
}

function pointsToCanvasWidth(points: number | undefined, project: PresentationProject): string | undefined {
  return typeof points === "number" ? `${points / project.size[0] * 100}cqw` : undefined;
}

function richTextContent(
  element: PresentationElement,
  baseStyle: PresentationTextStyle | undefined,
  project: PresentationProject,
) {
  const paragraphs = element.richText?.paragraphs || [];
  if (!paragraphs.length) return element.elementType === "text" ? element.content?.text : element.text;
  return paragraphs.map((paragraph, paragraphIndex) => {
    const lineHeight = paragraph.lineHeight?.points
      ? pointsToCanvasWidth(paragraph.lineHeight.points, project)
      : paragraph.lineHeight?.multiple;
    return (
      <div
        className="presentation-text-paragraph"
        key={`${element.elementId}-paragraph-${paragraphIndex}`}
        style={{
          marginTop: pointsToCanvasWidth(paragraph.spaceBefore, project),
          marginBottom: pointsToCanvasWidth(paragraph.spaceAfter, project),
          paddingLeft: paragraph.level ? `${paragraph.level * 1.2}em` : undefined,
          lineHeight,
          textAlign: paragraph.align === "center" || paragraph.align === "right" || paragraph.align === "justify"
            ? paragraph.align
            : baseStyle?.align === "center" || baseStyle?.align === "right" ? baseStyle.align : "left",
        }}
      >
        {paragraph.bullet && <span className="presentation-text-bullet" aria-hidden="true">•</span>}
        {(paragraph.runs || []).map((run, runIndex) => (
          <span
            key={`${element.elementId}-paragraph-${paragraphIndex}-run-${runIndex}`}
            style={{
              color: run.color,
              fontFamily: run.fontFamily,
              fontSize: run.fontSize ? `${run.fontSize / project.size[0] * 100}cqw` : undefined,
              fontWeight: run.bold ? 700 : undefined,
              fontStyle: run.italic ? "italic" : undefined,
            }}
          >
            {run.text}
          </span>
        ))}
      </div>
    );
  });
}

function PresentationChart({ element, project }: { element: PresentationElement; project: PresentationProject }) {
  const categories = (element.categories || []).slice(0, 16);
  const series = (element.series || []).slice(0, 8);
  const numericSeries = series.map((item) => ({
    ...item,
    values: categories.map((_, index) => {
      const value = Number(item.values[index]);
      return Number.isFinite(value) ? value : 0;
    }),
  }));
  const maxValue = Math.max(1, ...numericSeries.flatMap((item) => item.values.map((value) => Math.abs(value))));
  const chartType = (element.chartType || "").toLowerCase();
  const isPie = chartType.includes("pie") || chartType.includes("doughnut");
  const isLine = chartType.includes("line") || chartType.includes("scatter");
  const primaryValues = numericSeries[0]?.values || [];
  const total = primaryValues.reduce((sum, value) => sum + Math.max(0, value), 0) || 1;
  const piePalette = [series[0]?.color || "#4F6BED", "#16A085", "#F39C12", "#E15B64", "#7A5AF8", "#3498DB"];
  let offset = 0;
  const pieBackground = primaryValues.length > 0 ? `conic-gradient(${primaryValues.map((value, index) => {
    const start = offset / total * 100;
    offset += Math.max(0, value);
    const end = offset / total * 100;
    const color = piePalette[index % piePalette.length];
    return `${color} ${start}% ${end}%`;
  }).join(", ")})` : "#e5e7eb";
  return (
    <div className="presentation-chart-content">
      {element.title && (
        <div
          className="presentation-chart-title"
          style={{
            color: element.titleStyle?.color,
            fontFamily: element.titleStyle?.fontFamily,
            fontSize: element.titleStyle?.fontSize
              ? `${element.titleStyle.fontSize / project.size[0] * 100}cqw`
              : undefined,
            fontWeight: element.titleStyle?.bold ? 700 : undefined,
            textAlign: element.titleStyle?.align === "left" || element.titleStyle?.align === "right"
              ? element.titleStyle.align
              : "center",
          }}
        >
          {element.title}
        </div>
      )}
      <div className="presentation-chart-plot">
        {isPie ? (
          <div className={`presentation-chart-pie${chartType.includes("doughnut") ? " doughnut" : ""}`} style={{ background: pieBackground }} />
        ) : isLine ? (
          <svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true">
            {numericSeries.map((item, seriesIndex) => {
              const denominator = Math.max(1, item.values.length - 1);
              const points = item.values.map((value, index) => (
                `${index / denominator * 100},${56 - Math.max(0, value) / maxValue * 50}`
              )).join(" ");
              return <polyline key={seriesIndex} points={points} fill="none" stroke={item.color || "#4F6BED"} strokeWidth="2" vectorEffect="non-scaling-stroke" />;
            })}
          </svg>
        ) : (
          <div className="presentation-chart-columns">
            {categories.map((category, categoryIndex) => (
              <div className="presentation-chart-category" key={`${category}-${categoryIndex}`}>
                <div className="presentation-chart-bars">
                  {numericSeries.map((item, seriesIndex) => (
                    <span
                      key={seriesIndex}
                      style={{
                        height: `${Math.max(2, Math.abs(item.values[categoryIndex] || 0) / maxValue * 100)}%`,
                        background: item.color || "#4F6BED",
                      }}
                    />
                  ))}
                </div>
                <small>{category}</small>
              </div>
            ))}
          </div>
        )}
      </div>
      {element.hasLegend && series.length > 0 && (
        <div className="presentation-chart-legend">
          {series.map((item, index) => <span key={`${item.name}-${index}`}><i style={{ background: item.color || "#4F6BED" }} />{item.name}</span>)}
        </div>
      )}
    </div>
  );
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
        if (element.elementType === "chart") {
          return (
            <div
              key={element.elementId}
              className={`presentation-slide-element chart${selectableClass}${selectedClass}`}
              data-element-id={element.elementId}
              style={{ ...style, background: element.fill?.color || "transparent" }}
              onClick={select}
            >
              <PresentationChart element={element} project={project} />
            </div>
          );
        }
        if (element.elementType === "table") {
          const columns = Math.max(1, element.columns || 1);
          const rows = Math.max(1, element.rows || 1);
          const cells = new Map((element.cells || []).map((cell) => [`${cell.row}:${cell.column}`, cell]));
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
                const cell = cells.get(`${row}:${column}`);
                if (cell?.hidden) return null;
                const text = cell?.text || "";
                const cellKey = `${row + 1}:${column + 1}`;
                return (
                  <div
                    key={`${row}:${column}`}
                    className={selectedCell === cellKey ? "selected" : ""}
                    style={{
                      gridColumn: `${column + 1} / span ${Math.max(1, cell?.columnSpan || 1)}`,
                      gridRow: `${row + 1} / span ${Math.max(1, cell?.rowSpan || 1)}`,
                      background: cell?.fill?.color || "transparent",
                      color: cell?.textStyle?.color,
                      fontFamily: cell?.textStyle?.fontFamily,
                      fontSize: cell?.textStyle?.fontSize
                        ? `${cell.textStyle.fontSize / project.size[0] * 100}cqw`
                        : undefined,
                      fontWeight: cell?.textStyle?.bold ? 700 : undefined,
                      fontStyle: cell?.textStyle?.italic ? "italic" : undefined,
                      textAlign: cell?.textStyle?.align === "center" || cell?.textStyle?.align === "right"
                        ? cell.textStyle.align
                        : "left",
                    }}
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
        const margins = textStyle?.margins || [0, 0, 0, 0];
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
              fontStyle: textStyle?.italic ? "italic" : undefined,
              textAlign: textStyle?.align === "center" || textStyle?.align === "right" ? textStyle.align : "left",
              justifyContent: textStyle?.verticalAlign === "middle"
                ? "center"
                : textStyle?.verticalAlign === "bottom" ? "flex-end" : "flex-start",
              padding: margins.map((value) => pointsToCanvasWidth(value, project) || "0").join(" "),
            }}
            onClick={select}
          >
            {element.richText?.paragraphs?.length ? richTextContent(element, textStyle, project) : content}
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
          : element.elementType === "chart"
            ? [
              element.title || "",
              (element.categories || []).join(" / "),
              ...(element.series || []).map((item) => `${item.name}: ${item.values.join(", ")}`),
            ].filter(Boolean).join("\n").slice(0, 20_000)
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
