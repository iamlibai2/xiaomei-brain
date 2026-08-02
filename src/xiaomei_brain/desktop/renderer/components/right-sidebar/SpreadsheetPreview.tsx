import { useEffect, useMemo, useRef, useState } from "react";
import type { WorkBook } from "xlsx";
import type { ArtifactSpreadsheetSelection } from "../../types";
import { ArtifactAnnotationComposer } from "./ArtifactAnnotationComposer";

const MAX_ROWS = 1_000;
const MAX_COLUMNS = 100;
const MAX_SELECTION_LENGTH = 20_000;

type XlsxModule = typeof import("xlsx");
type CellPosition = { row: number; column: number };

function decodeBase64(dataBase64: string): Uint8Array {
  const binary = window.atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function decodeCsv(dataBase64: string): string {
  return new TextDecoder("utf-8", { fatal: false })
    .decode(decodeBase64(dataBase64))
    .replace(/^\uFEFF/, "");
}

function normalizedRange(first: CellPosition, second: CellPosition) {
  return {
    start: {
      row: Math.min(first.row, second.row),
      column: Math.min(first.column, second.column),
    },
    end: {
      row: Math.max(first.row, second.row),
      column: Math.max(first.column, second.column),
    },
  };
}

export function SpreadsheetPreview({
  dataBase64,
  fileName,
  onAnnotate,
}: {
  dataBase64: string;
  fileName: string;
  onAnnotate: (selection: ArtifactSpreadsheetSelection, instruction: string) => void;
}) {
  const [xlsx, setXlsx] = useState<XlsxModule | null>(null);
  const [workbook, setWorkbook] = useState<WorkBook | null>(null);
  const [activeSheet, setActiveSheet] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [anchor, setAnchor] = useState<CellPosition | null>(null);
  const [focus, setFocus] = useState<CellPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const [showComposer, setShowComposer] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setWorkbook(null);
    setAnchor(null);
    setFocus(null);
    setShowComposer(false);
    void import("xlsx").then((module) => {
      const isCsv = fileName.toLowerCase().endsWith(".csv");
      const value = module.read(
        isCsv ? decodeCsv(dataBase64) : decodeBase64(dataBase64),
        {
          type: isCsv ? "string" : "array",
          cellDates: true,
          cellFormula: true,
          cellStyles: false,
        },
      );
      if (cancelled) return;
      setXlsx(module);
      setWorkbook(value);
      setActiveSheet(value.SheetNames[0] || "");
      setLoading(false);
    }).catch((reason) => {
      if (!cancelled) {
        setLoading(false);
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    });
    return () => { cancelled = true; };
  }, [dataBase64, fileName]);

  useEffect(() => {
    const finish = () => setDragging(false);
    window.addEventListener("mouseup", finish);
    return () => window.removeEventListener("mouseup", finish);
  }, []);

  const grid = useMemo(() => {
    if (!xlsx || !workbook || !activeSheet) return null;
    const sheet = workbook.Sheets[activeSheet];
    if (!sheet) return null;
    const source = xlsx.utils.decode_range(sheet["!ref"] || "A1:A1");
    const endRow = Math.min(source.e.r, source.s.r + MAX_ROWS - 1);
    const endColumn = Math.min(source.e.c, source.s.c + MAX_COLUMNS - 1);
    const rows = [] as Array<{ index: number; values: string[] }>;
    for (let row = source.s.r; row <= endRow; row += 1) {
      const values: string[] = [];
      for (let column = source.s.c; column <= endColumn; column += 1) {
        const cell = sheet[xlsx.utils.encode_cell({ r: row, c: column })];
        values.push(cell ? xlsx.utils.format_cell(cell) : "");
      }
      rows.push({ index: row, values });
    }
    return {
      rows,
      startColumn: source.s.c,
      endColumn,
      truncatedRows: source.e.r > endRow,
      truncatedColumns: source.e.c > endColumn,
    };
  }, [activeSheet, workbook, xlsx]);

  const selection = useMemo(() => {
    if (!anchor || !focus || !grid || !xlsx) return null;
    const range = normalizedRange(anchor, focus);
    const sheet = workbook?.Sheets[activeSheet];
    if (!sheet) return null;
    const values: string[] = [];
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      const cells: string[] = [];
      for (let column = range.start.column; column <= range.end.column; column += 1) {
        const cell = sheet[xlsx.utils.encode_cell({ r: row, c: column })];
        cells.push(cell ? xlsx.utils.format_cell(cell) : "");
      }
      values.push(cells.join("\t"));
    }
    const startAddress = xlsx.utils.encode_cell({ r: range.start.row, c: range.start.column });
    const endAddress = xlsx.utils.encode_cell({ r: range.end.row, c: range.end.column });
    return {
      kind: "spreadsheet" as const,
      sheet: activeSheet,
      range: startAddress === endAddress ? startAddress : `${startAddress}:${endAddress}`,
      selectedText: (values.join("\n").trim() || "（空白单元格）").slice(0, MAX_SELECTION_LENGTH),
      bounds: range,
    };
  }, [activeSheet, anchor, focus, grid, workbook, xlsx]);

  const changeSheet = (name: string) => {
    setActiveSheet(name);
    setAnchor(null);
    setFocus(null);
    setShowComposer(false);
  };

  return (
    <div className="spreadsheet-preview-shell">
      <div className="artifact-preview-toolbar">
        <div>
          <strong>表格预览</strong>
          <span>{fileName}</span>
        </div>
      </div>
      {workbook && workbook.SheetNames.length > 0 && (
        <div className="spreadsheet-sheet-tabs" role="tablist" aria-label="工作表">
          {workbook.SheetNames.map((name) => (
            <button
              type="button"
              role="tab"
              aria-selected={name === activeSheet}
              className={name === activeSheet ? "active" : ""}
              key={name}
              onClick={() => changeSheet(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      <div
        ref={viewportRef}
        className="spreadsheet-preview-viewport"
        onMouseUp={() => {
          if (!dragging) return;
          setDragging(false);
          setShowComposer(true);
        }}
      >
        {loading && <div className="artifact-preview-state">正在读取工作簿…</div>}
        {error && <div className="artifact-preview-state error">预览失败：{error}</div>}
        {grid && xlsx && (
          <table className="spreadsheet-preview-table">
            <thead>
              <tr>
                <th className="spreadsheet-corner" />
                {Array.from(
                  { length: grid.endColumn - grid.startColumn + 1 },
                  (_, index) => grid.startColumn + index,
                ).map((column) => <th key={column}>{xlsx.utils.encode_col(column)}</th>)}
              </tr>
            </thead>
            <tbody>
              {grid.rows.map((row) => (
                <tr key={row.index}>
                  <th>{row.index + 1}</th>
                  {row.values.map((value, offset) => {
                    const position = { row: row.index, column: grid.startColumn + offset };
                    const selected = selection && (
                      position.row >= selection.bounds.start.row
                      && position.row <= selection.bounds.end.row
                      && position.column >= selection.bounds.start.column
                      && position.column <= selection.bounds.end.column
                    );
                    return (
                      <td
                        key={position.column}
                        className={selected ? "selected" : ""}
                        data-selected={selected ? "true" : undefined}
                        title={value}
                        onMouseDown={(event) => {
                          event.preventDefault();
                          const nextAnchor = event.shiftKey && anchor ? anchor : position;
                          setAnchor(nextAnchor);
                          setFocus(position);
                          setDragging(true);
                          setShowComposer(false);
                        }}
                        onMouseEnter={() => {
                          if (dragging) setFocus(position);
                        }}
                        onDoubleClick={() => setShowComposer(true)}
                      >
                        {value}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {grid && (grid.truncatedRows || grid.truncatedColumns) && (
          <div className="artifact-preview-limit">
            工作表较大，当前预览前 {MAX_ROWS} 行、{MAX_COLUMNS} 列；完整文件仍可交给 Agent 分析。
          </div>
        )}
      </div>
      {selection && showComposer && (
        <ArtifactAnnotationComposer
          excerpt={selection.selectedText}
          location={`${selection.sheet}!${selection.range}`}
          placeholder="例如：把这一区域的金额改为含税价，并更新合计"
          getAnchorRect={() => {
            const cells = Array.from(viewportRef.current?.querySelectorAll<HTMLElement>('td[data-selected="true"]') || []);
            if (cells.length === 0) return null;
            const rects = cells.map((cell) => cell.getBoundingClientRect());
            const left = Math.min(...rects.map((rect) => rect.left));
            const top = Math.min(...rects.map((rect) => rect.top));
            const right = Math.max(...rects.map((rect) => rect.right));
            const bottom = Math.max(...rects.map((rect) => rect.bottom));
            return new DOMRect(left, top, right - left, bottom - top);
          }}
          onCancel={() => setShowComposer(false)}
          onSubmit={(instruction) => {
            const { bounds: _bounds, ...payload } = selection;
            onAnnotate(payload, instruction);
            setShowComposer(false);
          }}
        />
      )}
    </div>
  );
}
