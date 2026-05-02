"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import type { TemplateColumn } from "@/lib/api";

interface CellStyle {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  fontSize?: number;
  fontColor?: string;
  bgColor?: string;
  align?: "left" | "center" | "right";
  valign?: "top" | "middle" | "bottom";
  wrap?: boolean;
  borders?: { top?: boolean; right?: boolean; bottom?: boolean; left?: boolean };
}

interface Cell {
  value: string;
  style: CellStyle;
  merged?: { rows: number; cols: number };
  mergedInto?: [number, number];
}

interface Props {
  initialColumns?: TemplateColumn[];
  onSheetsChange?: (data: any[]) => void;
  height?: number | string;
}

const ROWS = 50;
const COLS = 26;
const DEFAULT_COL_WIDTH = 120;
const DEFAULT_ROW_HEIGHT = 25;
const ROW_HEADER_WIDTH = 46;
const COL_HEADER_HEIGHT = 24;

const colLetter = (i: number) => {
  let r = "", n = i;
  do { r = String.fromCharCode(65 + (n % 26)) + r; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return r;
};

const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72];
const COLORS = [
  "#000000","#434343","#666666","#999999","#b7b7b7","#cccccc","#d9d9d9","#ffffff",
  "#ff0000","#ff4500","#ff9900","#ffff00","#00ff00","#00ffff","#4a86e8","#0000ff",
  "#9900ff","#ff00ff","#e6b8a2","#f4cccc","#fce5cd","#fff2cc","#d9ead3","#d0e0e3",
  "#c9daf8","#cfe2f3","#d9d2e9","#ead1dc","#4285f4","#34a853","#fbbc05","#ea4335",
];

export default function DocAgentSpreadsheet({ initialColumns = [], onSheetsChange, height = 500 }: Props) {
  const initGrid = (): Cell[][] => {
    const g: Cell[][] = Array.from({ length: ROWS }, () =>
      Array.from({ length: COLS }, () => ({ value: "", style: {} }))
    );
    initialColumns.forEach((col, i) => {
      if (i < COLS) g[0][i] = { value: col.name, style: { bold: true, bgColor: "#eff6ff", fontColor: "#1d4ed8" } };
    });
    return g;
  };

  const [grid, setGrid] = useState<Cell[][]>(initGrid);
  const [colWidths, setColWidths] = useState<number[]>(() => Array(COLS).fill(DEFAULT_COL_WIDTH));
  const [rowHeights, setRowHeights] = useState<number[]>(() => Array(ROWS).fill(DEFAULT_ROW_HEIGHT));
  const [sel, setSel] = useState<{ r: number; c: number } | null>({ r: 0, c: 0 });
  const [selRange, setSelRange] = useState<{ r1: number; c1: number; r2: number; c2: number } | null>(null);
  const [editCell, setEditCell] = useState<{ r: number; c: number } | null>(null);
  const [editVal, setEditVal] = useState("");
  const [showColorPicker, setShowColorPicker] = useState<"font" | "bg" | null>(null);
  const [history, setHistory] = useState<Cell[][][]>([]);
  const [redoStack, setRedoStack] = useState<Cell[][][]>([]);
  const [draggingCol, setDraggingCol] = useState<number | null>(null);
  const [draggingRow, setDraggingRow] = useState<number | null>(null);
  const dragStartX = useRef(0);
  const dragStartW = useRef(0);
  const dragStartY = useRef(0);
  const dragStartH = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isSelecting = useRef(false);

  const notifyChange = useCallback((g: Cell[][]) => {
    if (!onSheetsChange) return;
    const row0 = g[0].map((cell, c) => cell.value.trim() ? { r: 0, c, v: { v: cell.value } } : null).filter(Boolean);
    onSheetsChange([{ celldata: row0 }]);
  }, [onSheetsChange]);

  const pushHistory = useCallback((g: Cell[][]) => {
    setHistory(h => [...h.slice(-49), g.map(r => r.map(c => ({ ...c, style: { ...c.style } })))]);
    setRedoStack([]);
  }, []);

  const updateGrid = useCallback((updater: (g: Cell[][]) => Cell[][], skipHistory = false) => {
    setGrid(prev => {
      if (!skipHistory) pushHistory(prev);
      const next = updater(prev.map(r => r.map(c => ({ ...c, style: { ...c.style } }))));
      notifyChange(next);
      return next;
    });
  }, [pushHistory, notifyChange]);

  const undo = useCallback(() => {
    setHistory(h => {
      if (!h.length) return h;
      const prev = h[h.length - 1];
      setRedoStack(r => [...r, grid]);
      setGrid(prev);
      notifyChange(prev);
      return h.slice(0, -1);
    });
  }, [grid, notifyChange]);

  const redo = useCallback(() => {
    setRedoStack(r => {
      if (!r.length) return r;
      const next = r[r.length - 1];
      setHistory(h => [...h, grid]);
      setGrid(next);
      notifyChange(next);
      return r.slice(0, -1);
    });
  }, [grid, notifyChange]);

  // Current cell style
  const curStyle: CellStyle = sel ? grid[sel.r]?.[sel.c]?.style ?? {} : {};

  // Start editing a cell
  const startEdit = useCallback((r: number, c: number) => {
    const val = grid[r]?.[c]?.value ?? "";
    setEditCell({ r, c });
    setEditVal(val);
    setTimeout(() => inputRef.current?.focus(), 10);
  }, [grid]);

  // Commit edit
  const commitEdit = useCallback(() => {
    if (!editCell) return;
    const { r, c } = editCell;
    updateGrid(g => { g[r][c].value = editVal; return g; });
    setEditCell(null);
  }, [editCell, editVal, updateGrid]);

  // Apply style to selection
  const applyStyle = useCallback((patch: Partial<CellStyle>) => {
    updateGrid(g => {
      const range = selRange ?? (sel ? { r1: sel.r, c1: sel.c, r2: sel.r, c2: sel.c } : null);
      if (!range) return g;
      for (let r = range.r1; r <= range.r2; r++)
        for (let c = range.c1; c <= range.c2; c++)
          g[r][c].style = { ...g[r][c].style, ...patch };
      return g;
    });
  }, [sel, selRange, updateGrid]);

  // Merge cells
  const mergeCells = useCallback(() => {
    if (!selRange) return;
    const { r1, c1, r2, c2 } = selRange;
    updateGrid(g => {
      const baseVal = g[r1][c1].value;
      g[r1][c1].merged = { rows: r2 - r1 + 1, cols: c2 - c1 + 1 };
      for (let r = r1; r <= r2; r++)
        for (let c = c1; c <= c2; c++)
          if (r !== r1 || c !== c1) { g[r][c].value = ""; g[r][c].mergedInto = [r1, c1]; }
      g[r1][c1].value = baseVal;
      return g;
    });
    setSelRange(null);
  }, [selRange, updateGrid]);

  // Unmerge
  const unmerge = useCallback(() => {
    if (!sel) return;
    updateGrid(g => {
      const cell = g[sel.r][sel.c];
      if (cell.merged) {
        const { rows, cols } = cell.merged;
        for (let r = sel.r; r < sel.r + rows; r++)
          for (let c = sel.c; c < sel.c + cols; c++)
            if (r !== sel.r || c !== sel.c) delete g[r][c].mergedInto;
        delete cell.merged;
      }
      return g;
    });
  }, [sel, updateGrid]);

  // Delete cell contents
  const deleteCells = useCallback(() => {
    updateGrid(g => {
      const range = selRange ?? (sel ? { r1: sel.r, c1: sel.c, r2: sel.r, c2: sel.c } : null);
      if (!range) return g;
      for (let r = range.r1; r <= range.r2; r++)
        for (let c = range.c1; c <= range.c2; c++)
          g[r][c].value = "";
      return g;
    });
  }, [sel, selRange, updateGrid]);

  // Keyboard handling
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (editCell) return;
      if (!sel) return;
      const { r, c } = sel;
      if (e.ctrlKey || e.metaKey) {
        if (e.key === "z") { e.preventDefault(); undo(); }
        if (e.key === "y") { e.preventDefault(); redo(); }
        if (e.key === "b") { e.preventDefault(); applyStyle({ bold: !curStyle.bold }); }
        if (e.key === "i") { e.preventDefault(); applyStyle({ italic: !curStyle.italic }); }
        if (e.key === "u") { e.preventDefault(); applyStyle({ underline: !curStyle.underline }); }
        return;
      }
      if (e.key === "ArrowUp")    { e.preventDefault(); setSel({ r: Math.max(0, r - 1), c }); setSelRange(null); }
      if (e.key === "ArrowDown")  { e.preventDefault(); setSel({ r: Math.min(ROWS - 1, r + 1), c }); setSelRange(null); }
      if (e.key === "ArrowLeft")  { e.preventDefault(); setSel({ r, c: Math.max(0, c - 1) }); setSelRange(null); }
      if (e.key === "ArrowRight") { e.preventDefault(); setSel({ r, c: Math.min(COLS - 1, c + 1) }); setSelRange(null); }
      if (e.key === "Tab")        { e.preventDefault(); setSel({ r, c: Math.min(COLS - 1, c + 1) }); setSelRange(null); }
      if (e.key === "Enter")      { e.preventDefault(); setSel({ r: Math.min(ROWS - 1, r + 1), c }); setSelRange(null); }
      if (e.key === "Delete" || e.key === "Backspace") { deleteCells(); }
      if (e.key === "F2") startEdit(r, c);
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) { setEditVal(""); startEdit(r, c); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [sel, editCell, curStyle, undo, redo, applyStyle, deleteCells, startEdit]);

  // Col resize
  const startColResize = (e: React.MouseEvent, c: number) => {
    e.preventDefault();
    setDraggingCol(c);
    dragStartX.current = e.clientX;
    dragStartW.current = colWidths[c];
    const onMove = (ev: MouseEvent) => {
      const newW = Math.max(40, dragStartW.current + ev.clientX - dragStartX.current);
      setColWidths(w => { const n = [...w]; n[c] = newW; return n; });
    };
    const onUp = () => { setDraggingCol(null); document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  // Row resize
  const startRowResize = (e: React.MouseEvent, r: number) => {
    e.preventDefault();
    setDraggingRow(r);
    dragStartY.current = e.clientY;
    dragStartH.current = rowHeights[r];
    const onMove = (ev: MouseEvent) => {
      const newH = Math.max(18, dragStartH.current + ev.clientY - dragStartY.current);
      setRowHeights(h => { const n = [...h]; n[r] = newH; return n; });
    };
    const onUp = () => { setDraggingRow(null); document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const isSel = (r: number, c: number) => {
    if (selRange) return r >= selRange.r1 && r <= selRange.r2 && c >= selRange.c1 && c <= selRange.c2;
    return sel?.r === r && sel?.c === c;
  };

  const cellAddr = sel ? `${colLetter(sel.c)}${sel.r + 1}` : "";
  const cellVal = sel ? (editCell?.r === sel.r && editCell?.c === sel.c ? editVal : grid[sel.r]?.[sel.c]?.value ?? "") : "";

  const toolbarBtnStyle = (active?: boolean): React.CSSProperties => ({
    padding: "3px 7px", borderRadius: 4, border: `1px solid ${active ? "#4f46e5" : "transparent"}`,
    background: active ? "#ede9fe" : "transparent", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 13, color: active ? "#4f46e5" : "#374151", fontFamily: "inherit",
    minWidth: 28, height: 28, userSelect: "none" as const,
  });

  return (
    <div style={{ height, display: "flex", flexDirection: "column", border: "1px solid #e3e6ec", borderRadius: 10, overflow: "hidden", background: "#fff", userSelect: "none" }}>

      {/* ── Toolbar ── */}
      <div style={{ background: "#f8f9fb", borderBottom: "1px solid #e3e6ec", padding: "4px 8px", display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", flexShrink: 0 }}>

        {/* Undo/Redo */}
        <button style={toolbarBtnStyle()} onClick={undo} title="Undo (Ctrl+Z)"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 10h10a8 8 0 0 1 8 8v2M3 10l6-6M3 10l6 6"/></svg></button>
        <button style={toolbarBtnStyle()} onClick={redo} title="Redo (Ctrl+Y)"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10H11a8 8 0 0 0-8 8v2m18-10l-6-6m6 6l-6 6"/></svg></button>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Font family */}
        <select
          style={{ height: 28, border: "1px solid #e3e6ec", borderRadius: 4, fontSize: 12, padding: "0 4px", background: "#fff", cursor: "pointer" }}
          value={curStyle.fontColor ? "Arial" : "Arial"}
          onChange={() => {}}
        >
          <option>Arial</option><option>Calibri</option><option>Times New Roman</option><option>Courier New</option><option>Georgia</option>
        </select>

        {/* Font size */}
        <select
          style={{ height: 28, width: 52, border: "1px solid #e3e6ec", borderRadius: 4, fontSize: 12, padding: "0 4px", background: "#fff", cursor: "pointer" }}
          value={curStyle.fontSize ?? 11}
          onChange={e => applyStyle({ fontSize: parseInt(e.target.value) })}
        >
          {FONT_SIZES.map(s => <option key={s}>{s}</option>)}
        </select>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Bold/Italic/Underline */}
        <button style={toolbarBtnStyle(curStyle.bold)} onClick={() => applyStyle({ bold: !curStyle.bold })} title="Bold (Ctrl+B)"><b>B</b></button>
        <button style={{ ...toolbarBtnStyle(curStyle.italic), fontStyle: "italic" }} onClick={() => applyStyle({ italic: !curStyle.italic })} title="Italic (Ctrl+I)"><i>I</i></button>
        <button style={{ ...toolbarBtnStyle(curStyle.underline), textDecoration: "underline" }} onClick={() => applyStyle({ underline: !curStyle.underline })} title="Underline (Ctrl+U)">U</button>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Font color */}
        <div style={{ position: "relative" }}>
          <button style={{ ...toolbarBtnStyle(), flexDirection: "column", gap: 1 }} onClick={() => setShowColorPicker(v => v === "font" ? null : "font")} title="Font color">
            <span style={{ fontSize: 12, fontWeight: 600, color: curStyle.fontColor ?? "#000" }}>A</span>
            <div style={{ width: 16, height: 3, background: curStyle.fontColor ?? "#000", borderRadius: 1 }} />
          </button>
          {showColorPicker === "font" && (
            <div style={{ position: "absolute", top: 32, left: 0, zIndex: 100, background: "#fff", border: "1px solid #e3e6ec", borderRadius: 8, padding: 8, boxShadow: "0 4px 16px rgba(0,0,0,0.1)", display: "grid", gridTemplateColumns: "repeat(8,20px)", gap: 3 }}>
              {COLORS.map(color => (
                <div key={color} onClick={() => { applyStyle({ fontColor: color }); setShowColorPicker(null); }}
                  style={{ width: 20, height: 20, background: color, borderRadius: 3, cursor: "pointer", border: color === "#ffffff" ? "1px solid #ddd" : "none" }} />
              ))}
            </div>
          )}
        </div>

        {/* Background color */}
        <div style={{ position: "relative" }}>
          <button style={{ ...toolbarBtnStyle(), flexDirection: "column", gap: 1 }} onClick={() => setShowColorPicker(v => v === "bg" ? null : "bg")} title="Background color">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22C6.5 22 2 17.5 2 12S6.5 2 12 2s10 4.5 10 10"/><path d="M12 8v4l3 3"/></svg>
            <div style={{ width: 16, height: 3, background: curStyle.bgColor ?? "#ffff00", borderRadius: 1 }} />
          </button>
          {showColorPicker === "bg" && (
            <div style={{ position: "absolute", top: 32, left: 0, zIndex: 100, background: "#fff", border: "1px solid #e3e6ec", borderRadius: 8, padding: 8, boxShadow: "0 4px 16px rgba(0,0,0,0.1)", display: "grid", gridTemplateColumns: "repeat(8,20px)", gap: 3 }}>
              {COLORS.map(color => (
                <div key={color} onClick={() => { applyStyle({ bgColor: color }); setShowColorPicker(null); }}
                  style={{ width: 20, height: 20, background: color, borderRadius: 3, cursor: "pointer", border: color === "#ffffff" ? "1px solid #ddd" : "none" }} />
              ))}
            </div>
          )}
        </div>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Alignment */}
        <button style={toolbarBtnStyle(curStyle.align === "left")} onClick={() => applyStyle({ align: "left" })} title="Align left"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="21" y1="12" x2="3" y2="12"/><polyline points="10 19 3 12 10 5"/></svg></button>
        <button style={toolbarBtnStyle(curStyle.align === "center" || !curStyle.align)} onClick={() => applyStyle({ align: "center" })} title="Center"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="12" x2="16" y2="12"/><line x1="12" y1="8" x2="16" y2="12"/><line x1="12" y1="16" x2="16" y2="12"/></svg></button>
        <button style={toolbarBtnStyle(curStyle.align === "right")} onClick={() => applyStyle({ align: "right" })} title="Align right"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="12" x2="21" y2="12"/><polyline points="14 5 21 12 14 19"/></svg></button>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Borders */}
        <button style={toolbarBtnStyle()} onClick={() => applyStyle({ borders: { top: true, right: true, bottom: true, left: true } })} title="All borders"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="1"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg></button>
        <button style={toolbarBtnStyle()} onClick={() => applyStyle({ borders: {} })} title="No borders"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="1"/></svg></button>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Merge */}
        <button style={toolbarBtnStyle()} onClick={mergeCells} disabled={!selRange} title="Merge cells">
          <span style={{ fontSize: 11 }}>Merge</span>
        </button>
        <button style={toolbarBtnStyle()} onClick={unmerge} title="Unmerge">
          <span style={{ fontSize: 11 }}>Split</span>
        </button>
        <div style={{ width: 1, height: 20, background: "#e3e6ec", margin: "0 4px" }} />

        {/* Wrap text */}
        <button style={toolbarBtnStyle(curStyle.wrap)} onClick={() => applyStyle({ wrap: !curStyle.wrap })} title="Wrap text">
          <span style={{ fontSize: 10 }}>Wrap</span>
        </button>

        {/* Clear formatting */}
        <button style={toolbarBtnStyle()} onClick={() => applyStyle({ bold: false, italic: false, underline: false, fontColor: undefined, bgColor: undefined, align: undefined, borders: undefined, wrap: false, fontSize: 11 })} title="Clear formatting">
          <span style={{ fontSize: 11 }}>Clear</span>
        </button>
      </div>

      {/* ── Formula bar ── */}
      <div style={{ display: "flex", alignItems: "center", borderBottom: "1px solid #e3e6ec", background: "#fff", height: 28, flexShrink: 0 }}>
        <div style={{ width: 72, textAlign: "center", borderRight: "1px solid #e3e6ec", fontSize: 12, color: "#374151", fontWeight: 500, height: "100%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {cellAddr}
        </div>
        <div style={{ width: 32, textAlign: "center", borderRight: "1px solid #e3e6ec", fontSize: 13, color: "#9ca3af", fontStyle: "italic", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          ƒx
        </div>
        <div style={{ flex: 1, padding: "0 8px", fontSize: 12, color: "#374151", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {cellVal}
        </div>
      </div>

      {/* ── Grid ── */}
      <div
        ref={scrollRef}
        style={{ flex: 1, overflow: "auto", position: "relative" }}
        onClick={() => setShowColorPicker(null)}
      >
        <table style={{ borderCollapse: "collapse", tableLayout: "fixed", minWidth: "max-content" }}>
          {/* Column headers */}
          <thead>
            <tr>
              <th style={{ width: ROW_HEADER_WIDTH, minWidth: ROW_HEADER_WIDTH, height: COL_HEADER_HEIGHT, background: "#f8f9fb", border: "1px solid #d1d5db", position: "sticky", top: 0, left: 0, zIndex: 20 }} />
              {Array.from({ length: COLS }, (_, c) => (
                <th key={c} style={{ width: colWidths[c], minWidth: colWidths[c], height: COL_HEADER_HEIGHT, background: "#f8f9fb", border: "1px solid #d1d5db", fontSize: 11, fontWeight: 500, color: "#6b7280", textAlign: "center", position: "sticky", top: 0, zIndex: 10, userSelect: "none", cursor: "pointer" }}
                  onClick={() => { setSel({ r: 0, c }); setSelRange({ r1: 0, c1: c, r2: ROWS - 1, c2: c }); }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", position: "relative", height: "100%" }}>
                    {colLetter(c)}
                    {/* Col resize handle */}
                    <div
                      style={{ position: "absolute", right: 0, top: 0, width: 5, height: "100%", cursor: "col-resize", zIndex: 5 }}
                      onMouseDown={e => { e.stopPropagation(); startColResize(e, c); }}
                    />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: ROWS }, (_, r) => (
              <tr key={r}>
                {/* Row header */}
                <td
                  style={{ width: ROW_HEADER_WIDTH, minWidth: ROW_HEADER_WIDTH, height: rowHeights[r], background: "#f8f9fb", border: "1px solid #d1d5db", fontSize: 11, color: "#6b7280", textAlign: "center", position: "sticky", left: 0, zIndex: 5, cursor: "pointer", userSelect: "none" }}
                  onClick={() => { setSel({ r, c: 0 }); setSelRange({ r1: r, c1: 0, r2: r, c2: COLS - 1 }); }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", position: "relative", height: "100%" }}>
                    {r + 1}
                    <div style={{ position: "absolute", bottom: 0, left: 0, width: "100%", height: 5, cursor: "row-resize" }}
                      onMouseDown={e => { e.stopPropagation(); startRowResize(e, r); }} />
                  </div>
                </td>

                {/* Cells */}
                {Array.from({ length: COLS }, (_, c) => {
                  const cell = grid[r][c];
                  if (cell.mergedInto) return null;
                  const s = cell.style;
                  const isEditing = editCell?.r === r && editCell?.c === c;
                  const selected = isSel(r, c);
                  const isAnchor = sel?.r === r && sel?.c === c;
                  const colSpan = cell.merged?.cols ?? 1;
                  const rowSpan = cell.merged?.rows ?? 1;
                  const totalW = Array.from({ length: colSpan }, (_, i) => colWidths[c + i] ?? DEFAULT_COL_WIDTH).reduce((a, b) => a + b, 0);

                  const borderStyle = (side: "top" | "right" | "bottom" | "left") => {
                    if (s.borders?.[side]) return "1px solid #374151";
                    if (isAnchor) return side === "top" || side === "left" ? "2px solid #4f46e5" : side === "bottom" || side === "right" ? "2px solid #4f46e5" : "1px solid #d1d5db";
                    if (selected) return "1px solid #818cf8";
                    return "1px solid #d1d5db";
                  };

                  return (
                    <td
                      key={c}
                      colSpan={colSpan}
                      rowSpan={rowSpan}
                      style={{
                        width: totalW, minWidth: totalW,
                        height: rowHeights[r],
                        background: selected ? (s.bgColor ?? "#eef2ff") : (s.bgColor ?? "transparent"),
                        borderTop: borderStyle("top"),
                        borderRight: borderStyle("right"),
                        borderBottom: borderStyle("bottom"),
                        borderLeft: borderStyle("left"),
                        padding: 0, cursor: "cell", position: "relative",
                      }}
                      onClick={e => {
                        if (e.shiftKey && sel) {
                          setSelRange({ r1: Math.min(sel.r, r), c1: Math.min(sel.c, c), r2: Math.max(sel.r, r), c2: Math.max(sel.c, c) });
                        } else {
                          setSel({ r, c }); setSelRange(null);
                        }
                      }}
                      onDoubleClick={() => startEdit(r, c)}
                      onMouseDown={() => { isSelecting.current = true; setSel({ r, c }); setSelRange(null); }}
                      onMouseEnter={() => { if (isSelecting.current && sel) setSelRange({ r1: Math.min(sel.r, r), c1: Math.min(sel.c, c), r2: Math.max(sel.r, r), c2: Math.max(sel.c, c) }); }}
                      onMouseUp={() => { isSelecting.current = false; }}
                    >
                      {isEditing ? (
                        <input
                          ref={inputRef}
                          value={editVal}
                          onChange={e => setEditVal(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === "Enter") { commitEdit(); setSel({ r: r + 1, c }); }
                            if (e.key === "Tab") { e.preventDefault(); commitEdit(); setSel({ r, c: c + 1 }); }
                            if (e.key === "Escape") { setEditCell(null); }
                          }}
                          style={{
                            width: "100%", height: "100%", border: "none", outline: "none",
                            padding: "0 4px", fontSize: `${s.fontSize ?? 11}px`,
                            fontWeight: s.bold ? "bold" : "normal",
                            fontStyle: s.italic ? "italic" : "normal",
                            textDecoration: s.underline ? "underline" : "none",
                            textAlign: s.align ?? "left",
                            background: "transparent", fontFamily: "inherit",
                            color: s.fontColor ?? "#111",
                          }}
                        />
                      ) : (
                        <div style={{
                          padding: "0 4px",
                          fontSize: `${s.fontSize ?? 11}px`,
                          fontWeight: s.bold ? "bold" : "normal",
                          fontStyle: s.italic ? "italic" : "normal",
                          textDecoration: s.underline ? "underline" : "none",
                          textAlign: s.align ?? "left",
                          color: selected && !s.bgColor ? (s.fontColor ?? "#111") : (s.fontColor ?? "#111"),
                          whiteSpace: s.wrap ? "normal" : "nowrap",
                          overflow: "hidden",
                          textOverflow: s.wrap ? "clip" : "ellipsis",
                          height: "100%",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: s.align === "center" ? "center" : s.align === "right" ? "flex-end" : "flex-start",
                        }}>
                          {cell.value}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Status bar ── */}
      <div style={{ height: 22, background: "#f8f9fb", borderTop: "1px solid #e3e6ec", display: "flex", alignItems: "center", padding: "0 12px", fontSize: 11, color: "#9ca3af", gap: 16, flexShrink: 0 }}>
        <span>{selRange ? `${selRange.r2 - selRange.r1 + 1}R × ${selRange.c2 - selRange.c1 + 1}C selected` : cellAddr}</span>
        <span style={{ marginLeft: "auto" }}>
          {grid[0].filter(c => c.value.trim()).length} columns defined
        </span>
      </div>
    </div>
  );
}
