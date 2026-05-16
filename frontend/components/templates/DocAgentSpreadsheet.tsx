"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";

interface CellStyle {
  bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean;
  fontSize?: number; fontFamily?: string; fontColor?: string; bgColor?: string;
  align?: "left" | "center" | "right"; wrap?: boolean;
  borderAll?: boolean; borderOuter?: boolean;
}
interface Cell {
  value: string;
  style: CellStyle;
  mergeParent?: [number, number];
  mergeSpan?: { rows: number; cols: number };
  extractTarget?: boolean;
  repeatRow?: boolean;
}
export interface SheetSaveData {
  cells: Record<string, Cell>;
  colWidths: number[];
  merges: Record<string, { rows: number; cols: number }>;
  extractTargets: Array<{ r: number; c: number; label: string; isRepeat: boolean }>;
  repeatRows: number[];
}

interface Props {
  initialColumns?: { name: string; type: string; order: number }[];
  initialData?: SheetSaveData | null;
  onSheetsChange?: (data: SheetSaveData) => void;
  height?: number | string;
}

const ROWS = 50, COLS = 26, DCW = 120, DRH = 26, RHW = 52, CHH = 26;
const FONTS = ["Arial", "Calibri", "Segoe UI", "Times New Roman", "Georgia", "Courier New", "Verdana"];
const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72];
const COLORS = [
  "#000000","#434343","#666666","#999999","#b7b7b7","#cccccc","#d9d9d9","#ffffff",
  "#ff0000","#ff4500","#ff9900","#ffff00","#00ff00","#00ffff","#4a86e8","#0000ff",
  "#9900ff","#ff00ff","#ea9999","#f9cb9c","#ffe599","#b6d7a8","#a2c4c9","#a4c2f4",
  "#4285f4","#34a853","#fbbc05","#ea4335","#c27ba0","#674ea7","#e06666","#f6b26b",
];
const ck = (r: number, c: number) => `${r},${c}`;
const cl = (i: number) => { let r = "", n = i; do { r = String.fromCharCode(65 + (n % 26)) + r; n = Math.floor(n / 26) - 1; } while (n >= 0); return r; };

const IconUndo = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 10h10a8 8 0 0 1 8 8v2"/><path d="M3 10l6-6M3 10l6 6"/></svg>;
const IconRedo = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10H11a8 8 0 0 0-8 8v2"/><path d="M21 10l-6-6m6 6l-6 6"/></svg>;
const IconBold = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/></svg>;
const IconItalic = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="19" y1="4" x2="10" y2="4"/><line x1="14" y1="20" x2="5" y2="20"/><line x1="15" y1="4" x2="9" y2="20"/></svg>;
const IconUnderline = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"/><line x1="4" y1="21" x2="20" y2="21"/></svg>;
const IconStrike = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="4" y1="12" x2="20" y2="12"/><path d="M17.5 7C17.5 5.067 15.538 3.5 13 3.5c-2.538 0-4.5 1.567-4.5 3.5"/></svg>;
const IconAlignL = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/></svg>;
const IconAlignC = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>;
const IconAlignR = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="6" y1="18" x2="21" y2="18"/></svg>;
const IconBorderAll = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="1"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>;
const IconBorderOut = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="1"/></svg>;
const IconWrap = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><path d="M3 12h15a3 3 0 0 1 0 6H8"/><polyline points="10 15 7 18 10 21"/></svg>;
const IconExtract = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>;
const IconRepeat = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>;
const IconFx = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 19h6m2 0h6M9 4l-4 8 4 8m6-16l4 8-4 8"/></svg>;

export default function DocAgentSpreadsheet({ initialColumns = [], initialData, onSheetsChange, height = 500 }: Props) {
  const initCells = (): Record<string, Cell> => {
    if (initialData?.cells) return initialData.cells;
    const c: Record<string, Cell> = {};
    initialColumns.forEach((col, i) => {
      if (i < COLS) c[ck(0, i)] = { value: col.name, style: { bold: true, fontSize: 11 } };
    });
    return c;
  };

  const [cells, setCells] = useState<Record<string, Cell>>(initCells);
  const [colWidths, setColWidths] = useState<number[]>(() => initialData?.colWidths ?? Array(COLS).fill(DCW));
  const [merges, setMerges] = useState<Record<string, { rows: number; cols: number }>>(() => initialData?.merges ?? {});

  // FIX: Sync state when initialData arrives after mount.
  // useState initializer only runs once — if initialData is null on first render
  // (API still loading) and arrives later, cells/merges/colWidths never update.
  // We use a ref to track the last initialData we loaded so we only sync once
  // per unique initialData object (identified by savedAt timestamp).
  const loadedTimestampRef = useRef<string | null>(null);
  useEffect(() => {
    if (!initialData) return;
    // Use savedAt as a unique identifier for this version of the template
    const savedAt = (initialData as any).savedAt ?? JSON.stringify(Object.keys(initialData.cells ?? {}).slice(0, 3));
    if (loadedTimestampRef.current === savedAt) return; // already loaded this version
    loadedTimestampRef.current = savedAt;
    setCells(initialData.cells ?? {});
    setMerges(initialData.merges ?? {});
    setColWidths(initialData.colWidths ?? Array(COLS).fill(DCW));
    // Notify parent so sheetDataRef is populated — but only with the loaded data
    // NOT called again after user edits (notify is called by upd/markExtract etc.)
    onSheetsChange?.(initialData);
  }, [initialData]); // eslint-disable-line react-hooks/exhaustive-deps
  const [selR, setSelR] = useState(0);
  const [selC, setSelC] = useState(0);
  const [rng, setRng] = useState({ r1: 0, c1: 0, r2: 0, c2: 0 });
  const [ctrlSel, setCtrlSel] = useState<Set<string>>(new Set()); // Ctrl+click multi-select
  const [editR, setEditR] = useState<number | null>(null);
  const [editC, setEditC] = useState<number | null>(null);
  const [editVal, setEditVal] = useState("");
  const [hist, setHist] = useState<Record<string, Cell>[]>([]);
  const [redoStack, setRedoStack] = useState<Record<string, Cell>[]>([]);
  const [fcp, setFcp] = useState(false);
  const [bcp, setBcp] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const mouseDown = useRef(false);
  const clipboard = useRef<Record<string, Cell> | null>(null);

  const buildSaveData = useCallback((c: Record<string, Cell>, m: Record<string, { rows: number; cols: number }>, cw: number[]): SheetSaveData => {
    const extractTargets: Array<{ r: number; c: number; label: string; isRepeat: boolean }> = [];
    const repeatRowsSet = new Set<number>();
    Object.entries(c).forEach(([key, cell]) => {
      if (!cell) return;
      const [r, col] = key.split(",").map(Number);
      if (cell.repeatRow) repeatRowsSet.add(r);
      if (cell.extractTarget) {
        // Find the nearest label for this cell (look left, then above)
        let label = cell.value?.trim() ?? "";
        if (!label) {
          // Look left for a label
          for (let dc = 1; dc <= 3; dc++) {
            const left = c[`${r},${col - dc}`];
            if (left?.value?.trim()) { label = left.value.trim(); break; }
          }
        }
        if (!label) {
          // Look above for a label
          const above = c[`${r - 1},${col}`];
          if (above?.value?.trim()) label = above.value.trim();
        }
        extractTargets.push({ r, c: col, label, isRepeat: !!cell.repeatRow });
      }
    });
    return { cells: c, colWidths: cw, merges: m, extractTargets, repeatRows: [...repeatRowsSet].sort((a, b) => a - b) };
  }, []);

  const notify = useCallback((c: Record<string, Cell>, m: Record<string, { rows: number; cols: number }>, cw: number[]) => {
    onSheetsChange?.(buildSaveData(c, m, cw));
  }, [onSheetsChange, buildSaveData]);

  const cs: CellStyle = useMemo(() => cells[ck(selR, selC)]?.style ?? {}, [cells, selR, selC]);
  const curCell = useMemo(() => cells[ck(selR, selC)], [cells, selR, selC]);

  const ph = useCallback(() => { setHist(h => [...h.slice(-49), { ...cells }]); setRedoStack([]); }, [cells]);

  const upd = useCallback((next: Record<string, Cell>, nm?: Record<string, { rows: number; cols: number }>, ncw?: number[]) => {
    setCells(next);
    const m = nm ?? merges, cw = ncw ?? colWidths;
    if (nm) setMerges(nm);
    notify(next, m, cw);
  }, [merges, colWidths, notify]);

  const applyStyle = useCallback((patch: Partial<CellStyle>) => {
    ph();
    const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
    const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
    const next = { ...cells };
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
      const k = ck(r, c);
      next[k] = { ...(next[k] ?? { value: "", style: {} }), style: { ...(next[k]?.style ?? {}), ...patch } };
    }
    upd(next);
  }, [cells, selR, selC, rng, ph, upd]);

  // All currently selected cell keys — range union ctrl-clicked cells
  const allSelectedKeys = useMemo(() => {
    const keys = new Set<string>(ctrlSel);
    const r1 = Math.min(rng.r1, rng.r2), r2 = Math.max(rng.r1, rng.r2);
    const c1 = Math.min(rng.c1, rng.c2), c2 = Math.max(rng.c1, rng.c2);
    for (let r = r1; r <= r2; r++)
      for (let c = c1; c <= c2; c++)
        keys.add(ck(r, c));
    return keys;
  }, [rng, ctrlSel]);

  const markExtract = useCallback(() => {
    ph();
    const next = { ...cells };
    // Check if first selected cell is already marked — toggle all
    const firstKey = allSelectedKeys.values().next().value ?? ck(selR, selC);
    const alreadyMarked = next[firstKey]?.extractTarget && !next[firstKey]?.repeatRow;
    for (const k of allSelectedKeys) {
      next[k] = { ...(next[k] ?? { value: "", style: {} }), extractTarget: !alreadyMarked, repeatRow: false };
    }
    upd(next);
    // Clear ctrl selection after applying
    setCtrlSel(new Set());
  }, [cells, allSelectedKeys, selR, selC, ph, upd]);

  const markRepeat = useCallback(() => {
    ph();
    const r1 = Math.min(rng.r1, rng.r2);
    const r2 = Math.max(rng.r1, rng.r2);
    // Also include rows from ctrl-selected cells
    const ctrlRows = new Set<number>();
    ctrlSel.forEach(k => { const [r] = k.split(",").map(Number); ctrlRows.add(r); });
    const next = { ...cells };
    const alreadyRepeat = Object.entries(next).some(([k, cell]) => {
      const [r] = k.split(",").map(Number);
      return (r >= r1 && r <= r2 || ctrlRows.has(r)) && cell.repeatRow;
    });
    // Apply to range rows
    for (let r = r1; r <= r2; r++) for (let c = 0; c < COLS; c++) {
      const k = ck(r, c);
      next[k] = { ...(next[k] ?? { value: "", style: {} }), repeatRow: !alreadyRepeat, extractTarget: !alreadyRepeat };
    }
    // Apply to ctrl-selected rows
    ctrlRows.forEach(r => {
      if (r < r1 || r > r2) {
        for (let c = 0; c < COLS; c++) {
          const k = ck(r, c);
          next[k] = { ...(next[k] ?? { value: "", style: {} }), repeatRow: !alreadyRepeat, extractTarget: !alreadyRepeat };
        }
      }
    });
    upd(next);
    setCtrlSel(new Set());
  }, [cells, selR, selC, rng, ctrlSel, ph, upd]);

  const doUndo = useCallback(() => {
    if (!hist.length) return;
    setRedoStack(r => [...r, cells]);
    const p = hist[hist.length - 1]; setHist(h => h.slice(0, -1)); setCells(p); notify(p, merges, colWidths);
  }, [hist, cells, merges, colWidths, notify]);

  const doRedo = useCallback(() => {
    if (!redoStack.length) return;
    setHist(h => [...h, cells]);
    const n = redoStack[redoStack.length - 1]; setRedoStack(r => r.slice(0, -1)); setCells(n); notify(n, merges, colWidths);
  }, [redoStack, cells, merges, colWidths, notify]);

  // commitEdit with direction — SINGLE source of navigation after edit
  const commitEdit = useCallback((dr: number = 0, dc: number = 0) => {
    if (editR === null || editC === null) return;
    ph();
    const k = ck(editR, editC);
    const next = { ...cells, [k]: { ...(cells[k] ?? { style: {} }), value: editVal } };
    const savedR = editR, savedC = editC;
    setEditR(null); setEditC(null); setEditVal("");
    upd(next);
    if (dr !== 0 || dc !== 0) {
      const nr = Math.max(0, Math.min(ROWS - 1, savedR + dr));
      const nc = Math.max(0, Math.min(COLS - 1, savedC + dc));
      setSelR(nr); setSelC(nc); setRng({ r1: nr, c1: nc, r2: nr, c2: nc });
    }
  }, [editR, editC, editVal, cells, ph, upd]);

  const startEdit = useCallback((r: number, c: number, initChar?: string) => {
    setEditR(r); setEditC(c);
    setEditVal(initChar !== undefined ? initChar : (cells[ck(r, c)]?.value ?? ""));
    setTimeout(() => {
      const inp = inputRef.current;
      if (inp) { inp.focus(); const l = inp.value.length; inp.setSelectionRange(initChar !== undefined ? l : 0, l); }
    }, 0);
  }, [cells]);

  const nav = useCallback((dr: number, dc: number) => {
    const nr = Math.max(0, Math.min(ROWS - 1, selR + dr));
    const nc = Math.max(0, Math.min(COLS - 1, selC + dc));
    setSelR(nr); setSelC(nc); setRng({ r1: nr, c1: nc, r2: nr, c2: nc });
  }, [selR, selC]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const a = document.activeElement as HTMLElement;
      // If focus is in any input outside the grid, ignore
      if (a && (a.tagName === "INPUT" || a.tagName === "SELECT" || a.tagName === "TEXTAREA") && !a.dataset.grid) return;
      // If we're editing a cell, the cell input handles keys
      if (editR !== null) return;

      if (e.ctrlKey || e.metaKey) {
        if (e.key === "z") { e.preventDefault(); doUndo(); return; }
        if (e.key === "y") { e.preventDefault(); doRedo(); return; }
        if (e.key === "b") { e.preventDefault(); applyStyle({ bold: !cs.bold }); return; }
        if (e.key === "i") { e.preventDefault(); applyStyle({ italic: !cs.italic }); return; }
        if (e.key === "u") { e.preventDefault(); applyStyle({ underline: !cs.underline }); return; }
        if (e.key === "c") {
          e.preventDefault();
          const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
          const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
          const copied: Record<string, Cell> = {};
          for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
            const k = ck(r, c); if (cells[k]) copied[ck(r - r1, c - c1)] = JSON.parse(JSON.stringify(cells[k]));
          }
          clipboard.current = copied;
          return;
        }
        if (e.key === "x") {
          e.preventDefault();
          const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
          const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
          const copied: Record<string, Cell> = {};
          for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
            const k = ck(r, c); if (cells[k]) copied[ck(r - r1, c - c1)] = JSON.parse(JSON.stringify(cells[k]));
          }
          clipboard.current = copied;
          ph();
          const next = { ...cells };
          for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
            const k = ck(r, c); if (next[k]) next[k] = { ...next[k], value: "" };
          }
          upd(next);
          return;
        }
        if (e.key === "v" && clipboard.current) {
          e.preventDefault(); ph();
          const copied = clipboard.current;
          const next = { ...cells };
          Object.entries(copied).forEach(([relKey, cell]) => {
            const [dr, dc] = relKey.split(",").map(Number);
            const tr = selR + dr, tc = selC + dc;
            if (tr < ROWS && tc < COLS) {
              const k = ck(tr, tc);
              next[k] = JSON.parse(JSON.stringify(cell));
              delete next[k].mergeParent; delete next[k].mergeSpan;
            }
          });
          upd(next);
          return;
        }
        return;
      }

      // Arrow navigation — with Ctrl and Shift modifiers
      if (["ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.key)) {
        e.preventDefault();
        const dr = e.key === "ArrowUp" ? -1 : e.key === "ArrowDown" ? 1 : 0;
        const dc = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;

        if (e.ctrlKey || e.metaKey) {
          // Ctrl+Arrow — jump to edge of data (like Excel)
          let r = selR + dr, c = selC + dc;
          // Find last cell with content in this direction
          while (r >= 0 && r < ROWS && c >= 0 && c < COLS) {
            if (cells[ck(r, c)]?.value) {
              // Continue while there's content
              const nextR = r + dr, nextC = c + dc;
              if (nextR < 0 || nextR >= ROWS || nextC < 0 || nextC >= COLS || !cells[ck(nextR, nextC)]?.value) break;
              r = nextR; c = nextC;
            } else break;
          }
          r = Math.max(0, Math.min(ROWS - 1, r));
          c = Math.max(0, Math.min(COLS - 1, c));
          if (e.shiftKey) {
            // Ctrl+Shift+Arrow — extend selection to edge
            setRng(p => ({ ...p, r2: r, c2: c }));
          } else {
            setSelR(r); setSelC(c);
            setRng({ r1: r, c1: c, r2: r, c2: c });
            setCtrlSel(new Set());
          }
        } else if (e.shiftKey) {
          // Shift+Arrow — extend selection by one cell
          setRng(p => ({
            ...p,
            r2: Math.max(0, Math.min(ROWS - 1, p.r2 + dr)),
            c2: Math.max(0, Math.min(COLS - 1, p.c2 + dc)),
          }));
        } else {
          // Normal arrow — move selection
          nav(dr, dc);
          setCtrlSel(new Set());
        }
        return;
      }

      else if (e.key === "Enter") { e.preventDefault(); nav(1, 0); }
      else if (e.key === "F2") { e.preventDefault(); startEdit(selR, selC); }
      else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault(); ph();
        const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
        const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
        const next = { ...cells };
        for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
          const k = ck(r, c); if (next[k]) next[k] = { ...next[k], value: "" };
        }
        upd(next);
      }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        startEdit(selR, selC, e.key);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [editR, selR, selC, rng, cells, cs, nav, startEdit, applyStyle, doUndo, doRedo, ph, upd]);

  const mergeCells = useCallback(() => {
    const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
    const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
    if (r1 === r2 && c1 === c2) return; ph();
    const nm = { ...merges, [ck(r1, c1)]: { rows: r2 - r1 + 1, cols: c2 - c1 + 1 } };
    const next = { ...cells };
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) {
      if (r !== r1 || c !== c1) next[ck(r, c)] = { ...(next[ck(r, c)] ?? { style: {} }), value: "", mergeParent: [r1, c1] };
    }
    next[ck(r1, c1)] = { ...(next[ck(r1, c1)] ?? { style: {} }), value: next[ck(r1, c1)]?.value ?? "", mergeSpan: { rows: r2 - r1 + 1, cols: c2 - c1 + 1 } };
    setSelR(r1); setSelC(c1); setRng({ r1, c1, r2: r1, c2: c1 }); upd(next, nm);
  }, [selR, selC, rng, cells, merges, ph, upd]);

  const splitCells = useCallback(() => {
    const k = ck(selR, selC); if (!merges[k]) return; ph();
    const { rows, cols } = merges[k]; const nm = { ...merges }; delete nm[k];
    const next = { ...cells };
    for (let r = selR; r < selR + rows; r++) for (let c = selC; c < selC + cols; c++) {
      if (r !== selR || c !== selC) { const nc = { ...(next[ck(r, c)] ?? { style: {} }) }; delete nc.mergeParent; next[ck(r, c)] = nc; }
    }
    const nc = { ...next[k] }; delete nc.mergeSpan; next[k] = nc; upd(next, nm);
  }, [selR, selC, cells, merges, ph, upd]);

  const startColResize = useCallback((e: React.MouseEvent, c: number) => {
    e.preventDefault(); e.stopPropagation();
    const sx = e.clientX, sw = colWidths[c];
    const mv = (ev: MouseEvent) => {
      const nw = Math.max(30, sw + ev.clientX - sx);
      setColWidths(p => { const n = [...p]; n[c] = nw; return n; });
    };
    const up = (ev: MouseEvent) => {
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
      // Notify parent with updated colWidths so the new width is saved
      const nw = Math.max(30, sw + ev.clientX - sx);
      setColWidths(p => {
        const n = [...p]; n[c] = nw;
        notify(cells, merges, n);
        return n;
      });
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  }, [colWidths, cells, merges, notify]);

  const inRange = (r: number, c: number) => {
    if (ctrlSel.size > 0 && ctrlSel.has(ck(r, c))) return true;
    const r1 = Math.min(selR, rng.r2), r2 = Math.max(selR, rng.r2);
    const c1 = Math.min(selC, rng.c2), c2 = Math.max(selC, rng.c2);
    return r >= r1 && r <= r2 && c >= c1 && c <= c2;
  };

  // All currently selected cell keys (range + ctrl-selected)
  const extractCount = useMemo(() => Object.values(cells).filter(c => c?.extractTarget && !c?.repeatRow).length, [cells]);
  const repeatRowCount = useMemo(() => new Set(Object.entries(cells).filter(([, c]) => c?.repeatRow).map(([k]) => k.split(",")[0])).size, [cells]);

  const tb = (active = false): React.CSSProperties => ({
    display: "flex", alignItems: "center", justifyContent: "center",
    padding: "3px 7px", minWidth: 28, height: 28,
    borderRadius: 5, border: `1px solid ${active ? "#4f46e5" : "transparent"}`,
    background: active ? "#ede9fe" : "transparent",
    color: active ? "#4f46e5" : "#374151",
    cursor: "pointer", userSelect: "none" as const, transition: "all 0.1s", fontSize: 12, fontFamily: "inherit",
  });
  const sep: React.CSSProperties = { width: 1, height: 20, background: "#e5e7eb", margin: "0 3px", flexShrink: 0 };

  const ColorPicker = ({ onPick, onClose }: { onPick: (c: string) => void; onClose: () => void }) => (
    <div onClick={e => e.stopPropagation()} style={{ position: "absolute", top: 34, left: 0, zIndex: 300, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, padding: 8, boxShadow: "0 4px 16px rgba(0,0,0,0.12)", display: "grid", gridTemplateColumns: "repeat(8,22px)", gap: 3, width: 208 }}>
      <div onClick={() => { onPick(""); onClose(); }} style={{ width: 22, height: 22, background: "#fff", border: "1px solid #ddd", borderRadius: 3, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#999" }}>x</div>
      {COLORS.map(c => (
        <div key={c} onClick={() => { onPick(c); onClose(); }}
          style={{ width: 22, height: 22, background: c, borderRadius: 3, cursor: "pointer", border: c === "#ffffff" ? "1px solid #ddd" : "none" }}
          onMouseEnter={e => (e.currentTarget.style.transform = "scale(1.2)")}
          onMouseLeave={e => (e.currentTarget.style.transform = "scale(1)")}
        />
      ))}
    </div>
  );

  const isRepeatRow = (r: number) => Array.from({ length: 3 }, (_, c) => cells[ck(r, c)]?.repeatRow).some(Boolean);
  const formulaVal = editR !== null ? editVal : (cells[ck(selR, selC)]?.value ?? "");

  return (
    <div
      style={{ height, display: "flex", flexDirection: "column", background: "#fff", userSelect: "none", fontSize: 12, fontFamily: "Segoe UI,system-ui,sans-serif" }}
      onClick={() => { setFcp(false); setBcp(false); }}
    >
      {/* TOOLBAR */}
      <div style={{ flexShrink: 0, background: "#f8f9fb", borderBottom: "1px solid #e5e7eb", padding: "4px 8px", display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap", minHeight: 38 }}>
        <button style={tb()} onClick={doUndo} title="Undo (Ctrl+Z)"><IconUndo /></button>
        <button style={tb()} onClick={doRedo} title="Redo (Ctrl+Y)"><IconRedo /></button>
        <div style={sep} />
        <select value={cs.fontFamily ?? "Arial"} onChange={e => applyStyle({ fontFamily: e.target.value })}
          style={{ height: 28, border: "1px solid #e5e7eb", borderRadius: 5, fontSize: 12, padding: "0 4px", background: "#fff", cursor: "pointer", fontFamily: cs.fontFamily ?? "Arial", minWidth: 100 }}>
          {FONTS.map(f => <option key={f} style={{ fontFamily: f }}>{f}</option>)}
        </select>
        <select value={cs.fontSize ?? 11} onChange={e => applyStyle({ fontSize: parseInt(e.target.value) })}
          style={{ height: 28, width: 54, border: "1px solid #e5e7eb", borderRadius: 5, fontSize: 12, padding: "0 4px", background: "#fff", cursor: "pointer" }}>
          {SIZES.map(s => <option key={s}>{s}</option>)}
        </select>
        <div style={sep} />
        <button style={tb(!!cs.bold)} onClick={() => applyStyle({ bold: !cs.bold })} title="Bold (Ctrl+B)"><IconBold /></button>
        <button style={tb(!!cs.italic)} onClick={() => applyStyle({ italic: !cs.italic })} title="Italic (Ctrl+I)"><IconItalic /></button>
        <button style={tb(!!cs.underline)} onClick={() => applyStyle({ underline: !cs.underline })} title="Underline (Ctrl+U)"><IconUnderline /></button>
        <button style={tb(!!cs.strike)} onClick={() => applyStyle({ strike: !cs.strike })} title="Strikethrough"><IconStrike /></button>
        <div style={sep} />
        <div style={{ position: "relative" }} onClick={e => e.stopPropagation()}>
          <button style={{ ...tb(), flexDirection: "column", gap: 1 }} onClick={() => { setFcp(v => !v); setBcp(false); }} title="Font color">
            <span style={{ fontSize: 13, fontWeight: 700, color: cs.fontColor ?? "#000", lineHeight: 1 }}>A</span>
            <div style={{ width: 16, height: 3, background: cs.fontColor ?? "#000", borderRadius: 1 }} />
          </button>
          {fcp && <ColorPicker onPick={c => applyStyle({ fontColor: c || undefined })} onClose={() => setFcp(false)} />}
        </div>
        <div style={{ position: "relative" }} onClick={e => e.stopPropagation()}>
          <button style={{ ...tb(), flexDirection: "column", gap: 1 }} onClick={() => { setBcp(v => !v); setFcp(false); }} title="Fill color">
            <div style={{ width: 16, height: 12, background: cs.bgColor ?? "#ffff00", border: "1px solid #ccc", borderRadius: 2 }} />
            <div style={{ width: 16, height: 3, background: cs.bgColor ?? "#ffff00", borderRadius: 1 }} />
          </button>
          {bcp && <ColorPicker onPick={c => applyStyle({ bgColor: c || undefined })} onClose={() => setBcp(false)} />}
        </div>
        <div style={sep} />
        <button style={tb(!cs.align || cs.align === "left")} onClick={() => applyStyle({ align: "left" })} title="Align left"><IconAlignL /></button>
        <button style={tb(cs.align === "center")} onClick={() => applyStyle({ align: "center" })} title="Center"><IconAlignC /></button>
        <button style={tb(cs.align === "right")} onClick={() => applyStyle({ align: "right" })} title="Align right"><IconAlignR /></button>
        <div style={sep} />
        <button style={tb(!!cs.borderAll)} onClick={() => applyStyle({ borderAll: !cs.borderAll, borderOuter: false })} title="All borders"><IconBorderAll /></button>
        <button style={tb(!!cs.borderOuter)} onClick={() => applyStyle({ borderOuter: !cs.borderOuter, borderAll: false })} title="Outer border"><IconBorderOut /></button>
        <div style={sep} />
        <button style={tb()} onClick={mergeCells} title="Merge cells"><span style={{ fontSize: 11, fontWeight: 500 }}>Merge</span></button>
        <button style={tb()} onClick={splitCells} title="Split merged"><span style={{ fontSize: 11, fontWeight: 500 }}>Split</span></button>
        <div style={sep} />
        <button style={tb(!!cs.wrap)} onClick={() => applyStyle({ wrap: !cs.wrap })} title="Wrap text"><IconWrap /></button>
        <div style={sep} />
        <button
          style={{ ...tb(!!curCell?.extractTarget && !curCell?.repeatRow), background: curCell?.extractTarget && !curCell?.repeatRow ? "#dcfce7" : "transparent", border: `1px solid ${curCell?.extractTarget && !curCell?.repeatRow ? "#16a34a" : "#e5e7eb"}`, color: "#15803d", gap: 5, padding: "3px 10px", minWidth: "auto" }}
          onClick={markExtract} title="Mark cell for AI extraction"
        >
          <IconExtract />
          <span style={{ fontSize: 11, fontWeight: 600 }}>Extract here</span>
        </button>
        <button
          style={{ ...tb(!!curCell?.repeatRow), background: curCell?.repeatRow ? "#dbeafe" : "transparent", border: `1px solid ${curCell?.repeatRow ? "#2563eb" : "#e5e7eb"}`, color: "#1d4ed8", gap: 5, padding: "3px 10px", minWidth: "auto" }}
          onClick={markRepeat} title="Repeat row for each line item"
        >
          <IconRepeat />
          <span style={{ fontSize: 11, fontWeight: 600 }}>Repeat row</span>
        </button>
        <div style={sep} />
        <button style={{ ...tb(), color: "#6b7280", fontSize: 11 }}
          onClick={() => applyStyle({ bold: false, italic: false, underline: false, strike: false, fontColor: undefined, bgColor: undefined, align: undefined, borderAll: false, borderOuter: false, wrap: false, fontSize: 11, fontFamily: undefined })}
          title="Clear formatting">Clear
        </button>
      </div>

      {/* FORMULA BAR */}
      <div style={{ flexShrink: 0, display: "flex", alignItems: "center", borderBottom: "1px solid #e5e7eb", background: "#fff", height: 28 }}>
        <div style={{ width: 72, textAlign: "center", borderRight: "1px solid #e5e7eb", fontSize: 12, fontWeight: 600, color: "#374151", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {cl(selC)}{selR + 1}
        </div>
        <div style={{ width: 32, borderRight: "1px solid #e5e7eb", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#9ca3af", flexShrink: 0 }}>
          <IconFx />
        </div>
        <input
          value={formulaVal}
          onChange={e => {
            if (editR === selR && editC === selC) {
              setEditVal(e.target.value);
            } else {
              setEditR(selR);
              setEditC(selC);
              setEditVal(e.target.value);
            }
          }}
          onFocus={() => {
            if (editR !== selR || editC !== selC) {
              setEditR(selR);
              setEditC(selC);
              setEditVal(cells[ck(selR, selC)]?.value ?? "");
            }
          }}
          onBlur={() => {
            if (editR !== null && editC !== null) {
              commitEdit(0, 0);
            }
          }}
          onKeyDown={e => {
            e.stopPropagation();
            if (e.key === "Enter") { e.preventDefault(); commitEdit(0, 0); }
            if (e.key === "Escape") { e.preventDefault(); setEditR(null); setEditC(null); setEditVal(""); }
          }}
          style={{ flex: 1, height: "100%", border: "none", outline: "none", padding: "0 10px", fontSize: 12, color: "#374151", background: "transparent", fontFamily: "inherit" }}
          placeholder="Click a cell to edit..."
        />
        {curCell?.extractTarget && (
          <div style={{ flexShrink: 0, padding: "0 12px", borderLeft: "1px solid #e5e7eb", display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: curCell.repeatRow ? "#2563eb" : "#16a34a", display: "inline-block" }} />
            <span style={{ fontSize: 11, color: curCell.repeatRow ? "#1d4ed8" : "#15803d", fontWeight: 600 }}>
              {curCell.repeatRow ? "Repeat row" : "Extract target"}
            </span>
          </div>
        )}
      </div>

      {/* GRID */}
      <div style={{ flex: 1, overflow: "auto" }} onMouseUp={() => { mouseDown.current = false; }}>
        <table style={{ borderCollapse: "collapse", tableLayout: "fixed", minWidth: "max-content" }}>
          <thead>
            <tr>
              <th style={{ width: RHW, minWidth: RHW, height: CHH, background: "#f1f3f9", border: "1px solid #d1d5db", position: "sticky", top: 0, left: 0, zIndex: 20 }} />
              {Array.from({ length: COLS }, (_, c) => (
                <th key={c}
                  style={{ width: colWidths[c], minWidth: colWidths[c], height: CHH, background: "#f1f3f9", border: "1px solid #d1d5db", fontSize: 11, fontWeight: 600, color: "#6b7280", textAlign: "center", position: "sticky", top: 0, zIndex: 10, userSelect: "none", cursor: "pointer" }}
                  onClick={() => { setSelR(0); setSelC(c); setRng({ r1: 0, c1: c, r2: ROWS - 1, c2: c }); }}>
                  <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
                    {cl(c)}
                    <div onMouseDown={e => startColResize(e, c)} style={{ position: "absolute", right: 0, top: 0, width: 5, height: "100%", cursor: "col-resize", zIndex: 5 }} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: ROWS }, (_, r) => {
              const rowIsRepeat = isRepeatRow(r);
              return (
                <tr key={r} style={{ height: DRH }}>
                  <td
                    style={{ width: RHW, minWidth: RHW, height: DRH, maxHeight: DRH, overflow: "hidden", background: rowIsRepeat ? "#dbeafe" : "#f1f3f9", border: "1px solid #d1d5db", fontSize: 10, color: rowIsRepeat ? "#1d4ed8" : "#6b7280", textAlign: "center", position: "sticky", left: 0, zIndex: 5, cursor: "pointer", userSelect: "none", fontWeight: rowIsRepeat ? 700 : 400 }}
                    onClick={() => { setSelR(r); setSelC(0); setRng({ r1: r, c1: 0, r2: r, c2: COLS - 1 }); }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 1 }}>
                      <span>{r + 1}</span>
                      {rowIsRepeat && <span style={{ fontSize: 8 }}>RPT</span>}
                    </div>
                  </td>
                  {Array.from({ length: COLS }, (_, c) => {
                    const k = ck(r, c);
                    const cell = cells[k];
                    if (cell?.mergeParent) return null;
                    const span = merges[k];
                    const cs2 = span?.cols ?? 1, rs2 = span?.rows ?? 1;
                    const s = cell?.style ?? {};
                    const isEdit = editR === r && editC === c;
                    const isSel = selR === r && selC === c;
                    const ir = inRange(r, c);
                    const isCtrlSel = ctrlSel.has(ck(r, c));
                    const isExtract = cell?.extractTarget && !cell?.repeatRow;
                    const isRepeat = cell?.repeatRow;
                    const tw = Array.from({ length: cs2 }, (_, i) => colWidths[c + i] ?? DCW).reduce((a, b) => a + b, 0);
                    const bg = s.bgColor ?? (isRepeat ? "rgba(37,99,235,0.06)" : isExtract ? "rgba(22,163,74,0.06)" : isCtrlSel ? "rgba(79,70,229,0.12)" : ir ? "rgba(79,70,229,0.06)" : "#fff");
                    const bd = isSel ? "2px solid #4f46e5" : isCtrlSel ? "2px solid #7c3aed" : isRepeat ? "1px solid #93c5fd" : isExtract ? "1px solid #86efac" : ir ? "1px solid #a5b4fc" : "1px solid #e5e7eb";
                    const finalBd = s.borderAll ? "1px solid #374151" : s.borderOuter && isSel ? "2px solid #374151" : bd;
                    const ff = s.fontFamily ?? "Segoe UI,system-ui,sans-serif";
                    const fs = s.fontSize ?? 11;
                    const fw = s.bold ? "600" : "normal";
                    const fc = s.fontColor ?? "#111827";
                    const td2 = [s.underline && "underline", s.strike && "line-through"].filter(Boolean).join(" ") || "none";

                    return (
                      <td key={c} colSpan={cs2} rowSpan={rs2}
                        style={{ width: tw, minWidth: tw, height: DRH, maxHeight: DRH, overflow: "hidden", background: bg, border: finalBd, padding: 0, cursor: "cell", position: "relative", verticalAlign: "middle" }}
                        onClick={e => {
                          if (e.ctrlKey || e.metaKey) {
                            // Ctrl/Cmd+click — toggle cell in multi-select
                            setCtrlSel(prev => {
                              const next = new Set(prev);
                              const k = ck(r, c);
                              if (next.has(k)) next.delete(k); else next.add(k);
                              return next;
                            });
                          } else if (e.shiftKey) {
                            setRng(p => ({ ...p, r2: r, c2: c }));
                          } else {
                            setSelR(r); setSelC(c);
                            setRng({ r1: r, c1: c, r2: r, c2: c });
                            setCtrlSel(new Set()); // clear ctrl selection on normal click
                          }
                        }}
                        onDoubleClick={() => startEdit(r, c)}
                        onMouseDown={e => { if (e.button !== 0) return; mouseDown.current = true; setSelR(r); setSelC(c); setRng({ r1: r, c1: c, r2: r, c2: c }); }}
                        onMouseEnter={() => { if (mouseDown.current) setRng(p => ({ ...p, r2: r, c2: c })); }}
                      >
                        {(isExtract || isRepeat) && (
                          <div style={{ position: "absolute", top: 2, right: 3, width: 6, height: 6, borderRadius: "50%", background: isRepeat ? "#2563eb" : "#16a34a", zIndex: 2 }} />
                        )}
                        {isEdit ? (
                          <input
                            ref={inputRef}
                            data-grid="true"
                            value={editVal}
                            onChange={e => setEditVal(e.target.value)}
                            onBlur={() => commitEdit(0, 0)}
                            onKeyDown={e => {
                              e.stopPropagation();
                              if (e.key === "Enter") { e.preventDefault(); commitEdit(1, 0); }
                              else if (e.key === "Tab") { e.preventDefault(); commitEdit(0, 1); }
                              else if (e.key === "Escape") { e.preventDefault(); setEditR(null); setEditC(null); setEditVal(""); }
                            }}
                            style={{ width: "100%", height: `${DRH}px`, maxHeight: `${DRH}px`, border: "none", outline: "none", padding: "0 6px", fontFamily: ff, fontSize: `${fs}px`, fontWeight: fw, fontStyle: s.italic ? "italic" : "normal", background: "transparent", color: fc, textAlign: s.align ?? "left", overflow: "hidden" }}
                          />
                        ) : (
                          <div style={{ padding: "0 6px", fontFamily: ff, fontSize: `${fs}px`, fontWeight: fw, fontStyle: s.italic ? "italic" : "normal", textDecoration: td2, color: fc, textAlign: s.align ?? "left", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", height: `${DRH}px`, maxHeight: `${DRH}px`, display: "flex", alignItems: "center", justifyContent: s.align === "center" ? "center" : s.align === "right" ? "flex-end" : "flex-start", cursor: "cell" }}>
                            {cell?.value ?? ""}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* STATUS BAR */}
      <div style={{ flexShrink: 0, height: 26, background: "#f8f9fb", borderTop: "1px solid #e5e7eb", display: "flex", alignItems: "center", padding: "0 12px", fontSize: 11, color: "#9ca3af", gap: 16 }}>
        <span style={{ color: "#6b7280", fontWeight: 500 }}>{cl(selC)}{selR + 1}</span>
        {ctrlSel.size > 0 && (
          <span style={{ color: "#7c3aed", fontWeight: 600, fontSize: 10 }}>
            +{ctrlSel.size} Ctrl-selected
          </span>
        )}
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#16a34a", display: "inline-block" }} />
          <span style={{ color: extractCount > 0 ? "#15803d" : "#9ca3af", fontWeight: extractCount > 0 ? 600 : 400 }}>
            {extractCount} extract target{extractCount !== 1 ? "s" : ""}
          </span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#2563eb", display: "inline-block" }} />
          <span style={{ color: repeatRowCount > 0 ? "#1d4ed8" : "#9ca3af", fontWeight: repeatRowCount > 0 ? 600 : 400 }}>
            {repeatRowCount} repeat row{repeatRowCount !== 1 ? "s" : ""}
          </span>
        </span>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#d1d5db" }}>
          Ctrl+click multi-select · Shift+click/arrow range · Ctrl+arrow jump
        </span>
      </div>
    </div>
  );
}
