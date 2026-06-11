"use client";

import type { ColumnTemplate } from "@/lib/api";

/* ── Mirror of DocAgentSpreadsheet's internal types ── */
interface CellStyle {
  bold?: boolean;
  italic?: boolean;
  fontSize?: number;
  fontColor?: string;
  bgColor?: string;
  align?: "left" | "center" | "right";
  borderAll?: boolean;
  borderOuter?: boolean;
}
interface SheetCell {
  value: string;
  style: CellStyle;
  mergeParent?: [number, number];
  mergeSpan?: { rows: number; cols: number };
  extractTarget?: boolean;
  repeatRow?: boolean;
}
interface GridData {
  cells: Record<string, SheetCell>;
  colWidths: number[];
  merges: Record<string, { rows: number; cols: number }>;
  extractTargets: Array<{ r: number; c: number; label: string; isRepeat: boolean }>;
  repeatRows: number[];
}

const ck = (r: number, c: number) => `${r},${c}`;

function parseGrid(desc: string | null | undefined): GridData | null {
  if (!desc) return null;
  try {
    const p = JSON.parse(desc);
    if (p && typeof p === "object" && "cells" in p) return p as GridData;
  } catch {}
  return null;
}

function contentBounds(g: GridData): { rows: number; cols: number } {
  let maxR = -1, maxC = -1;
  for (const key of Object.keys(g.cells)) {
    const cell = g.cells[key];
    if (!cell.value?.trim() && !cell.extractTarget) continue;
    const [r, c] = key.split(",").map(Number);
    if (r > maxR) maxR = r;
    if (c > maxC) maxC = c;
  }
  for (const et of (g.extractTargets ?? [])) {
    if (et.r > maxR) maxR = et.r;
    if (et.c > maxC) maxC = et.c;
  }
  for (const key of Object.keys(g.merges ?? {})) {
    const [r, c] = key.split(",").map(Number);
    const span = g.merges[key];
    if (r + span.rows - 1 > maxR) maxR = r + span.rows - 1;
    if (c + span.cols - 1 > maxC) maxC = c + span.cols - 1;
  }
  return { rows: Math.max(maxR + 1, 0), cols: Math.max(maxC + 1, 0) };
}

/* ────────────────────────────────────────────────── */
function GridPreview({ grid }: { grid: GridData }) {
  const { rows, cols } = contentBounds(grid);
  if (rows === 0 || cols === 0) {
    return <p style={{ fontSize: 11, color: "var(--text4)", padding: "8px 0" }}>No layout data in this template.</p>;
  }

  /* Cells covered by merges — skip rendering a <td> for them */
  const skipSet = new Set<string>();
  for (const key of Object.keys(grid.merges ?? {})) {
    const [r0, c0] = key.split(",").map(Number);
    const span = grid.merges[key];
    for (let dr = 0; dr < span.rows; dr++) {
      for (let dc = 0; dc < span.cols; dc++) {
        if (dr === 0 && dc === 0) continue;
        skipSet.add(ck(r0 + dr, c0 + dc));
      }
    }
  }

  const etKeys = new Set<string>((grid.extractTargets ?? []).map(et => ck(et.r, et.c)));
  const repeatSet = new Set<number>(grid.repeatRows ?? []);

  /* Scale colWidths for the preview viewport */
  const widths = Array.from({ length: cols }, (_, c) => {
    const w = (grid.colWidths?.[c] ?? 120) * 0.78;
    return Math.max(52, Math.min(w, 190));
  });

  const hasExtract = etKeys.size > 0;
  const hasRepeat = repeatSet.size > 0;

  return (
    <div>
      <div style={{
        overflowX: "auto", overflowY: "auto", maxHeight: 340,
        border: "1px solid var(--border)", borderRadius: 7,
      }}>
        <table style={{ borderCollapse: "collapse", tableLayout: "fixed", fontSize: 11, whiteSpace: "nowrap" }}>
          <colgroup>
            {widths.map((w, i) => <col key={i} style={{ width: w }} />)}
          </colgroup>
          <tbody>
            {Array.from({ length: rows }, (_, r) => {
              const isRepeatRow = repeatSet.has(r);
              return (
                <tr key={r}>
                  {Array.from({ length: cols }, (_, c) => {
                    const key = ck(r, c);
                    if (skipSet.has(key)) return null;

                    const cell: SheetCell | undefined = grid.cells[key];
                    const merge = grid.merges?.[key];
                    const isET = etKeys.has(key) || !!cell?.extractTarget;
                    const st = cell?.style ?? {};

                    const bg = isET
                      ? "var(--accent-dim)"
                      : st.bgColor
                      ? st.bgColor
                      : isRepeatRow
                      ? "var(--blue-bg)"
                      : undefined;

                    return (
                      <td
                        key={c}
                        rowSpan={merge?.rows}
                        colSpan={merge?.cols}
                        title={cell?.value ?? ""}
                        style={{
                          padding: "4px 8px",
                          border: "1px solid var(--border)",
                          background: bg,
                          borderLeft: isET ? "3px solid var(--accent)" : undefined,
                          verticalAlign: "middle",
                          textAlign: st.align ?? "left",
                          fontWeight: st.bold ? 600 : 400,
                          fontStyle: st.italic ? "italic" : undefined,
                          fontSize: Math.min(st.fontSize ?? 11, 12),
                          color: st.fontColor ?? "var(--text1)",
                          maxWidth: widths[c],
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          {isET && (
                            <svg width="8" height="8" viewBox="0 0 24 24" style={{ fill: "var(--accent)", flexShrink: 0 }}>
                              <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/>
                            </svg>
                          )}
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                            {cell?.value ?? ""}
                          </span>
                          {isRepeatRow && c === cols - 1 && (
                            <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--blue)", opacity: 0.6, flexShrink: 0 }}>↻</span>
                          )}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {(hasExtract || hasRepeat) && (
        <div style={{ display: "flex", gap: 14, marginTop: 7, flexWrap: "wrap" }}>
          {hasExtract && (
            <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--text3)" }}>
              <span style={{ display: "inline-block", width: 10, height: 10, background: "var(--accent-dim)", borderLeft: "3px solid var(--accent)", borderRadius: "0 2px 2px 0" }} />
              Extraction target
            </span>
          )}
          {hasRepeat && (
            <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, color: "var(--text3)" }}>
              <span style={{ display: "inline-block", width: 10, height: 10, background: "var(--blue-bg)", border: "1px solid var(--blue)", borderRadius: 2, opacity: 0.8 }} />
              Line-item row
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Fallback for templates with no grid layout ── */
function ColumnListFallback({ template }: { template: ColumnTemplate }) {
  const headers   = template.columns.filter(c => (c.extraction_type ?? "header") !== "lineitem");
  const lineitems = template.columns.filter(c => c.extraction_type === "lineitem");

  if (template.columns.length === 0) {
    return <p style={{ fontSize: 11, color: "var(--text4)", paddingTop: 4 }}>No columns defined in this template.</p>;
  }

  function Pill({ col, accent }: { col: typeof headers[0]; accent: string }) {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        padding: "3px 9px", borderRadius: 12,
        background: accent + "12", border: `1px solid ${accent}28`,
        fontSize: 11, color: "var(--text2)", fontWeight: 450,
      }}>
        {col.name}
        <span style={{ fontSize: 9, color: accent, opacity: 0.85, fontWeight: 500 }}>{col.type}</span>
      </span>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {headers.length > 0 && (
        <div>
          <p style={{ fontSize: 9.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text3)", marginBottom: 6 }}>
            Header fields ({headers.length})
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {headers.map(col => <Pill key={col.order} col={col} accent="var(--accent)" />)}
          </div>
        </div>
      )}
      {lineitems.length > 0 && (
        <div>
          <p style={{ fontSize: 9.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text3)", marginBottom: 6 }}>
            Line-item fields ({lineitems.length})
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {lineitems.map(col => <Pill key={col.order} col={col} accent="var(--blue)" />)}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Public export ── */
export default function TemplatePreview({ template }: { template: ColumnTemplate }) {
  const grid = parseGrid(template.description);
  return grid ? <GridPreview grid={grid} /> : <ColumnListFallback template={template} />;
}
