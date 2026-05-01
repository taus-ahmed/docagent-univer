"use client";

import { useEffect, useRef, useState } from "react";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  onColumnsChange?: (cols: TemplateColumn[]) => void;
  height?: number;
}

export default function FortuneSheetEditor({ initialColumns = [], onColumnsChange, height = 520 }: Props) {
  const [WorkbookComp, setWorkbookComp] = useState<React.ComponentType<any> | null>(null);
  const [sheets, setSheets] = useState<any[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  function buildSheets(cols: TemplateColumn[]): any[] {
    const celldata: any[] = [];
    if (cols.length > 0) {
      cols.forEach((col, c) => {
        celldata.push({ r: 0, c, v: { v: col.name, m: col.name, ct: { fa: "@", t: "s" }, bl: 1 } });
      });
    }
    return [{
      name: "Sheet1",
      id: "sheet1",
      status: 1,
      order: 0,
      hide: 0,
      row: 50,
      column: 26,
      defaultRowHeight: 25,
      defaultColWidth: 120,
      celldata,
      config: {},
      scrollLeft: 0,
      scrollTop: 0,
    }];
  }

  useEffect(() => {
    import("@fortune-sheet/react")
      .then(mod => {
        setWorkbookComp(() => mod.Workbook);
        setSheets(buildSheets(initialColumns));
      })
      .catch(err => setLoadError(err?.message ?? "Failed to load"));
  }, []);

  function handleChange(data: any[]) {
    if (!data?.length) return;
    setSheets(data);
    const sheet = data[0];
    const row0 = (sheet.celldata ?? [])
      .filter((c: any) => c.r === 0)
      .sort((a: any, b: any) => a.c - b.c);
    const cols: TemplateColumn[] = [];
    for (const cell of row0) {
      const val = String(cell.v?.v ?? cell.v?.m ?? "").trim();
      if (val) cols.push({ name: val, type: "Text", order: cell.c });
    }
    onColumnsChange?.(cols);
  }

  if (loadError) return (
    <div style={{ height, display:"flex", alignItems:"center", justifyContent:"center", background:"var(--surface2)", border:"1px solid var(--border)", borderRadius:10 }}>
      <p style={{ color:"var(--red)", fontSize:13 }}>Failed to load spreadsheet: {loadError}</p>
    </div>
  );

  if (!WorkbookComp) return (
    <div style={{ height, display:"flex", alignItems:"center", justifyContent:"center", background:"var(--surface2)", border:"1px solid var(--border)", borderRadius:10 }}>
      <p style={{ fontSize:13, color:"var(--text3)" }}>Loading spreadsheet…</p>
    </div>
  );

  return (
    <div style={{ height, border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      <WorkbookComp
        data={sheets}
        onChange={handleChange}
        showToolbar={true}
        showFormulaBar={true}
        showStatisticBar={true}
        allowEdit={true}
        lang="en"
        style={{ width:"100%", height:"100%" }}
      />
    </div>
  );
}