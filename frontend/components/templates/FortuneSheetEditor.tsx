"use client";

import { useEffect, useRef, useState } from "react";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  onColumnsChange?: (cols: TemplateColumn[]) => void;
  height?: number;
}

export default function FortuneSheetEditor({ initialColumns = [], onColumnsChange, height = 520 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workbookRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    import("@fortune-sheet/react").then(mod => {
      if (cancelled || !containerRef.current) return;
      const { Workbook } = mod;
      const React = require("react");
      const ReactDOM = require("react-dom/client");

      const celldata: any[] = initialColumns.map((col, c) => ({
        r: 0, c, v: { v: col.name, m: col.name, ct: { fa: "@", t: "s" }, bl: 1 }
      }));

      const sheets = [{
        name: "Sheet1", id: "sheet1", status: 1, order: 0,
        row: 50, column: 26,
        defaultRowHeight: 25, defaultColWidth: 120,
        celldata, config: {},
      }];

      function handleChange(data: any[]) {
        if (!data?.length) return;
        const row0 = (data[0].celldata ?? [])
          .filter((c: any) => c.r === 0)
          .sort((a: any, b: any) => a.c - b.c);
        const cols: TemplateColumn[] = [];
        for (const cell of row0) {
          const val = String(cell.v?.v ?? cell.v?.m ?? "").trim();
          if (val) cols.push({ name: val, type: "Text", order: cell.c });
        }
        onColumnsChange?.(cols);
      }

      const root = ReactDOM.createRoot(containerRef.current);
      workbookRef.current = root;
      root.render(
        React.createElement(Workbook, {
          data: sheets,
          onChange: handleChange,
          showToolbar: true,
          showFormulaBar: true,
          showStatisticBar: false,
          allowEdit: true,
          lang: "en",
          style: { width: "100%", height: "100%" },
        })
      );
      if (!cancelled) setLoaded(true);
    }).catch(err => {
      if (!cancelled) setError(err?.message ?? "Failed to load");
    });

    return () => {
      cancelled = true;
      try { workbookRef.current?.unmount(); } catch {}
    };
  }, []);

  if (error) return (
    <div style={{ height, display:"flex", alignItems:"center", justifyContent:"center", background:"#fef2f2", border:"1px solid #fecaca", borderRadius:10 }}>
      <p style={{ color:"#dc2626", fontSize:13 }}>Spreadsheet failed to load: {error}</p>
    </div>
  );

  return (
    <div style={{ position:"relative", height, border:"1px solid var(--border)", borderRadius:10, overflow:"hidden" }}>
      {!loaded && (
        <div style={{ position:"absolute", inset:0, display:"flex", alignItems:"center", justifyContent:"center", background:"var(--surface2)", zIndex:1 }}>
          <p style={{ fontSize:13, color:"var(--text3)" }}>Loading spreadsheet…</p>
        </div>
      )}
      <div ref={containerRef} style={{ width:"100%", height:"100%" }} />
    </div>
  );
}