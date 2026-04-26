"use client";

import { useEffect, useRef, useState } from "react";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  colTypes?: Record<number, "header" | "lineitem">;
  onColumnsChange?: (cols: TemplateColumn[]) => void;
  onColumnSelect?: (idx: number) => void;
  height?: number;
}

export default function FortuneSheetEditor({
  initialColumns = [],
  colTypes = {},
  onColumnsChange,
  onColumnSelect,
  height = 500,
}: Props) {
  const [Workbook, setWorkbook] = useState<React.ComponentType<any> | null>(null);
  const [sheets, setSheets] = useState<any[]>([]);
  const initialized = useRef(false);

  // Build initial sheet data from columns
  function buildSheetData(cols: TemplateColumn[], types: Record<number, "header" | "lineitem">) {
    // Row 0 = column headers (bold, colored by type)
    const celldata: any[] = [];

    const seedCols = cols.length > 0 ? cols : [
      { name: "Invoice Number", type: "Text", order: 0 },
      { name: "Vendor Name",    type: "Text", order: 1 },
      { name: "Invoice Date",   type: "Date", order: 2 },
      { name: "Total Amount",   type: "Currency", order: 3 },
      { name: "Item Description", type: "Text", order: 4 },
      { name: "SKU",            type: "Text", order: 5 },
      { name: "GTIN",           type: "Text", order: 6 },
      { name: "Unit Price",     type: "Currency", order: 7 },
      { name: "Qty",            type: "Number", order: 8 },
      { name: "Subtotal",       type: "Currency", order: 9 },
    ];

    seedCols.forEach((col, c) => {
      const isLineItem = (types[c] ?? (c >= 4 ? "lineitem" : "header")) === "lineitem";
      celldata.push({
        r: 0, c,
        v: {
          v: col.name,
          m: col.name,
          ct: { fa: "@", t: "s" },
          bl: 1, // bold
          fc: isLineItem ? "#15803d" : "#1d4ed8",
          bg: isLineItem ? "#f0fdf4" : "#eff6ff",
        },
      });
    });

    // 8 blank preview rows
    for (let r = 1; r <= 8; r++) {
      for (let c = 0; c < seedCols.length; c++) {
        celldata.push({ r, c, v: { v: "", m: "" } });
      }
    }

    return [{
      name: "Sheet 1",
      id: "sheet1",
      status: 1,
      order: 0,
      hide: 0,
      row: 20,
      column: Math.max(seedCols.length + 2, 12),
      defaultRowHeight: 25,
      defaultColWidth: 120,
      celldata,
      config: {
        rowlen: { 0: 28 },
        colhidden: {},
      },
    }];
  }

  // Load fortune-sheet lazily (client-only)
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    import("@fortune-sheet/react").then((mod) => {
      setWorkbook(() => mod.Workbook);
      setSheets(buildSheetData(initialColumns, colTypes));
    }).catch(err => {
      console.error("FortuneSheet load failed:", err);
    });
  }, []);

  // Update sheet when colTypes change (recolor headers)
  useEffect(() => {
    if (!sheets.length) return;
    setSheets(prev => {
      if (!prev.length) return prev;
      const sheet = { ...prev[0] };
      const newCelldata = (sheet.celldata || []).map((cell: any) => {
        if (cell.r === 0) {
          const isLineItem = (colTypes[cell.c] ?? (cell.c >= 4 ? "lineitem" : "header")) === "lineitem";
          return {
            ...cell,
            v: {
              ...cell.v,
              fc: isLineItem ? "#15803d" : "#1d4ed8",
              bg: isLineItem ? "#f0fdf4" : "#eff6ff",
            },
          };
        }
        return cell;
      });
      return [{ ...sheet, celldata: newCelldata }];
    });
  }, [colTypes]);

  function handleChange(data: any[]) {
    if (!data?.length) return;
    const sheet = data[0];
    const celldata: any[] = sheet.celldata || [];

    // Extract column names from row 0
    const cols: TemplateColumn[] = [];
    const row0 = celldata.filter((c: any) => c.r === 0);
    row0.sort((a: any, b: any) => a.c - b.c);

    for (const cell of row0) {
      const val = cell.v?.v ?? cell.v?.m ?? "";
      if (!val || String(val).trim() === "") continue;
      cols.push({
        name: String(val).trim(),
        type: "Text",
        order: cell.c,
      });
    }

    onColumnsChange?.(cols);
    setSheets(data);
  }

  function handleCellClick(row: number, col: number) {
    if (row === 0) {
      onColumnSelect?.(col);
    }
  }

  if (!Workbook) {
    return (
      <div style={{
        height, display: "flex", alignItems: "center", justifyContent: "center",
        background: "#f8f9fb", border: "1px solid var(--border)",
        borderRadius: "0 0 var(--radius-lg) var(--radius-lg)",
      }}>
        <div style={{ textAlign: "center" }}>
          <svg className="animate-spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" style={{ margin: "0 auto 10px", display: "block" }}>
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
          </svg>
          <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading spreadsheet…</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ height, border: "1px solid var(--border)", borderRadius: "0 0 var(--radius-lg) var(--radius-lg)", overflow: "hidden" }}>
      <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortune-sheet/react@1.0.4/dist/index.css" />
      <Workbook
        data={sheets}
        onChange={handleChange}
        onCellClick={handleCellClick}
        showToolbar={true}
        showFormulaBar={true}
        showStatisticBar={false}
        lang="en"
        style={{ width: "100%", height: "100%" }}
        toolbarItems={[
          "undo", "redo", "|",
          "format-painter", "|",
          "currency-format", "percentage-format", "|",
          "font-size", "|",
          "bold", "italic", "strike-through", "underline", "|",
          "font-color", "background", "|",
          "border", "|",
          "merge-cell", "|",
          "horizontal-alignment", "vertical-alignment", "|",
          "text-wrap", "|",
          "freeze", "|",
          "sort", "filter",
        ]}
      />
    </div>
  );
}
