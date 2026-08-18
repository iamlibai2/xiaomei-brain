import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
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

type PresentationCrop = { left?: number; top?: number; right?: number; bottom?: number };

type PresentationFill = {
  type?: "none" | "solid" | "gradient" | "image" | "unknown";
  color?: string;
  gradientType?: "linear" | "radial";
  angle?: number;
  stops?: Array<{ position: number; color: string }>;
  src?: string;
  fit?: { mode?: "cover" | "contain" | "fill" };
  crop?: PresentationCrop;
  opacity?: number;
};

type PresentationShadow = {
  blur?: number;
  color?: string;
  offset?: [number, number];
};

type PresentationLine = {
  type?: "none" | "solid" | "dash" | "dot" | "unknown";
  color?: string;
  width?: number;
};

type PresentationChartAxis = {
  visible?: boolean;
  labelsVisible?: boolean;
  position?: string;
  line?: PresentationLine;
  labelStyle?: PresentationTextStyle;
  majorGridline?: PresentationLine;
  minimum?: number;
  maximum?: number;
  majorUnit?: number;
  numberFormat?: string;
};

type PresentationChartDataLabels = {
  showValue?: boolean;
  showCategory?: boolean;
  showSeries?: boolean;
  showPercent?: boolean;
  position?: string;
  numberFormat?: string;
  style?: PresentationTextStyle;
};

type PresentationChartSeries = {
  name: string;
  values: Array<number | string | null>;
  color?: string;
  line?: PresentationLine;
  marker?: {
    symbol?: string;
    size?: number;
    fill?: PresentationFill;
    line?: PresentationLine;
  };
  dataLabels?: PresentationChartDataLabels;
};

type PresentationChartLayout = {
  target?: string;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
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
  fill?: PresentationFill;
  line?: PresentationLine;
  shadow?: PresentationShadow;
  src?: string;
  fit?: { mode?: "cover" | "contain" | "fill" };
  crop?: PresentationCrop;
  cropShape?: "rect" | "ellipse" | "roundRect";
  rows?: number;
  columns?: number;
  cells?: Array<{
    row: number;
    column: number;
    text: string;
    fill?: PresentationFill;
    textStyle?: PresentationTextStyle;
    columnSpan?: number;
    rowSpan?: number;
    hidden?: boolean;
  }>;
  chartType?: string;
  title?: string;
  titleStyle?: { fontSize?: number; fontFamily?: string; color?: string; bold?: boolean; align?: string };
  categories?: string[];
  series?: PresentationChartSeries[];
  hasLegend?: boolean;
  legend?: {
    position?: string;
    overlay?: boolean;
    style?: PresentationTextStyle;
    layout?: PresentationChartLayout;
  };
  plotArea?: PresentationChartLayout;
  gapWidth?: number;
  overlap?: number;
  roundedCorners?: boolean;
  categoryAxis?: PresentationChartAxis;
  valueAxis?: PresentationChartAxis;
};

type PresentationSlide = {
  index: number;
  background?: PresentationFill;
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

function mediaUrl(source: string | undefined, media: Record<string, PresentationMedia>): string | undefined {
  const item = source ? media[source] : undefined;
  return item ? `data:${item.mime_type};base64,${item.data_base64}` : undefined;
}

function fillStyle(fill: PresentationFill | undefined, media: Record<string, PresentationMedia>): CSSProperties {
  if (!fill || fill.type === "none") return { background: "transparent" };
  if (fill.type === "solid") return { background: fill.color || "transparent" };
  if (fill.type === "gradient" && (fill.stops || []).length >= 2) {
    const stops = (fill.stops || [])
      .map((stop) => `${stop.color} ${Math.max(0, Math.min(1, stop.position)) * 100}%`)
      .join(", ");
    return {
      background: fill.gradientType === "radial"
        ? `radial-gradient(circle, ${stops})`
        : `linear-gradient(${(fill.angle || 0) + 90}deg, ${stops})`,
    };
  }
  if (fill.type === "image") {
    const source = mediaUrl(fill.src, media);
    const crop = fill.crop;
    const horizontalCrop = (crop?.left || 0) + (crop?.right || 0);
    const verticalCrop = (crop?.top || 0) + (crop?.bottom || 0);
    const hasCrop = horizontalCrop > 0 || verticalCrop > 0;
    const availableWidth = Math.max(0.01, 1 - horizontalCrop);
    const availableHeight = Math.max(0.01, 1 - verticalCrop);
    const cropX = horizontalCrop > 0 ? (crop?.left || 0) / horizontalCrop * 100 : 50;
    const cropY = verticalCrop > 0 ? (crop?.top || 0) / verticalCrop * 100 : 50;
    return source ? {
      backgroundImage: `url("${source}")`,
      backgroundPosition: hasCrop ? `${cropX}% ${cropY}%` : "center",
      backgroundRepeat: "no-repeat",
      backgroundSize: hasCrop
        ? `${100 / availableWidth}% ${100 / availableHeight}%`
        : fill.fit?.mode === "contain" ? "contain" : fill.fit?.mode === "fill" ? "100% 100%" : "cover",
    } : { background: "transparent" };
  }
  return { background: fill.color || "transparent" };
}

function shadowStyle(shadow: PresentationShadow | undefined, project: PresentationProject): string | undefined {
  if (!shadow) return undefined;
  const [offsetX, offsetY] = shadow.offset || [0, 0];
  return [offsetX, offsetY, shadow.blur || 0]
    .map((value) => pointsToCanvasWidth(value, project) || "0")
    .join(" ") + ` ${shadow.color || "#00000040"}`;
}

function croppedImageStyle(crop: PresentationCrop | undefined): CSSProperties {
  const left = crop?.left || 0;
  const top = crop?.top || 0;
  const right = crop?.right || 0;
  const bottom = crop?.bottom || 0;
  const availableWidth = Math.max(0.01, 1 - left - right);
  const availableHeight = Math.max(0.01, 1 - top - bottom);
  return {
    position: "absolute",
    width: `${100 / availableWidth}%`,
    height: `${100 / availableHeight}%`,
    left: `${-left / availableWidth * 100}%`,
    top: `${-top / availableHeight * 100}%`,
  };
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

function niceStep(range: number, targetTicks = 5): number {
  if (!Number.isFinite(range) || range <= 0) return 1;
  const rough = range / Math.max(1, targetTicks - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / magnitude;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return factor * magnitude;
}

function chartScale(values: number[], axis: PresentationChartAxis | undefined) {
  const dataMinimum = values.length ? Math.min(...values) : 0;
  const dataMaximum = values.length ? Math.max(...values) : 1;
  const includeZeroMinimum = dataMinimum >= 0 ? 0 : dataMinimum;
  const includeZeroMaximum = dataMaximum <= 0 ? 0 : dataMaximum;
  const rawMinimum = axis?.minimum ?? includeZeroMinimum;
  const rawMaximum = axis?.maximum ?? includeZeroMaximum;
  const step = axis?.majorUnit && axis.majorUnit > 0
    ? axis.majorUnit
    : niceStep(Math.max(1e-9, rawMaximum - rawMinimum));
  const minimum = axis?.minimum ?? Math.floor(rawMinimum / step) * step;
  let maximum = axis?.maximum ?? Math.ceil(rawMaximum / step) * step;
  if (maximum <= minimum) maximum = minimum + step;
  const ticks: number[] = [];
  for (let value = minimum, count = 0; value <= maximum + step / 100 && count < 20; value += step, count += 1) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return { minimum, maximum, ticks };
}

function formatAxisValue(value: number, format?: string): string {
  if (format?.includes("%")) return `${Math.round(value * 100)}%`;
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: Math.abs(value) < 10 && !Number.isInteger(value) ? 2 : 0,
  }).format(value);
}

function svgDash(line: PresentationLine | undefined): string | undefined {
  return line?.type === "dash" ? "3 2" : line?.type === "dot" ? "1 2" : undefined;
}

function chartDataLabel(
  labels: PresentationChartDataLabels | undefined,
  seriesName: string,
  category: string,
  value: number,
  seriesTotal: number,
): string {
  if (!labels) return "";
  const parts: string[] = [];
  if (labels.showSeries) parts.push(seriesName);
  if (labels.showCategory) parts.push(category);
  if (labels.showValue) parts.push(formatAxisValue(value, labels.numberFormat));
  if (labels.showPercent) parts.push(`${Math.round(value / Math.max(1e-9, seriesTotal) * 100)}%`);
  return parts.join(" ");
}

function ChartMarker({
  x,
  y,
  marker,
  color,
}: {
  x: number;
  y: number;
  marker: PresentationChartSeries["marker"];
  color: string;
}) {
  if (!marker || marker.symbol === "none") return null;
  const radius = Math.max(0.65, Math.min(2.2, (marker.size || 5) * 0.14));
  const fill = marker.fill?.color || color;
  const stroke = marker.line?.color || color;
  const strokeWidth = Math.max(0.25, (marker.line?.width || 0.75) * 0.35);
  if (marker.symbol === "square") {
    return <rect x={x - radius} y={y - radius} width={radius * 2} height={radius * 2} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
  }
  if (marker.symbol === "diamond") {
    return <path d={`M ${x} ${y - radius} L ${x + radius} ${y} L ${x} ${y + radius} L ${x - radius} ${y} Z`} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
  }
  if (marker.symbol === "triangle") {
    return <path d={`M ${x} ${y - radius} L ${x + radius} ${y + radius} L ${x - radius} ${y + radius} Z`} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
  }
  if (marker.symbol === "x" || marker.symbol === "star") {
    return (
      <path
        d={`M ${x - radius} ${y - radius} L ${x + radius} ${y + radius} M ${x + radius} ${y - radius} L ${x - radius} ${y + radius}`}
        fill="none"
        stroke={stroke}
        strokeWidth={Math.max(0.5, strokeWidth)}
      />
    );
  }
  return <circle cx={x} cy={y} r={radius} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
}

function CartesianChart({
  element,
  project,
  categories,
  series,
  lineChart,
}: {
  element: PresentationElement;
  project: PresentationProject;
  categories: string[];
  series: Array<Omit<PresentationChartSeries, "values"> & { values: number[] }>;
  lineChart: boolean;
}) {
  const categoryAxis = element.categoryAxis;
  const valueAxis = element.valueAxis;
  const values = series.flatMap((item) => item.values);
  const scale = chartScale(values, valueAxis);
  const manualPlot = element.plotArea;
  const fallbackPlot = {
    left: valueAxis?.labelsVisible === false ? 6 : 17,
    right: 97,
    top: 5,
    bottom: categoryAxis?.labelsVisible === false ? 56 : 47,
  };
  const plot = manualPlot && typeof manualPlot.w === "number" && typeof manualPlot.h === "number"
    ? {
      left: Math.max(2, Math.min(92, (manualPlot.x || 0) * 100)),
      right: Math.max(8, Math.min(98, ((manualPlot.x || 0) + manualPlot.w) * 100)),
      top: Math.max(1, Math.min(52, (manualPlot.y || 0) * 60)),
      bottom: Math.max(8, Math.min(59, ((manualPlot.y || 0) + manualPlot.h) * 60)),
    }
    : fallbackPlot;
  const width = plot.right - plot.left;
  const height = plot.bottom - plot.top;
  const y = (value: number) => plot.bottom - (value - scale.minimum) / (scale.maximum - scale.minimum) * height;
  const categoryX = (index: number) => lineChart
    ? plot.left + index / Math.max(1, categories.length - 1) * width
    : plot.left + (index + 0.5) / Math.max(1, categories.length) * width;
  const labelFontSize = Math.max(
    2.2,
    Math.min(4.2, (valueAxis?.labelStyle?.fontSize || 10) / Math.max(1, element.bounds[2]) * 100),
  );
  const categoryFontSize = Math.max(
    2.2,
    Math.min(4.2, (categoryAxis?.labelStyle?.fontSize || 10) / Math.max(1, element.bounds[2]) * 100),
  );
  const gridline = valueAxis?.majorGridline;
  const valueLine = valueAxis?.line;
  const categoryLine = categoryAxis?.line;
  const gapRatio = Math.max(0.08, Math.min(0.92, 100 / (100 + Math.max(0, element.gapWidth ?? 150))));
  const barGroupWidth = width / Math.max(1, categories.length) * gapRatio;
  const overlapRatio = Math.max(-1, Math.min(1, (element.overlap || 0) / 100));
  const seriesCount = Math.max(1, series.length);
  const barWidth = barGroupWidth / Math.max(1, seriesCount - overlapRatio * (seriesCount - 1));
  const barStep = barWidth * (1 - overlapRatio);
  const renderedGroupWidth = barWidth + barStep * (seriesCount - 1);
  return (
    <svg className="presentation-chart-cartesian" viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true">
      {valueAxis?.visible !== false && scale.ticks.map((tick) => (
        <g key={`tick-${tick}`}>
          {gridline?.type !== "none" && (
            <line
              x1={plot.left}
              x2={plot.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke={gridline?.color || "#D9DEE7"}
              strokeWidth={Math.max(0.3, (gridline?.width || 0.5) * 0.45)}
              strokeDasharray={svgDash(gridline)}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {valueAxis?.labelsVisible !== false && (
            <text
              x={plot.left - 1.8}
              y={y(tick)}
              fill={valueAxis?.labelStyle?.color || "#697386"}
              fontFamily={valueAxis?.labelStyle?.fontFamily}
              fontSize={labelFontSize}
              fontWeight={valueAxis?.labelStyle?.bold ? 700 : 400}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {formatAxisValue(tick, valueAxis?.numberFormat)}
            </text>
          )}
        </g>
      ))}
      {valueAxis?.visible !== false && valueLine?.type !== "none" && (
        <line
          x1={plot.left}
          x2={plot.left}
          y1={plot.top}
          y2={plot.bottom}
          stroke={valueLine?.color || "#888888"}
          strokeWidth={Math.max(0.4, valueLine?.width || 1)}
          strokeDasharray={svgDash(valueLine)}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {categoryAxis?.visible !== false && categoryLine?.type !== "none" && (
        <line
          x1={plot.left}
          x2={plot.right}
          y1={plot.bottom}
          y2={plot.bottom}
          stroke={categoryLine?.color || "#888888"}
          strokeWidth={Math.max(0.4, categoryLine?.width || 1)}
          strokeDasharray={svgDash(categoryLine)}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {lineChart ? series.map((item, seriesIndex) => {
        const points = item.values.map((value, index) => `${categoryX(index)},${y(value)}`).join(" ");
        const color = item.line?.color || item.color || "#4F6BED";
        const total = item.values.reduce((sum, value) => sum + Math.max(0, value), 0);
        return (
          <g key={`line-${seriesIndex}`}>
            <polyline
              points={points}
              fill="none"
              stroke={color}
              strokeWidth={Math.max(0.5, item.line?.width || 2)}
              strokeDasharray={svgDash(item.line)}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            {item.values.map((value, index) => {
              const label = chartDataLabel(item.dataLabels, item.name, categories[index] || "", value, total);
              const labelOffset = item.dataLabels?.position === "b" ? 3.2 : -2.2;
              return (
                <g key={index}>
                  <ChartMarker x={categoryX(index)} y={y(value)} marker={item.marker} color={color} />
                  {label && (
                    <text
                      x={categoryX(index)}
                      y={y(value) + labelOffset}
                      fill={item.dataLabels?.style?.color || color}
                      fontFamily={item.dataLabels?.style?.fontFamily}
                      fontSize={Math.max(2.2, Math.min(4.2, (item.dataLabels?.style?.fontSize || 10) / Math.max(1, element.bounds[2]) * 100))}
                      fontWeight={item.dataLabels?.style?.bold ? 700 : 400}
                      textAnchor="middle"
                    >
                      {label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        );
      }) : categories.flatMap((_, categoryIndex) => series.map((item, seriesIndex) => {
        const value = item.values[categoryIndex] || 0;
        const zeroY = y(Math.max(scale.minimum, Math.min(scale.maximum, 0)));
        const valueY = y(value);
        const total = item.values.reduce((sum, itemValue) => sum + Math.max(0, itemValue), 0);
        const label = chartDataLabel(item.dataLabels, item.name, categories[categoryIndex] || "", value, total);
        const barX = categoryX(categoryIndex) - renderedGroupWidth / 2 + seriesIndex * barStep;
        const renderedBarWidth = Math.max(0.5, barWidth * 0.9);
        const barTop = Math.min(zeroY, valueY);
        const barHeight = Math.max(0.4, Math.abs(zeroY - valueY));
        const labelInside = item.dataLabels?.position === "ctr" || item.dataLabels?.position === "inEnd" || item.dataLabels?.position === "inBase";
        return (
          <g key={`bar-${categoryIndex}-${seriesIndex}`}>
            <rect
              x={barX}
              y={barTop}
              width={renderedBarWidth}
              height={barHeight}
              rx={element.roundedCorners ? Math.min(1.4, renderedBarWidth * 0.18) : 0}
              fill={item.color || "#4F6BED"}
            />
            {label && (
              <text
                x={barX + renderedBarWidth / 2}
                y={labelInside ? barTop + Math.max(3, barHeight * 0.22) : barTop - 1.5}
                fill={item.dataLabels?.style?.color || (labelInside ? "#FFFFFF" : item.color || "#4F6BED")}
                fontFamily={item.dataLabels?.style?.fontFamily}
                fontSize={Math.max(2.2, Math.min(4.2, (item.dataLabels?.style?.fontSize || 10) / Math.max(1, element.bounds[2]) * 100))}
                fontWeight={item.dataLabels?.style?.bold ? 700 : 400}
                textAnchor="middle"
              >
                {label}
              </text>
            )}
          </g>
        );
      }))}
      {categoryAxis?.visible !== false && categoryAxis?.labelsVisible !== false && categories.map((category, index) => (
        <text
          key={`category-${index}`}
          x={categoryX(index)}
          y="53"
          fill={categoryAxis?.labelStyle?.color || "#697386"}
          fontFamily={categoryAxis?.labelStyle?.fontFamily}
          fontSize={categoryFontSize}
          fontWeight={categoryAxis?.labelStyle?.bold ? 700 : 400}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {category.length > 12 ? `${category.slice(0, 11)}…` : category}
        </text>
      ))}
    </svg>
  );
}

function PresentationLegend({
  element,
  series,
}: {
  element: PresentationElement;
  series: PresentationChartSeries[];
}) {
  if (!element.hasLegend || !series.length) return null;
  const style = element.legend?.style;
  return (
    <div
      className={`presentation-chart-legend position-${element.legend?.position || "b"}`}
      style={{
        color: style?.color,
        fontFamily: style?.fontFamily,
        fontWeight: style?.bold ? 700 : 400,
      }}
    >
      {series.map((item, index) => (
        <span key={`${item.name}-${index}`}>
          <i style={{ background: item.color || "#4F6BED" }} />
          {item.name}
        </span>
      ))}
    </div>
  );
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
  const legendPosition = element.legend?.position || "b";
  const legendAtTop = legendPosition === "t" || legendPosition === "tr";
  const legendAtLeft = legendPosition === "l";
  const legendAtRight = legendPosition === "r";
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
      {legendAtTop && <PresentationLegend element={element} series={series} />}
      <div className="presentation-chart-main">
        {legendAtLeft && <PresentationLegend element={element} series={series} />}
        <div className="presentation-chart-plot">
          {isPie ? (
            <div className={`presentation-chart-pie${chartType.includes("doughnut") ? " doughnut" : ""}`} style={{ background: pieBackground }} />
          ) : (
            <CartesianChart
              element={element}
              project={project}
              categories={categories}
              series={numericSeries}
              lineChart={isLine}
            />
          )}
        </div>
        {legendAtRight && <PresentationLegend element={element} series={series} />}
      </div>
      {!legendAtTop && !legendAtLeft && !legendAtRight && <PresentationLegend element={element} series={series} />}
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
        background: "#ffffff",
        ...fillStyle(slide.background, media),
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
            <div
              key={element.elementId}
              className={`presentation-slide-element image${selectableClass}${selectedClass}`}
              data-element-id={element.elementId}
              style={{
                ...style,
                borderRadius: element.cropShape === "ellipse" ? "50%" : element.cropShape === "roundRect" ? "8%" : 0,
                boxShadow: shadowStyle(element.shadow, project),
              }}
              onClick={select}
            >
              <img
                style={{
                  ...croppedImageStyle(element.crop),
                  objectFit: element.fit?.mode || "fill",
                }}
                src={`data:${source.mime_type};base64,${source.data_base64}`}
                alt=""
              />
            </div>
          );
        }
        if (element.elementType === "chart") {
          return (
            <div
              key={element.elementId}
              className={`presentation-slide-element chart${selectableClass}${selectedClass}`}
              data-element-id={element.elementId}
              style={{
                ...style,
                ...fillStyle(element.fill, media),
                boxShadow: shadowStyle(element.shadow, project),
              }}
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
              ...(element.elementType === "shape" ? fillStyle(element.fill, media) : {}),
              border: element.elementType === "shape" ? `${element.line?.width || 0}px solid ${element.line?.color || "transparent"}` : undefined,
              boxShadow: shadowStyle(element.shadow, project),
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
